"""TwiML saliente con cumplimiento, webhooks de estado/grabación y finalización (§4.5)."""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogos import ESTADOS_LLAMADA_TERMINALES
from app.config import get_settings
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import estado as estado_agente
from app.modulos.consola.servicio import exclusiones_de, reserva_vigente
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.telefonia import twiml
from app.modulos.telefonia.modelos import EventoLlamada, Grabacion, Llamada
from app.modulos.usuarios.modelos import Usuario
from app.tiempo_real import bus

logger = logging.getLogger("app")
_FROM = re.compile(r"client:agente_(\d{1,10})")
_ENTERO = re.compile(r"\d{1,10}")
MAX_INT32 = 2**31 - 1

# Estado final según el estado terminal del proveedor.
_TERMINALES_PROVEEDOR = {"completed", "busy", "no-answer", "failed", "canceled"}


@dataclass
class ResultadoSaliente:
    xml: str
    permitida: bool
    llamada_id: int | None
    motivos: list[dict[str, str]] = field(default_factory=list)


def _motivo(codigo: str, mensaje: str) -> dict[str, str]:
    return {"codigo": codigo, "mensaje": mensaje}


def _entero(valor: str | None) -> int | None:
    if valor is None or not _ENTERO.fullmatch(valor.strip()):
        return None
    n = int(valor.strip())
    return n if 1 <= n <= MAX_INT32 else None


def _xml_rechazo() -> str:
    s = get_settings()
    return twiml.twiml_rechazo(s.telefonia_mensaje_bloqueo, s.telefonia_idioma_voz)


def _xml_marcar(llamada: Llamada, numero: str) -> str:
    s = get_settings()
    return twiml.twiml_marcar(
        numero=numero,
        base_url=s.public_base_url,
        llamada_id=llamada.id,
        grabar=s.telefonia_grabar,
        caller_id=s.twilio_numero_saliente or None,
    )


def _xml_de_llamada(db: Session, llamada: Llamada) -> str:
    if llamada.estado == "bloqueada":
        return _xml_rechazo()
    telefono = db.get(Telefono, llamada.telefono_id)
    assert telefono is not None
    return _xml_marcar(llamada, telefono.numero_e164)


def _publicar_llamada(db: Session, llamada: Llamada, campana_id: int) -> None:
    bus.publicar(
        db,
        "llamada.estado",
        {
            "llamada_id": llamada.id,
            "usuario_id": llamada.usuario_id,
            "campana_id": campana_id,
            "campana_cliente_id": llamada.campana_cliente_id,
            "estado": llamada.estado,
            "motivos": llamada.motivos_bloqueo or [],
        },
    )


# ---- TwiML saliente --------------------------------------------------------------------------
def procesar_saliente(
    db: Session,
    *,
    call_sid: str,
    desde: str,
    account_sid: str | None,
    campana_cliente_id: str | None,
    telefono_id: str | None,
    ahora: datetime,
    verificar_cuenta: bool,
) -> ResultadoSaliente:
    """Valida en el orden de §4.5 y crea la llamada (permitida o bloqueada)."""
    rechazo = ResultadoSaliente(_xml_rechazo(), False, None)
    settings = get_settings()

    # 2. agente
    m = _FROM.fullmatch((desde or "").strip())
    agente = db.get(Usuario, int(m.group(1))) if m and int(m.group(1)) <= MAX_INT32 else None
    cuenta_ok = not verificar_cuenta or account_sid == settings.twilio_account_sid
    if agente is None or not agente.activo or agente.rol != "agente" or not cuenta_ok:
        logger.warning("TwiML saliente rechazado: AGENTE_INVALIDO")
        rechazo.motivos = [_motivo("AGENTE_INVALIDO", "Agente inválido.")]
        return rechazo

    # 3. parámetros
    cc_id, tel_id = _entero(campana_cliente_id), _entero(telefono_id)
    cc = db.get(CampanaCliente, cc_id) if cc_id else None
    telefono = db.get(Telefono, tel_id) if tel_id else None
    if cc is None or telefono is None or telefono.cliente_id != cc.cliente_id:
        logger.warning("TwiML saliente rechazado: PARAMETROS_INVALIDOS")
        rechazo.motivos = [_motivo("PARAMETROS_INVALIDOS", "Parámetros inválidos.")]
        return rechazo

    # B4: serializa las llamadas simultáneas del mismo agente y del mismo cliente. Orden fijo de
    # bloqueo (estados_agente, luego clientes) y lectura fresca tras obtener los bloqueos.
    estado_agente.bloquear(db, agente.id)
    db.execute(select(Cliente.id).where(Cliente.id == cc.cliente_id).with_for_update()).all()
    db.refresh(cc)

    # 4. idempotencia por CallSid
    existente = db.scalar(select(Llamada).where(Llamada.call_sid == call_sid))
    if existente is not None:
        return _resultado_existente(db, existente, agente)

    campana = db.get(Campana, cc.campana_id)
    assert campana is not None
    motivos, version = _validar_permiso(db, agente, campana, cc, telefono, ahora)

    try:
        if motivos:
            llamada = Llamada(
                campana_cliente_id=cc.id,
                telefono_id=telefono.id,
                usuario_id=agente.id,
                call_sid=call_sid,
                estado="bloqueada",
                motivos_bloqueo=motivos,
                iniciada_en=ahora,
                finalizada_en=ahora,
            )
            db.add(llamada)
            db.flush()
            auditoria.registrar(
                db,
                "llamada.bloqueada",
                agente.id,
                "llamada",
                llamada.id,
                {"llamada_id": llamada.id, "codigos": [x["codigo"] for x in motivos]},
            )
            _publicar_llamada(db, llamada, campana.id)
            db.commit()
            return ResultadoSaliente(_xml_rechazo(), False, llamada.id, motivos)

        intento = cumplimiento.registrar_intento(
            db,
            cliente_id=cc.cliente_id,
            tipo_campana=campana.tipo,
            canal="voz",
            iniciado_por="empresa",
            momento=ahora,
            campana_id=campana.id,
            campana_cliente_id=cc.id,
            telefono_id=telefono.id,
            politica_version=version,
        )
        llamada = Llamada(
            campana_cliente_id=cc.id,
            telefono_id=telefono.id,
            usuario_id=agente.id,
            call_sid=call_sid,
            estado="iniciando",
            motivos_bloqueo=[],
            intento_contacto_id=intento.id,
            iniciada_en=ahora,
        )
        db.add(llamada)
        db.flush()
        estado_agente.fijar(db, agente.id, "en_llamada", ahora, llamada_id=llamada.id)
        cc.reservado_hasta = ahora + timedelta(minutes=settings.consola_reserva_minutos)
        auditoria.registrar(
            db, "llamada.iniciada", agente.id, "llamada", llamada.id, {"llamada_id": llamada.id}
        )
        _publicar_llamada(db, llamada, campana.id)
        xml = _xml_marcar(llamada, telefono.numero_e164)
        db.commit()
        return ResultadoSaliente(xml, True, llamada.id, [])
    except IntegrityError:
        # Carrera por CallSid: otra petición creó la llamada primero.
        db.rollback()
        existente = db.scalar(select(Llamada).where(Llamada.call_sid == call_sid))
        if existente is None:
            raise
        return _resultado_existente(db, existente, agente)


def _resultado_existente(db: Session, llamada: Llamada, agente: Usuario) -> ResultadoSaliente:
    if llamada.usuario_id != agente.id:
        logger.warning("TwiML saliente rechazado: AGENTE_INVALIDO")
        return ResultadoSaliente(
            _xml_rechazo(), False, None, [_motivo("AGENTE_INVALIDO", "Agente inválido.")]
        )
    bloqueada = llamada.estado == "bloqueada"
    return ResultadoSaliente(
        _xml_de_llamada(db, llamada),
        not bloqueada,
        llamada.id,
        list(llamada.motivos_bloqueo or []),
    )


def _validar_permiso(
    db: Session,
    agente: Usuario,
    campana: Campana,
    cc: CampanaCliente,
    telefono: Telefono,
    ahora: datetime,
) -> tuple[list[dict[str, str]], int | None]:
    """Pasos 5-12. Devuelve (motivos, versión de política); sin motivos = permitida."""
    if estado_agente.llamada_sin_tipificar(db, agente.id) is not None:
        return [
            _motivo("TIPIFICACION_PENDIENTE", "Tiene una llamada pendiente por tipificar.")
        ], None
    if estado_agente.estado_actual(db, agente.id) != "disponible":
        return [
            _motivo("AGENTE_NO_DISPONIBLE", "El agente debe estar en estado 'disponible'.")
        ], None
    if campana.estado != "activa":
        return [_motivo("CAMPANA_NO_ACTIVA", "La campaña no está activa.")], None
    asignado = db.scalar(
        select(CampanaAgente.id).where(
            CampanaAgente.campana_id == campana.id, CampanaAgente.usuario_id == agente.id
        )
    )
    if asignado is None:
        return [_motivo("CAMPANA_NO_ASIGNADA", "El agente no está asignado a la campaña.")], None
    if not (reserva_vigente(cc, ahora) and cc.reservado_por == agente.id):
        return [
            _motivo("REGISTRO_NO_RESERVADO", "El registro no está reservado por el agente.")
        ], None
    if cc.intentos >= campana.max_intentos:
        return [_motivo("INTENTOS_AGOTADOS", "El registro agotó sus intentos.")], None
    if exclusiones_de(db, {telefono.numero_e164}, campana.tipo):
        return [_motivo("EXCLUIDO", "El número está excluido.")], None
    evaluacion, version = cumplimiento.evaluar_para_cliente(
        db, cc.cliente_id, campana.tipo, "voz", ahora
    )
    if not evaluacion.permitido:
        return [_motivo(m.codigo, m.mensaje) for m in evaluacion.motivos], version
    return [], version


# ---- Estados ---------------------------------------------------------------------------------
def _campana_de(db: Session, llamada: Llamada) -> int:
    cc = db.get(CampanaCliente, llamada.campana_cliente_id)
    assert cc is not None
    return cc.campana_id


def _estado_final(estado_proveedor: str, contestada: bool) -> str:
    if estado_proveedor == "completed":
        return "completada" if contestada else "no_contesta"
    return {
        "busy": "ocupado",
        "no-answer": "no_contesta",
        "failed": "fallida",
        "canceled": "cancelada",
    }[estado_proveedor]


def finalizar(
    db: Session,
    llamada: Llamada,
    estado_proveedor: str,
    duracion: int | None,
    ahora: datetime,
    contestada: bool = False,
) -> bool:
    """Finalización idempotente: gana la primera señal terminal. Devuelve True si finalizó.

    El UPDATE es condicional (`estado` no terminal), así que dos señales simultáneas no pueden
    finalizar dos veces: la perdedora ve 0 filas y no hace nada. `contestada=True` indica que
    el proveedor informa de tiempo de conversación (p. ej. `DialCallDuration > 0`) aunque se
    haya perdido el callback `answered`.
    """
    db.flush()
    db.refresh(llamada)
    if llamada.estado in ESTADOS_LLAMADA_TERMINALES:
        return False
    contestada_en = llamada.contestada_en
    if contestada_en is None and contestada and duracion:
        contestada_en = ahora - timedelta(seconds=duracion)
    nuevo = _estado_final(estado_proveedor, contestada_en is not None)
    if duracion is not None:
        segundos: int | None = max(duracion, 0)
    elif contestada_en is not None:
        segundos = max(int((ahora - contestada_en).total_seconds()), 0)
    else:
        segundos = None
    valores: dict[str, Any] = {"estado": nuevo, "finalizada_en": ahora}
    if contestada_en is not None:
        valores["contestada_en"] = contestada_en
    if segundos is not None:
        valores["duracion_segundos"] = segundos
    ganada = db.execute(
        update(Llamada)
        .where(Llamada.id == llamada.id, Llamada.estado.not_in(ESTADOS_LLAMADA_TERMINALES))
        .values(**valores)
        .execution_options(synchronize_session=False)
    )
    db.refresh(llamada)
    if ganada.rowcount != 1:
        return False
    if llamada.usuario_id is not None:
        # B2: el registro sigue protegido (reserva renovada) hasta que el agente tipifique.
        cc = db.get(CampanaCliente, llamada.campana_cliente_id)
        if cc is not None and cc.reservado_por == llamada.usuario_id:
            cc.reservado_hasta = ahora + timedelta(minutes=get_settings().consola_reserva_minutos)
        estado_agente.fijar(db, llamada.usuario_id, "tipificando", ahora, llamada_id=llamada.id)
    _publicar_llamada(db, llamada, _campana_de(db, llamada))
    return True


def _renovar_reserva(db: Session, llamada: Llamada, ahora: datetime) -> None:
    """D-1: mientras la llamada siga activa, cada webhook de estado renueva la reserva."""
    if llamada.estado in ESTADOS_LLAMADA_TERMINALES or llamada.usuario_id is None:
        return
    cc = db.get(CampanaCliente, llamada.campana_cliente_id)
    if cc is not None and cc.reservado_por == llamada.usuario_id:
        cc.reservado_hasta = ahora + timedelta(minutes=get_settings().consola_reserva_minutos)


def _entero_opcional(valor: str | None) -> int | None:
    if valor is None:
        return None
    try:
        n = int(valor.strip())
    except ValueError:
        return None
    return n if 0 <= n <= 10**7 else None


def _guardar_evento(
    db: Session,
    llamada: Llamada,
    call_sid: str,
    estado: str,
    secuencia: int,
    datos: dict[str, Any],
    ahora: datetime,
) -> bool:
    """Inserta el evento; False si es duplicado."""
    duplicado = db.scalar(
        select(EventoLlamada.id).where(
            EventoLlamada.call_sid == call_sid,
            EventoLlamada.estado_proveedor == estado,
            EventoLlamada.secuencia == secuencia,
        )
    )
    if duplicado is not None:
        return False
    try:
        db.add(
            EventoLlamada(
                llamada_id=llamada.id,
                call_sid=call_sid,
                estado_proveedor=estado,
                secuencia=secuencia,
                datos=datos,
                recibido_en=ahora,
            )
        )
        db.flush()
    except IntegrityError:  # carrera con otra entrega del mismo evento
        db.rollback()
        return False
    return True


def _datos_evento(params: dict[str, str]) -> dict[str, Any]:
    datos: dict[str, Any] = {}
    for clave in ("CallDuration", "SipResponseCode", "DialCallStatus", "DialCallDuration"):
        if clave in params:
            datos[clave] = params[clave][:20]
    return datos


def _localizar(db: Session, llamada_id: str | None, call_sid: str) -> Llamada | None:
    """Carga la llamada con bloqueo de fila (`FOR UPDATE`) y datos frescos: serializa los
    webhooks de una misma llamada."""
    lid = _entero(llamada_id)
    consulta = select(Llamada)
    if lid is not None:
        consulta = consulta.where(Llamada.id == lid)
    else:
        consulta = consulta.where(
            (Llamada.call_sid == call_sid) | (Llamada.call_sid_cliente == call_sid)
        )
    return db.scalar(consulta.with_for_update().execution_options(populate_existing=True).limit(1))


def procesar_estado(
    db: Session, params: dict[str, str], llamada_id: str | None, ahora: datetime
) -> None:
    """Webhook de estado (pierna del cliente con `llamada_id`, o pierna del agente por CallSid)."""
    call_sid = (params.get("CallSid") or "")[:64]
    estado = (params.get("CallStatus") or "")[:20]
    if not call_sid or not estado:
        return
    llamada = _localizar(db, llamada_id, call_sid)
    if llamada is None:
        logger.info("Webhook de estado para llamada desconocida.")
        return
    secuencia = _entero_opcional(params.get("SequenceNumber")) or 0
    es_cliente = call_sid != llamada.call_sid
    if es_cliente and llamada.call_sid_cliente is None:
        ocupado = db.scalar(select(Llamada.id).where(Llamada.call_sid_cliente == call_sid))
        if ocupado is None:
            llamada.call_sid_cliente = call_sid
    if not _guardar_evento(db, llamada, call_sid, estado, secuencia, _datos_evento(params), ahora):
        db.rollback()
        return
    _renovar_reserva(db, llamada, ahora)
    # La duración válida es la de la pierna del cliente; la del agente incluye el marcado.
    duracion = _entero_opcional(params.get("CallDuration")) if es_cliente else None
    aplicar_estado(db, llamada, estado, duracion, ahora)
    db.commit()


def _transicion(
    db: Session,
    llamada: Llamada,
    nuevo: str,
    desde: tuple[str, ...],
    extra: dict[str, Any] | None = None,
) -> None:
    """UPDATE condicional: nunca sale de un estado terminal ni retrocede."""
    r = db.execute(
        update(Llamada)
        .where(Llamada.id == llamada.id, Llamada.estado.in_(desde))
        .values(estado=nuevo, **(extra or {}))
        .execution_options(synchronize_session=False)
    )
    db.refresh(llamada)
    if r.rowcount == 1:
        _publicar_llamada(db, llamada, _campana_de(db, llamada))


def aplicar_estado(
    db: Session, llamada: Llamada, estado: str, duracion: int | None, ahora: datetime
) -> None:
    if estado == "ringing":
        _transicion(db, llamada, "sonando", ("iniciando",))
    elif estado in ("in-progress", "answered"):
        _transicion(db, llamada, "en_curso", ("iniciando", "sonando"), {"contestada_en": ahora})
    elif estado in _TERMINALES_PROVEEDOR:
        finalizar(db, llamada, estado, duracion, ahora)


def procesar_dial_terminado(
    db: Session, params: dict[str, str], llamada_id: str | None, ahora: datetime
) -> None:
    call_sid = (params.get("CallSid") or "")[:64]
    llamada = _localizar(db, llamada_id, call_sid) if call_sid or llamada_id else None
    if llamada is None:
        logger.info("dial-terminado para llamada desconocida.")
        return
    estado = (params.get("DialCallStatus") or "")[:20]
    if not _guardar_evento(
        db, llamada, call_sid or llamada.call_sid, "dial-terminado", 0, _datos_evento(params), ahora
    ):
        db.rollback()
        return
    dial_sid = (params.get("DialCallSid") or "")[:64]
    if dial_sid and llamada.call_sid_cliente is None and dial_sid != llamada.call_sid:
        existe = db.scalar(select(Llamada.id).where(Llamada.call_sid_cliente == dial_sid))
        if existe is None:
            llamada.call_sid_cliente = dial_sid
    if estado in _TERMINALES_PROVEEDOR:
        duracion = _entero_opcional(params.get("DialCallDuration"))
        # S2: `completed` con tiempo de conversación cuenta como contestada.
        finalizar(
            db,
            llamada,
            estado,
            duracion,
            ahora,
            contestada=estado == "completed" and bool(duracion),
        )
    db.commit()


def procesar_grabacion(
    db: Session, params: dict[str, str], llamada_id: str | None, ahora: datetime
) -> None:
    lid = _entero(llamada_id)
    llamada = db.get(Llamada, lid) if lid else None
    sid = (params.get("RecordingSid") or "")[:64]
    if llamada is None or not sid:
        logger.info("Webhook de grabación ignorado (llamada o grabación desconocida).")
        return
    grabacion = db.scalar(select(Grabacion).where(Grabacion.recording_sid == sid))
    url = (params.get("RecordingUrl") or "")[:500]
    estado = (params.get("RecordingStatus") or "")[:20] or "desconocido"
    duracion = _entero_opcional(params.get("RecordingDuration"))
    canales = _entero_opcional(params.get("RecordingChannels"))
    if grabacion is None:
        db.add(
            Grabacion(
                llamada_id=llamada.id,
                recording_sid=sid,
                url=url,
                estado=estado,
                duracion_segundos=duracion,
                canales=canales,
                creado_en=ahora,
            )
        )
    else:
        grabacion.estado = estado
        if url:
            grabacion.url = url
        grabacion.duracion_segundos = duracion
        grabacion.canales = canales
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # carrera con otra entrega del mismo recording_sid


# ---- Simulación (mismos servicios que los webhooks) -------------------------------------------
def simular_evento(
    db: Session,
    llamada: Llamada,
    evento: str,
    resultado: str | None,
    duracion: int | None,
    ahora: datetime,
) -> None:
    secuencia = (
        db.scalar(
            select(EventoLlamada.id)
            .where(EventoLlamada.llamada_id == llamada.id)
            .order_by(EventoLlamada.id.desc())
        )
        or 0
    ) + 1
    sid_cliente = f"CAsimC{llamada.id:010d}"
    if evento == "contestada":
        params = {
            "CallSid": sid_cliente,
            "CallStatus": "in-progress",
            "SequenceNumber": str(secuencia),
        }
        procesar_estado(db, params, str(llamada.id), ahora)
    else:
        params = {
            "CallSid": llamada.call_sid,
            "DialCallSid": sid_cliente,
            "DialCallStatus": resultado or "completed",
        }
        if duracion is not None:
            params["DialCallDuration"] = str(duracion)
        procesar_dial_terminado(db, params, str(llamada.id), ahora)
