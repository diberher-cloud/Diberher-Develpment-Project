"""Tipificación de llamadas y listado por campaña (§4.6)."""

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogos import ESTADOS_LLAMADA_TERMINALES, ESTADOS_NO_CONTESTADA
from app.config import get_settings
from app.errores import ErrorApp, detalle
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


def _en_rango(momento: datetime | None) -> bool:
    """True si el instante es convertible a UTC y cae entre los años 1984 y 2100."""
    if momento is None:
        return True
    try:
        return 1984 <= momento.astimezone(UTC).year <= 2100
    except (OverflowError, ValueError):
        return False


def _validar_presencia(datos: TipificacionCrear) -> list[dict]:
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

    errores = _validar_presencia(datos)
    if errores:
        raise _validacion(errores)
    r = datos.resultado
    if llamada.estado in ESTADOS_NO_CONTESTADA and r not in ("no_contesta", "numero_errado"):
        raise ErrorApp(
            422,
            "RESULTADO_INCOHERENTE",
            f"La llamada terminó en '{llamada.estado}'; "
            "solo admite 'no_contesta' o 'numero_errado'.",
        )
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
    monto = fecha_pago = valor_venta = None
    producto = None
    if datos.promesa is not None:
        monto = _decimal_positivo(datos.promesa.monto, "promesa.monto", errores)
        if monto is not None and cc.saldo_total is not None and monto > cc.saldo_total:
            errores.append(detalle("promesa.monto", "No puede superar el saldo total."))
        hoy = ahora.astimezone(zona).date()
        fecha_pago = datos.promesa.fecha_pago
        maximo = hoy + timedelta(days=get_settings().promesa_max_dias)
        if not hoy <= fecha_pago <= maximo:
            errores.append(
                detalle(
                    "promesa.fecha_pago",
                    f"Debe estar entre hoy y {get_settings().promesa_max_dias} días.",
                )
            )
    if datos.venta is not None:
        producto = " ".join(datos.venta.producto.split())
        if not 2 <= len(producto) <= 120:
            errores.append(detalle("venta.producto", "Debe tener entre 2 y 120 caracteres."))
        valor_venta = _decimal_positivo(datos.venta.valor, "venta.valor", errores)
    rastreable = _en_rango(datos.volver_a_llamar_en)
    festivos = cumplimiento.cargar_festivos(
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
            horario = motor.evaluar_horario(cuando, politica, festivos)
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

    # ---- efectos ----
    telefono = db.get(Telefono, llamada.telefono_id)
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
            proxima_ventana=lambda t: motor.proxima_ventana(t, politica, festivos),
        )
    )

    try:
        tip = Tipificacion(
            campana_cliente_id=cc.id,
            canal="voz",
            origen=origen,
            usuario_id=actor_id,
            llamada_id=llamada.id,
            resultado=r,
            contacto_directo=efecto.contacto_directo,
            observacion=observacion,
            volver_a_llamar_en=datos.volver_a_llamar_en,
            creado_en=ahora,
        )
        db.add(tip)
        db.flush()
        promesa = venta = None
        if efecto.crear_promesa and monto is not None and fecha_pago is not None:
            promesa = PromesaPago(
                tipificacion_id=tip.id,
                campana_cliente_id=cc.id,
                monto=monto,
                fecha_pago=fecha_pago,
                numero_cuotas=1,
                descuento_porcentaje=Decimal("0"),
                estado="vigente",
                origen=origen,
                creado_en=ahora,
            )
            db.add(promesa)
        if efecto.crear_venta and valor_venta is not None and producto is not None:
            venta = Venta(
                tipificacion_id=tip.id,
                campana_cliente_id=cc.id,
                producto=producto,
                valor=valor_venta,
                unidades=1,
                origen=origen,
                creado_en=ahora,
            )
            db.add(venta)
        if efecto.excluir_telefono and telefono is not None:
            existe = db.scalar(
                select(Exclusion.id).where(
                    Exclusion.numero_e164 == telefono.numero_e164, Exclusion.aplica_a == "todas"
                )
            )
            if existe is None:
                exclusion = Exclusion(
                    numero_e164=telefono.numero_e164,
                    motivo="numero_errado",
                    aplica_a="todas",
                    creado_por=agente_id,
                )
                db.add(exclusion)
                db.flush()
                auditoria.registrar(
                    db,
                    "exclusion.crear",
                    actor_id,
                    "exclusion",
                    exclusion.id,
                    {"motivo": "numero_errado", "aplica_a": "todas"},
                )
        # B2c: solo se libera/cierra el registro si la reserva sigue siendo de este agente. Si
        # otro agente lo tiene (caso excepcional), se registran la tipificación, el intento, la
        # exclusión y los contadores (intentos, último resultado), pero NO se toca su reserva,
        # el estado del registro ni `proximo_intento_en`.
        es_dueno = cc.reservado_por in (agente_id, None)
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
        if llamada.intento_contacto_id is not None:
            intento = db.get(IntentoContacto, llamada.intento_contacto_id)
            if intento is not None:
                intento.contacto_directo = efecto.contacto_directo
                intento.resultado = r
        actual = estado_agente.obtener(db, agente_id)
        if origen == "agente" or (
            actual is not None
            and actual.estado in ("tipificando", "en_llamada")
            and actual.llamada_id == llamada.id
        ):
            estado_agente.fijar(db, agente_id, "disponible", ahora)
        auditoria.registrar(
            db,
            "tipificacion.crear" if origen == "agente" else "consola.tipificacion_sistema",
            actor_id,
            "tipificacion",
            tip.id,
            {"tipificacion_id": tip.id, "llamada_id": llamada.id, "resultado": r},
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
    return _salida(tip, promesa, venta, cc)


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
