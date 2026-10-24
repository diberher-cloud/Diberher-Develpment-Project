"""Lista de trabajo, reserva de registros, ficha del cliente y consulta de llamadas (§4.4)."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.catalogos import ESTADOS_LLAMADA_ACTIVAS, ESTADOS_LLAMADA_TIPIFICABLES
from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import estado as estado_agente
from app.modulos.consola.esquemas import (
    CampanaConsola,
    CampanaResumen,
    CumplimientoSalida,
    FichaCliente,
    GestionHistorial,
    LlamadaSalida,
    MotivoSalida,
    RegistroTrabajo,
    TelefonoFicha,
)
from app.modulos.consola.guion import renderizar_guion
from app.modulos.consola.modelos import PromesaPago, Tipificacion, Venta
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.cumplimiento.motor import ResultadoEvaluacion
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar
from app.tiempo_real import bus

MAX_HISTORIAL = 20


# ---- Utilidades ------------------------------------------------------------------------------
def enmascarar_telefono(e164: str) -> str:
    """`+573001234567` -> `+57300****567` (primeros 6 + `****` + últimos 3)."""
    if len(e164) <= 9:
        return "****"
    return f"{e164[:6]}****{e164[-3:]}"


def reserva_vigente(cc: CampanaCliente, ahora: datetime) -> bool:
    return (
        cc.reservado_por is not None
        and cc.reservado_hasta is not None
        and cc.reservado_hasta > ahora
    )


def publicar_registro(db: Session, campana_id: int, cc_id: int | None, accion: str) -> None:
    bus.publicar(
        db,
        "consola.registro",
        {"campana_id": campana_id, "campana_cliente_id": cc_id, "accion": accion},
    )


def liberar_registro(cc: CampanaCliente, nuevo_estado: str = "pendiente") -> None:
    cc.estado = nuevo_estado
    cc.reservado_por = None
    cc.reservado_hasta = None


def _asignada(db: Session, usuario_id: int, campana_id: int) -> bool:
    return (
        db.scalar(
            select(CampanaAgente.id).where(
                CampanaAgente.campana_id == campana_id, CampanaAgente.usuario_id == usuario_id
            )
        )
        is not None
    )


def _no_asignada() -> ErrorApp:
    return ErrorApp(403, "CAMPANA_NO_ASIGNADA", "No está asignado a la campaña de este registro.")


# ---- Lista de trabajo ------------------------------------------------------------------------
def _condicion_trabajo(usuario_id: int, ahora: datetime):
    propia = and_(
        CampanaCliente.reservado_por == usuario_id, CampanaCliente.reservado_hasta > ahora
    )
    libre = or_(
        CampanaCliente.estado == "pendiente",
        and_(
            CampanaCliente.estado == "en_gestion",
            or_(CampanaCliente.reservado_hasta.is_(None), CampanaCliente.reservado_hasta <= ahora),
        ),
    )
    elegible = and_(
        libre,
        CampanaCliente.intentos < Campana.max_intentos,
        or_(
            CampanaCliente.proximo_intento_en.is_(None), CampanaCliente.proximo_intento_en <= ahora
        ),
    )
    return or_(propia, elegible)


def _base_trabajo(usuario_id: int, ahora: datetime):
    return (
        select(CampanaCliente)
        .join(Campana, Campana.id == CampanaCliente.campana_id)
        .join(
            CampanaAgente,
            and_(CampanaAgente.campana_id == Campana.id, CampanaAgente.usuario_id == usuario_id),
        )
        .where(Campana.estado == "activa", _condicion_trabajo(usuario_id, ahora))
    )


def campanas_asignadas(db: Session, usuario: Usuario, ahora: datetime) -> list[CampanaConsola]:
    pendientes = dict(
        db.execute(
            _base_trabajo(usuario.id, ahora)
            .with_only_columns(CampanaCliente.campana_id, func.count(CampanaCliente.id))
            .group_by(CampanaCliente.campana_id)
        ).all()
    )
    campanas = db.scalars(
        select(Campana)
        .join(CampanaAgente, CampanaAgente.campana_id == Campana.id)
        .where(CampanaAgente.usuario_id == usuario.id, Campana.estado == "activa")
        .order_by(Campana.nombre, Campana.id)
    )
    return [
        CampanaConsola(id=c.id, nombre=c.nombre, tipo=c.tipo, pendientes=pendientes.get(c.id, 0))  # type: ignore[arg-type]
        for c in campanas
    ]


def listar_registros(
    db: Session,
    usuario: Usuario,
    params: ParamsPaginacion,
    campana_id: int | None,
    ahora: datetime,
) -> tuple[list[RegistroTrabajo], int]:
    if campana_id is not None and not _asignada(db, usuario.id, campana_id):
        raise _no_asignada()
    mia = and_(CampanaCliente.reservado_por == usuario.id, CampanaCliente.reservado_hasta > ahora)
    consulta = (
        _base_trabajo(usuario.id, ahora)
        .join(Cliente, Cliente.id == CampanaCliente.cliente_id)
        .with_only_columns(CampanaCliente, Campana, Cliente.nombre)
        .order_by(
            case((mia, 0), else_=1),
            func.coalesce(CampanaCliente.proximo_intento_en, CampanaCliente.creado_en),
            CampanaCliente.id,
        )
    )
    if campana_id is not None:
        consulta = consulta.where(CampanaCliente.campana_id == campana_id)
    filas, total = paginar(db, consulta, params, escalares=False)
    items = [
        RegistroTrabajo(
            id=cc.id,
            campana_id=camp.id,
            campana_nombre=camp.nombre,
            tipo_campana=camp.tipo,  # type: ignore[arg-type]
            nombre_cliente=nombre,
            estado=cc.estado,  # type: ignore[arg-type]
            intentos=cc.intentos,
            max_intentos=camp.max_intentos,
            ultimo_resultado=cc.ultimo_resultado,  # type: ignore[arg-type]
            ultima_gestion_en=cc.ultima_gestion_en,
            proximo_intento_en=cc.proximo_intento_en,
            saldo_mora=cc.saldo_mora,
            dias_mora=cc.dias_mora,
            producto=cc.producto,
            reservado_por_mi=reserva_vigente(cc, ahora) and cc.reservado_por == usuario.id,
        )
        for cc, camp, nombre in filas
    ]
    return items, total


# ---- Reserva ---------------------------------------------------------------------------------
def _cargar(db: Session, registro_id: int) -> tuple[CampanaCliente, Campana]:
    cc = db.get(CampanaCliente, registro_id)
    if cc is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Registro no encontrado.")
    campana = db.get(Campana, cc.campana_id)
    assert campana is not None
    return cc, campana


def _llamada_pendiente_de_otro(usuario_id: int):
    """EXISTS (correlacionado con `campana_clientes`): llamada de OTRO agente sobre el registro
    que sigue activa o terminó sin tipificar. Protege el registro hasta que ese agente tipifique."""
    sin_tipificar = ~exists().where(Tipificacion.llamada_id == Llamada.id)
    return exists().where(
        Llamada.campana_cliente_id == CampanaCliente.id,
        Llamada.usuario_id != usuario_id,
        or_(
            Llamada.estado.in_(ESTADOS_LLAMADA_ACTIVAS),
            and_(Llamada.estado.in_(ESTADOS_LLAMADA_TIPIFICABLES), sin_tipificar),
        ),
    )


def llamada_pendiente_en_registro(db: Session, cc_id: int, usuario_id: int | None = None):
    """Primera llamada del registro activa o terminada sin tipificar (opcional: de un agente)."""
    sin_tipificar = ~exists().where(Tipificacion.llamada_id == Llamada.id)
    consulta = select(Llamada).where(
        Llamada.campana_cliente_id == cc_id,
        or_(
            Llamada.estado.in_(ESTADOS_LLAMADA_ACTIVAS),
            and_(Llamada.estado.in_(ESTADOS_LLAMADA_TIPIFICABLES), sin_tipificar),
        ),
    )
    if usuario_id is not None:
        consulta = consulta.where(Llamada.usuario_id == usuario_id)
    return db.scalars(consulta.limit(1)).first()


def _bloquear_asignacion(db: Session, usuario_id: int, registro_id: int) -> bool:
    """`FOR SHARE` sobre la asignación agente-campaña del registro; False si no existe."""
    return (
        db.scalar(
            select(CampanaAgente.id)
            .where(
                CampanaAgente.usuario_id == usuario_id,
                CampanaAgente.campana_id
                == select(CampanaCliente.campana_id)
                .where(CampanaCliente.id == registro_id)
                .scalar_subquery(),
            )
            .with_for_update(read=True)
        )
        is not None
    )


def _reservar_atomico(
    db: Session, registro_id: int, usuario_id: int, ahora: datetime, hasta: datetime
) -> bool:
    """UPDATE condicional: solo gana si está libre, ya es mío o la reserva caducó.

    S1: antes toma `FOR SHARE` sobre la fila de asignación (si no existe, no reserva): quitar la
    asignación espera a que esta transacción confirme y entonces libera la reserva recién hecha.
    """
    if not _bloquear_asignacion(db, usuario_id, registro_id):
        return False
    resultado = db.execute(
        update(CampanaCliente)
        .where(
            CampanaCliente.id == registro_id,
            CampanaCliente.estado.in_(("pendiente", "en_gestion")),
            or_(
                CampanaCliente.reservado_por.is_(None),
                CampanaCliente.reservado_por == usuario_id,
                and_(
                    CampanaCliente.reservado_hasta < ahora,
                    ~_llamada_pendiente_de_otro(
                        usuario_id
                    ),  # D-1/B2: sin robo con llamada pendiente
                ),
            ),
            # F-3: la asignación se comprueba en la misma sentencia que la reserva.
            exists().where(
                CampanaAgente.campana_id == CampanaCliente.campana_id,
                CampanaAgente.usuario_id == usuario_id,
            ),
        )
        .values(estado="en_gestion", reservado_por=usuario_id, reservado_hasta=hasta)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount == 1


def tomar(db: Session, usuario: Usuario, registro_id: int, ahora: datetime) -> FichaCliente:
    cc, campana = _cargar(db, registro_id)
    if not _asignada(db, usuario.id, campana.id):
        raise _no_asignada()
    no_disponible = ErrorApp(
        409, "REGISTRO_NO_DISPONIBLE", "El registro no está disponible para gestión."
    )
    if campana.estado != "activa" or cc.estado in ("gestionado", "descartado"):
        raise no_disponible
    mio_vigente = reserva_vigente(cc, ahora) and cc.reservado_por == usuario.id
    if not mio_vigente:
        pendiente = llamada_pendiente_en_registro(db, cc.id)
        llamada_ajena = pendiente is not None and pendiente.usuario_id != usuario.id
        if reserva_vigente(cc, ahora) or llamada_ajena:
            raise ErrorApp(409, "REGISTRO_RESERVADO", "El registro está reservado por otro agente.")
        if cc.intentos >= campana.max_intentos or (
            cc.proximo_intento_en is not None and cc.proximo_intento_en > ahora
        ):
            raise no_disponible
    estado = estado_agente.estado_actual(db, usuario.id)
    if estado == "en_llamada":
        raise ErrorApp(409, "AGENTE_EN_LLAMADA", "El agente está en una llamada.")
    if estado == "tipificando" or estado_agente.llamada_sin_tipificar(db, usuario.id):
        raise ErrorApp(409, "TIPIFICACION_PENDIENTE", "Debe tipificar la llamada anterior primero.")

    # Primero el bloqueo de la asignación (igual que `asignar_agentes`): ambos caminos toman
    # campana_agentes antes que las filas de campana_clientes y no hay ciclo de espera.
    if not _bloquear_asignacion(db, usuario.id, cc.id):
        db.rollback()
        raise _no_asignada()

    # Una reserva por agente: libera cualquier otra.
    otras = db.scalars(
        select(CampanaCliente).where(
            CampanaCliente.reservado_por == usuario.id, CampanaCliente.id != cc.id
        )
    ).all()
    for otra in otras:
        liberar_registro(otra)
        publicar_registro(db, otra.campana_id, otra.id, "liberado")

    hasta = ahora + timedelta(minutes=get_settings().consola_reserva_minutos)
    if not _reservar_atomico(db, cc.id, usuario.id, ahora, hasta):
        db.rollback()
        if not _asignada(
            db, usuario.id, campana.id
        ):  # desasignado entre la validación y la reserva
            raise _no_asignada()
        raise ErrorApp(409, "REGISTRO_RESERVADO", "El registro está reservado por otro agente.")
    db.refresh(cc)
    auditoria.registrar(
        db, "consola.tomar", usuario.id, "campana_cliente", cc.id, {"campana_id": campana.id}
    )
    auditoria.registrar(
        db, "consola.ficha_ver", usuario.id, "campana_cliente", cc.id, {"campana_id": campana.id}
    )
    publicar_registro(db, campana.id, cc.id, "reservado")
    ficha = construir_ficha(db, cc, campana, usuario, ahora)
    db.commit()
    return ficha


def soltar(db: Session, usuario: Usuario, registro_id: int, ahora: datetime) -> None:
    cc, campana = _cargar(db, registro_id)
    if not (reserva_vigente(cc, ahora) and cc.reservado_por == usuario.id):
        raise ErrorApp(409, "REGISTRO_NO_RESERVADO", "No tiene una reserva vigente del registro.")
    pendiente = llamada_pendiente_en_registro(db, cc.id)
    if pendiente is not None:
        if pendiente.estado in ESTADOS_LLAMADA_ACTIVAS:
            raise ErrorApp(409, "AGENTE_EN_LLAMADA", "Hay una llamada en curso sobre el registro.")
        raise ErrorApp(
            409, "TIPIFICACION_PENDIENTE", "Debe tipificar la llamada antes de soltar el registro."
        )
    liberar_registro(cc)
    publicar_registro(db, campana.id, cc.id, "liberado")
    db.commit()


def ver_ficha(db: Session, usuario: Usuario, registro_id: int, ahora: datetime) -> FichaCliente:
    cc, campana = _cargar(db, registro_id)
    if not (reserva_vigente(cc, ahora) and cc.reservado_por == usuario.id):
        raise ErrorApp(409, "REGISTRO_NO_RESERVADO", "No tiene una reserva vigente del registro.")
    if not _asignada(db, usuario.id, campana.id):
        # Excepción (D-1): puede ver la ficha de la gestión que dejó en curso o sin tipificar.
        if llamada_pendiente_en_registro(db, cc.id, usuario.id) is None:
            raise _no_asignada()
    auditoria.registrar(
        db, "consola.ficha_ver", usuario.id, "campana_cliente", cc.id, {"campana_id": campana.id}
    )
    ficha = construir_ficha(db, cc, campana, usuario, ahora)
    db.commit()
    return ficha


# ---- Ficha -----------------------------------------------------------------------------------
def _cumplimiento_salida(r: ResultadoEvaluacion, version: int) -> CumplimientoSalida:
    return CumplimientoSalida(
        permitido=r.permitido,
        motivos=[MotivoSalida(codigo=m.codigo, mensaje=m.mensaje) for m in r.motivos],
        momento_local=r.momento_local.isoformat(),
        proxima_ventana_inicio=(
            r.proxima_ventana_inicio.isoformat() if r.proxima_ventana_inicio else None
        ),
        politica_version=version,
    )


def exclusiones_de(db: Session, numeros: set[str], tipo_campana: str) -> dict[str, Exclusion]:
    if not numeros:
        return {}
    filas = db.scalars(
        select(Exclusion)
        .where(Exclusion.numero_e164.in_(numeros), Exclusion.aplica_a.in_((tipo_campana, "todas")))
        .order_by(Exclusion.id)
    )
    resultado: dict[str, Exclusion] = {}
    for f in filas:
        resultado.setdefault(f.numero_e164, f)
    return resultado


def _historial(db: Session, cc_id: int) -> list[GestionHistorial]:
    filas = db.execute(
        select(Tipificacion, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == Tipificacion.usuario_id)
        .where(Tipificacion.campana_cliente_id == cc_id)
        .order_by(Tipificacion.creado_en.desc(), Tipificacion.id.desc())
        .limit(MAX_HISTORIAL)
    ).all()
    ids = [t.id for t, _ in filas]
    promesas = {
        p.tipificacion_id: p
        for p in db.scalars(select(PromesaPago).where(PromesaPago.tipificacion_id.in_(ids)))
    }
    ventas = {
        v.tipificacion_id: v
        for v in db.scalars(select(Venta).where(Venta.tipificacion_id.in_(ids)))
    }
    from app.modulos.consola.esquemas import PromesaSalida, VentaSalida

    return [
        GestionHistorial(
            id=t.id,
            canal=t.canal,  # type: ignore[arg-type]
            origen=t.origen,  # type: ignore[arg-type]
            agente_nombre=nombre,
            resultado=t.resultado,  # type: ignore[arg-type]
            contacto_directo=t.contacto_directo,
            observacion=t.observacion,
            creado_en=t.creado_en,
            promesa=PromesaSalida.model_validate(promesas[t.id]) if t.id in promesas else None,
            venta=VentaSalida.model_validate(ventas[t.id]) if t.id in ventas else None,
            volver_a_llamar_en=t.volver_a_llamar_en,
        )
        for t, nombre in filas
    ]


def construir_ficha(
    db: Session, cc: CampanaCliente, campana: Campana, usuario: Usuario, ahora: datetime
) -> FichaCliente:
    from app.modulos.clientes.esquemas import ClienteSalida

    cliente = db.get(Cliente, cc.cliente_id)
    assert cliente is not None
    telefonos = list(
        db.scalars(
            select(Telefono)
            .where(Telefono.cliente_id == cliente.id)
            .order_by(Telefono.prioridad, Telefono.id)
        )
    )
    evaluacion, version = cumplimiento.evaluar_para_cliente(
        db, cliente.id, campana.tipo, "voz", ahora
    )
    excluidos = exclusiones_de(db, {t.numero_e164 for t in telefonos}, campana.tipo)
    intentos_ok = cc.intentos < campana.max_intentos
    fichas: list[TelefonoFicha] = []
    for t in telefonos:
        motivos: list[MotivoSalida] = []
        exc = excluidos.get(t.numero_e164)
        if exc is not None:
            motivos.append(
                MotivoSalida(codigo="EXCLUIDO", mensaje=f"Número excluido ({exc.motivo}).")
            )
        motivos.extend(MotivoSalida(codigo=m.codigo, mensaje=m.mensaje) for m in evaluacion.motivos)
        fichas.append(
            TelefonoFicha(
                id=t.id,
                numero_mascara=enmascarar_telefono(t.numero_e164),
                tipo_linea=t.tipo_linea,  # type: ignore[arg-type]
                prioridad=t.prioridad,
                excluido=exc is not None,
                llamable=exc is None and evaluacion.permitido and intentos_ok,
                motivos=motivos,
            )
        )
    nombre = cliente.nombre
    contexto: dict[str, Any] = {
        "nombre": nombre,
        "primer_nombre": nombre.split()[0] if nombre.split() else "",
        "saldo_total": cc.saldo_total,
        "saldo_mora": cc.saldo_mora,
        "dias_mora": cc.dias_mora,
        "fecha_vencimiento": cc.fecha_vencimiento,
        "numero_obligacion": cc.numero_obligacion,
        "producto": cc.producto,
        "oferta": cc.oferta,
        "empresa": get_settings().empresa_nombre,
        "agente": usuario.nombre,
        "datos": cc.datos_adicionales or {},
    }
    return FichaCliente(
        id=cc.id,
        campana=CampanaResumen(id=campana.id, nombre=campana.nombre, tipo=campana.tipo),  # type: ignore[arg-type]
        estado=cc.estado,  # type: ignore[arg-type]
        reservado_hasta=cc.reservado_hasta,
        intentos=cc.intentos,
        max_intentos=campana.max_intentos,
        ultimo_resultado=cc.ultimo_resultado,  # type: ignore[arg-type]
        proximo_intento_en=cc.proximo_intento_en,
        cliente=ClienteSalida(
            id=cliente.id,
            tipo_documento=cliente.tipo_documento,
            numero_documento=cliente.numero_documento,
            nombre=cliente.nombre,
            email=cliente.email,
            ciudad=cliente.ciudad,
        ),
        telefonos=fichas,
        numero_obligacion=cc.numero_obligacion,
        saldo_total=cc.saldo_total,
        saldo_mora=cc.saldo_mora,
        dias_mora=cc.dias_mora,
        fecha_vencimiento=cc.fecha_vencimiento,
        producto=cc.producto,
        oferta=cc.oferta,
        datos_adicionales=cc.datos_adicionales or {},
        guion=renderizar_guion(campana.guion, contexto),
        cumplimiento=_cumplimiento_salida(evaluacion, version),
        historial=_historial(db, cc.id),
    )


# ---- Llamadas --------------------------------------------------------------------------------
def obtener_llamada(db: Session, usuario: Usuario, llamada_id: int) -> LlamadaSalida:
    llamada = db.get(Llamada, llamada_id)
    if llamada is None or llamada.usuario_id != usuario.id:
        raise ErrorApp(404, "NO_ENCONTRADO", "Llamada no encontrada.")
    tipificada = (
        db.scalar(select(Tipificacion.id).where(Tipificacion.llamada_id == llamada.id)) is not None
    )
    return LlamadaSalida(
        id=llamada.id,
        campana_cliente_id=llamada.campana_cliente_id,
        telefono_id=llamada.telefono_id,
        canal=llamada.canal,  # type: ignore[arg-type]
        direccion=llamada.direccion,  # type: ignore[arg-type]
        estado=llamada.estado,
        motivos_bloqueo=[MotivoSalida(**m) for m in llamada.motivos_bloqueo or []],
        iniciada_en=llamada.iniciada_en,
        contestada_en=llamada.contestada_en,
        finalizada_en=llamada.finalizada_en,
        duracion_segundos=llamada.duracion_segundos,
        tipificada=tipificada,
    )
