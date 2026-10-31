"""Tipificación de llamadas y listado por campaña (§4.6)."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogos import ESTADOS_LLAMADA_TERMINALES, ESTADOS_NO_CONTESTADA
from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, PromesaCuota
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import estado as estado_agente
from app.modulos.consola import servicio as consola
from app.modulos.consola.efectos import EntradaEfectos, calcular_efectos
from app.modulos.consola.esquemas import (
    PromesaSalida,
    RegistroResultante,
    TipificacionCampanaSalida,
    TipificacionCrear,
    TipificacionDatos,
    TipificacionSalida,
    VentaSalida,
)
from app.modulos.consola.modelos import PromesaPago, Tipificacion, Venta
from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar

_CENTAVOS = Decimal("0.01")


def _validacion(errores: list[dict]) -> ErrorApp:
    return ErrorApp(422, "VALIDACION", "Los datos enviados no son válidos.", errores)


_PATRON_MONTO = re.compile(r"\d{1,12}(\.\d{1,2})?", re.ASCII)


def _decimal_positivo(texto: str, campo: str, errores: list[dict]) -> Decimal | None:
    """Monto en texto plano: hasta 12 enteros y 2 decimales, sin signo, exponente ni separadores."""
    limpio = texto.strip()
    if len(limpio) > 20 or not _PATRON_MONTO.fullmatch(limpio):
        errores.append(
            detalle(campo, "Debe ser un número positivo con hasta 12 enteros y 2 decimales.")
        )
        return None
    valor = Decimal(limpio)
    if valor <= 0:
        errores.append(detalle(campo, "Debe ser mayor que cero."))
        return None
    return valor.quantize(_CENTAVOS)


def _validar_limites_ia(
    db: Session, campana: Campana, cc: CampanaCliente, monto: Decimal, errores: list[dict]
) -> None:
    """Promesas de humanos en cobranza con reglas de IA: mismos límites con una cuota
    (ADR-0015 §1). Lanza `422 FUERA_DE_LIMITES`."""
    from app.modulos.agente_ia.limites import (
        ErroresReglas,
        Obligacion,
        validar_promesa_humana,
        validar_reglas_cobranza,
    )

    cfg = db.get(ConfiguracionIACampana, campana.id)
    if cfg is None:
        return
    try:
        reglas = validar_reglas_cobranza(cfg.reglas)
    except ErroresReglas:
        return
    mensaje = validar_promesa_humana(Obligacion(cc.saldo_total, cc.saldo_mora), reglas, monto)
    if mensaje is not None and "saldo total" not in mensaje:
        raise ErrorApp(
            422,
            "FUERA_DE_LIMITES",
            "La promesa está fuera de los límites de negociación de la campaña.",
            [detalle("promesa.monto", mensaje)],
        )


def _en_rango(momento: datetime | None) -> bool:
    """True si el instante es convertible a UTC y cae entre los años 1984 y 2100."""
    if momento is None:
        return True
    try:
        return 1984 <= momento.astimezone(UTC).year <= 2100
    except (OverflowError, ValueError):
        return False


def _validar_presencia(datos: TipificacionDatos) -> list[dict]:
    errores: list[dict] = []
    r = datos.resultado

    def exigir(campo: str, presente: bool, requerido: bool) -> None:
        if requerido and not presente:
            errores.append(detalle(campo, "Obligatorio para este resultado."))
        if presente and not requerido:
            errores.append(detalle(campo, "No aplica para este resultado."))

    exigir("promesa", datos.promesa is not None, r == "promesa_pago")
    exigir("venta", datos.venta is not None, r == "venta")
    exigir("volver_a_llamar_en", datos.volver_a_llamar_en is not None, r == "volver_a_llamar")
    exigir("contacto_directo", datos.contacto_directo is not None, r == "volver_a_llamar")
    return errores


def tipificar(
    db: Session, usuario: Usuario, datos: TipificacionCrear, ahora: datetime
) -> TipificacionSalida:
    return _tipificar(db, datos, ahora, agente_id=usuario.id, actor_id=usuario.id, origen="agente")


def tipificar_sistema(
    db: Session, llamada_id: int, resultado: str, ahora: datetime
) -> TipificacionSalida:
    """Tipificación de soporte (origen `sistema`, sin usuario) de una llamada que su agente no
    tipificó. Aplica los mismos efectos que la del agente y libera su reserva."""
    llamada = db.get(Llamada, llamada_id)
    if llamada is None or llamada.usuario_id is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Llamada no encontrada.")
    datos = TipificacionCrear(llamada_id=llamada_id, resultado=resultado)  # type: ignore[arg-type]
    return _tipificar(
        db, datos, ahora, agente_id=llamada.usuario_id, actor_id=None, origen="sistema"
    )


@dataclass
class Validada:
    """Resultado de la validación común (llamada y conversación)."""

    politica: Any
    festivos: dict
    monto: Decimal | None = None
    fecha_pago: date | None = None
    producto: str | None = None
    valor_venta: Decimal | None = None
    observacion: str | None = None


def validar_comun(
    db: Session,
    datos: TipificacionDatos,
    cc: CampanaCliente,
    campana: Campana,
    ahora: datetime,
    coherencia: Callable[[], None] | None = None,
) -> Validada:
    """Validación de la tipificación (fase-2.md §4.6): campos condicionados, `coherencia` (propia
    de cada contexto, tras la presencia), resultado permitido, montos y fechas."""
    errores = _validar_presencia(datos)
    if errores:
        raise _validacion(errores)
    r = datos.resultado
    if coherencia is not None:
        coherencia()
    if (r == "promesa_pago" and campana.tipo != "cobranza") or (
        r == "venta" and campana.tipo != "venta"
    ):
        raise ErrorApp(
            422,
            "RESULTADO_NO_PERMITIDO",
            f"El resultado '{r}' no aplica a campañas de {campana.tipo}.",
        )

    observacion = (datos.observacion or "").strip() or None
    if observacion is not None and len(observacion) > 1000:
        raise _validacion([detalle("observacion", "Máximo 1000 caracteres.")])

    politica, _version = cumplimiento.cargar_politica(db, campana.tipo)
    zona = ZoneInfo(politica.zona_horaria)
    errores = []
    val = Validada(politica=politica, festivos={}, observacion=observacion)
    if datos.promesa is not None:
        val.monto = _decimal_positivo(datos.promesa.monto, "promesa.monto", errores)
        if val.monto is not None and cc.saldo_total is not None and val.monto > cc.saldo_total:
            errores.append(detalle("promesa.monto", "No puede superar el saldo total."))
        if val.monto is not None and campana.tipo == "cobranza":
            _validar_limites_ia(db, campana, cc, val.monto, errores)
        hoy = ahora.astimezone(zona).date()
        val.fecha_pago = datos.promesa.fecha_pago
        maximo = hoy + timedelta(days=get_settings().promesa_max_dias)
        if not hoy <= val.fecha_pago <= maximo:
            errores.append(
                detalle(
                    "promesa.fecha_pago",
                    f"Debe estar entre hoy y {get_settings().promesa_max_dias} días.",
                )
            )
    if datos.venta is not None:
        val.producto = " ".join(datos.venta.producto.split())
        if not 2 <= len(val.producto) <= 120:
            errores.append(detalle("venta.producto", "Debe tener entre 2 y 120 caracteres."))
        val.valor_venta = _decimal_positivo(datos.venta.valor, "venta.valor", errores)
    rastreable = _en_rango(datos.volver_a_llamar_en)
    val.festivos = cumplimiento.cargar_festivos(
        db, datos.volver_a_llamar_en if rastreable and datos.volver_a_llamar_en else ahora, politica
    )
    if datos.volver_a_llamar_en is not None:
        cuando = datos.volver_a_llamar_en
        if not rastreable:
            errores.append(
                detalle("volver_a_llamar_en", "La fecha debe estar entre los años 1984 y 2100.")
            )
        elif not ahora + timedelta(minutes=5) < cuando <= ahora + timedelta(days=30):
            errores.append(
                detalle(
                    "volver_a_llamar_en",
                    "Debe ser posterior a 5 minutos desde ahora y no exceder 30 días.",
                )
            )
        else:
            horario = motor.evaluar_horario(cuando, politica, val.festivos)
            if not horario.permitido:
                sugerida = (
                    f" Próxima ventana: {horario.proxima_ventana_inicio.isoformat()}"
                    if horario.proxima_ventana_inicio
                    else ""
                )
                raise ErrorApp(
                    422,
                    "VOLVER_A_LLAMAR_FUERA_DE_FRANJA",
                    "La fecha de rellamada no está permitida por la política de cumplimiento.",
                    [detalle("volver_a_llamar_en", f"Fuera de franja.{sugerida}")],
                )
    if errores:
        raise _validacion(errores)
    return val


@dataclass
class DetallePromesa:
    """Acuerdo de la IA: varias cuotas con periodicidad (fase-2c.md §4.8)."""

    monto_total: Decimal
    cuotas: list[tuple[date, Decimal]]
    periodicidad: str
    descuento_porcentaje: Decimal
    reglas_version: int | None


@dataclass
class DetalleVenta:
    producto: str
    valor: Decimal
    unidades: int
    oferta_id: int | None
    descuento_porcentaje: Decimal
    reglas_version: int | None


@dataclass
class Aplicada:
    tip: Tipificacion
    promesa: PromesaPago | None
    venta: Venta | None
    efecto: Any
    es_dueno: bool


def aplicar_efectos(
    db: Session,
    datos: TipificacionDatos,
    val: Validada,
    cc: CampanaCliente,
    campana: Campana,
    telefono: Telefono | None,
    ahora: datetime,
    *,
    canal: str,
    origen: str,
    actor_id: int | None,
    gestor_id: int | None,
    llamada_id: int | None = None,
    conversacion_id: int | None = None,
    origen_exclusion: str = "usuario",
    detalle_promesa: DetallePromesa | None = None,
    detalle_venta: DetalleVenta | None = None,
) -> Aplicada:
    """Crea la tipificación (y promesa/venta/exclusión) y actualiza el registro (B2c: solo
    libera/cierra el registro si la reserva es de `gestor_id` o está libre). Sin commit."""
    r = datos.resultado
    otros_llamables = False
    if r == "numero_errado" and telefono is not None:
        otros = db.scalars(
            select(Telefono).where(Telefono.cliente_id == cc.cliente_id, Telefono.id != telefono.id)
        ).all()
        excluidos = consola.exclusiones_de(db, {t.numero_e164 for t in otros}, campana.tipo)
        otros_llamables = any(t.numero_e164 not in excluidos for t in otros)
    efecto = calcular_efectos(
        EntradaEfectos(
            resultado=r,
            ahora=ahora,
            intentos=cc.intentos,
            max_intentos=campana.max_intentos,
            intervalo_reintento_minutos=campana.intervalo_reintento_minutos,
            contacto_directo_pedido=datos.contacto_directo,
            volver_a_llamar_en=datos.volver_a_llamar_en,
            quedan_telefonos_llamables=otros_llamables,
            proxima_ventana=lambda t: motor.proxima_ventana(t, val.politica, val.festivos),
        )
    )
    tip = Tipificacion(
        campana_cliente_id=cc.id,
        canal=canal,
        origen=origen,
        usuario_id=actor_id,
        llamada_id=llamada_id,
        conversacion_id=conversacion_id,
        resultado=r,
        contacto_directo=efecto.contacto_directo,
        observacion=val.observacion,
        volver_a_llamar_en=datos.volver_a_llamar_en,
        creado_en=ahora,
    )
    db.add(tip)
    db.flush()
    promesa = venta = None
    if efecto.crear_promesa and detalle_promesa is not None:
        promesa = PromesaPago(
            tipificacion_id=tip.id,
            campana_cliente_id=cc.id,
            monto=detalle_promesa.monto_total,
            fecha_pago=detalle_promesa.cuotas[0][0],
            numero_cuotas=len(detalle_promesa.cuotas),
            descuento_porcentaje=detalle_promesa.descuento_porcentaje,
            periodicidad=detalle_promesa.periodicidad,
            reglas_version=detalle_promesa.reglas_version,
            estado="vigente",
            origen=origen,
            creado_en=ahora,
        )
        db.add(promesa)
        db.flush()
        for numero, (fecha, monto) in enumerate(detalle_promesa.cuotas, start=1):
            db.add(PromesaCuota(promesa_id=promesa.id, numero=numero, fecha=fecha, monto=monto))
    elif efecto.crear_promesa and val.monto is not None and val.fecha_pago is not None:
        promesa = PromesaPago(
            tipificacion_id=tip.id,
            campana_cliente_id=cc.id,
            monto=val.monto,
            fecha_pago=val.fecha_pago,
            numero_cuotas=1,
            descuento_porcentaje=Decimal("0"),
            estado="vigente",
            origen=origen,
            creado_en=ahora,
        )
        db.add(promesa)
    if efecto.crear_venta and detalle_venta is not None:
        venta = Venta(
            tipificacion_id=tip.id,
            campana_cliente_id=cc.id,
            producto=detalle_venta.producto,
            valor=detalle_venta.valor,
            unidades=detalle_venta.unidades,
            oferta_id=detalle_venta.oferta_id,
            descuento_porcentaje=detalle_venta.descuento_porcentaje,
            reglas_version=detalle_venta.reglas_version,
            origen=origen,
            creado_en=ahora,
        )
        db.add(venta)
    elif efecto.crear_venta and val.valor_venta is not None and val.producto is not None:
        venta = Venta(
            tipificacion_id=tip.id,
            campana_cliente_id=cc.id,
            producto=val.producto,
            valor=val.valor_venta,
            unidades=1,
            origen=origen,
            creado_en=ahora,
        )
        db.add(venta)
    if efecto.excluir_telefono and telefono is not None:
        existe = db.scalar(
            select(Exclusion.id).where(
                Exclusion.numero_e164 == telefono.numero_e164,
                Exclusion.aplica_a == "todas",
                Exclusion.canal == "todos",
            )
        )
        if existe is None:
            exclusion = Exclusion(
                numero_e164=telefono.numero_e164,
                motivo="numero_errado",
                aplica_a="todas",
                origen=origen_exclusion,
                creado_por=gestor_id,
            )
            db.add(exclusion)
            db.flush()
            auditoria.registrar(
                db,
                "exclusion.crear",
                actor_id,
                "exclusion",
                exclusion.id,
                {"motivo": "numero_errado", "aplica_a": "todas"}
                | ({"origen": origen_exclusion} if origen_exclusion != "usuario" else {}),
            )
    # B2c: solo se libera/cierra el registro si la reserva sigue siendo de este agente. Si
    # otro agente lo tiene (caso excepcional), se registran la tipificación, el intento, la
    # exclusión y los contadores (intentos, último resultado), pero NO se toca su reserva,
    # el estado del registro ni `proximo_intento_en`.
    es_dueno = cc.reservado_por in (gestor_id, None)
    # Contador con UPDATE atómico (`intentos = intentos + 1`): no pisa incrementos concurrentes.
    db.flush()
    db.execute(
        update(CampanaCliente)
        .where(CampanaCliente.id == cc.id)
        .values(intentos=CampanaCliente.intentos + 1)
        .execution_options(synchronize_session=False)
    )
    db.refresh(cc)
    if es_dueno:
        consola.liberar_registro(cc)
        cc.estado = efecto.estado
        cc.proximo_intento_en = efecto.proximo_intento_en
    cc.ultimo_resultado = r
    cc.ultima_gestion_en = ahora
    return Aplicada(tip, promesa, venta, efecto, es_dueno)


def _tipificar(
    db: Session,
    datos: TipificacionCrear,
    ahora: datetime,
    *,
    agente_id: int,
    actor_id: int | None,
    origen: str,
) -> TipificacionSalida:
    llamada = db.get(Llamada, datos.llamada_id)
    if llamada is None or llamada.usuario_id != agente_id:
        raise ErrorApp(404, "NO_ENCONTRADO", "Llamada no encontrada.")
    if llamada.estado not in ESTADOS_LLAMADA_TERMINALES:
        raise ErrorApp(409, "LLAMADA_EN_CURSO", "La llamada aún no ha terminado.")
    if llamada.estado == "bloqueada":
        raise ErrorApp(409, "LLAMADA_BLOQUEADA", "La llamada no se realizó (bloqueada).")
    if db.scalar(select(Tipificacion.id).where(Tipificacion.llamada_id == llamada.id)):
        raise ErrorApp(409, "LLAMADA_YA_TIPIFICADA", "La llamada ya fue tipificada.")

    cc = db.get(CampanaCliente, llamada.campana_cliente_id)
    campana = db.get(Campana, cc.campana_id) if cc else None
    if cc is None or campana is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Registro no encontrado.")

    # Orden de bloqueo estados_agente -> clientes, el mismo que `procesar_saliente`, para no crear
    # ciclos de espera entre una llamada nueva y una tipificación del mismo agente/cliente.
    estado_agente.bloquear(db, agente_id)
    db.execute(select(Cliente.id).where(Cliente.id == cc.cliente_id).with_for_update()).all()
    db.refresh(cc)
    if db.scalar(select(Tipificacion.id).where(Tipificacion.llamada_id == llamada.id)):
        db.rollback()  # otra tipificación simultánea ganó mientras esperábamos el bloqueo
        raise ErrorApp(409, "LLAMADA_YA_TIPIFICADA", "La llamada ya fue tipificada.")

    def coherencia() -> None:
        if llamada.estado in ESTADOS_NO_CONTESTADA and datos.resultado not in (
            "no_contesta",
            "numero_errado",
        ):
            raise ErrorApp(
                422,
                "RESULTADO_INCOHERENTE",
                f"La llamada terminó en '{llamada.estado}'; "
                "solo admite 'no_contesta' o 'numero_errado'.",
            )

    val = validar_comun(db, datos, cc, campana, ahora, coherencia)
    telefono = db.get(Telefono, llamada.telefono_id)
    try:
        aplicada = aplicar_efectos(
            db,
            datos,
            val,
            cc,
            campana,
            telefono,
            ahora,
            canal="voz",
            origen=origen,
            actor_id=actor_id,
            gestor_id=agente_id,
            llamada_id=llamada.id,
        )
        tip, efecto, es_dueno = aplicada.tip, aplicada.efecto, aplicada.es_dueno
        if llamada.intento_contacto_id is not None:
            intento = db.get(IntentoContacto, llamada.intento_contacto_id)
            if intento is not None:
                intento.contacto_directo = efecto.contacto_directo
                intento.resultado = datos.resultado
        actual = estado_agente.obtener(db, agente_id)
        if origen == "agente" or (
            actual is not None
            and actual.estado in ("tipificando", "en_llamada")
            and actual.llamada_id == llamada.id
        ):
            propietario = db.get(Usuario, agente_id)
            inactivo = origen == "sistema" and propietario is not None and not propietario.activo
            # Un agente desactivado no queda `disponible`.
            estado_agente.fijar(db, agente_id, "desconectado" if inactivo else "disponible", ahora)
        auditoria.registrar(
            db,
            "tipificacion.crear" if origen == "agente" else "consola.tipificacion_sistema",
            actor_id,
            "tipificacion",
            tip.id,
            {"tipificacion_id": tip.id, "llamada_id": llamada.id, "resultado": datos.resultado},
        )
        if es_dueno:
            consola.publicar_registro(
                db, campana.id, cc.id, "gestionado" if efecto.cierra_registro else "liberado"
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorApp(409, "LLAMADA_YA_TIPIFICADA", "La llamada ya fue tipificada.") from exc
    except Exception:
        db.rollback()
        raise
    return _salida(tip, aplicada.promesa, aplicada.venta, cc)


def _salida(
    tip: Tipificacion, promesa: PromesaPago | None, venta: Venta | None, cc: CampanaCliente
) -> TipificacionSalida:
    return TipificacionSalida(
        **_base(tip, promesa, venta),
        registro=RegistroResultante(
            estado=cc.estado,  # type: ignore[arg-type]
            intentos=cc.intentos,
            proximo_intento_en=cc.proximo_intento_en,
        ),
    )


def _base(tip: Tipificacion, promesa: PromesaPago | None, venta: Venta | None) -> dict:
    return {
        "id": tip.id,
        "campana_cliente_id": tip.campana_cliente_id,
        "llamada_id": tip.llamada_id,
        "conversacion_id": tip.conversacion_id,
        "canal": tip.canal,
        "origen": tip.origen,
        "usuario_id": tip.usuario_id,
        "resultado": tip.resultado,
        "contacto_directo": tip.contacto_directo,
        "observacion": tip.observacion,
        "promesa": PromesaSalida.model_validate(promesa) if promesa else None,
        "venta": VentaSalida.model_validate(venta) if venta else None,
        "volver_a_llamar_en": tip.volver_a_llamar_en,
        "creado_en": tip.creado_en,
    }


def listar_campana(
    db: Session,
    campana_id: int,
    params: ParamsPaginacion,
    resultado: str | None,
    origen: str | None,
    desde: date | None,
    hasta: date | None,
) -> tuple[list[TipificacionCampanaSalida], int]:
    campana = db.get(Campana, campana_id)
    if campana is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    politica, _ = cumplimiento.cargar_politica(db, campana.tipo)
    zona = ZoneInfo(politica.zona_horaria)
    consulta = (
        select(Tipificacion, Cliente.nombre, Usuario.nombre)
        .join(CampanaCliente, CampanaCliente.id == Tipificacion.campana_cliente_id)
        .join(Cliente, Cliente.id == CampanaCliente.cliente_id)
        .outerjoin(Usuario, Usuario.id == Tipificacion.usuario_id)
        .where(CampanaCliente.campana_id == campana_id)
    )
    if resultado:
        consulta = consulta.where(Tipificacion.resultado == resultado)
    if origen:
        consulta = consulta.where(Tipificacion.origen == origen)
    for nombre, valor in (("desde", desde), ("hasta", hasta)):
        if valor is not None and not 1984 <= valor.year <= 2100:
            raise ErrorApp(
                422,
                "VALIDACION",
                "Los datos enviados no son válidos.",
                [detalle(nombre, "La fecha debe estar entre los años 1984 y 2100.")],
            )
    try:
        if desde:
            consulta = consulta.where(
                Tipificacion.creado_en >= datetime.combine(desde, time.min, tzinfo=zona)
            )
        if hasta:
            consulta = consulta.where(
                Tipificacion.creado_en
                < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona)
            )
    except OverflowError as exc:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("hasta", "Fecha fuera de rango.")],
        ) from exc
    consulta = consulta.order_by(Tipificacion.creado_en.desc(), Tipificacion.id.desc())
    filas, total = paginar(db, consulta, params, escalares=False)
    ids = [t.id for t, _, _ in filas]
    promesas = {
        p.tipificacion_id: p
        for p in db.scalars(select(PromesaPago).where(PromesaPago.tipificacion_id.in_(ids)))
    }
    ventas = {
        v.tipificacion_id: v
        for v in db.scalars(select(Venta).where(Venta.tipificacion_id.in_(ids)))
    }
    items = [
        TipificacionCampanaSalida(
            **_base(t, promesas.get(t.id), ventas.get(t.id)),
            cliente_nombre=cliente,
            agente_nombre=agente,
        )
        for t, cliente, agente in filas
    ]
    return items, total
