"""Webhook de estado de entrega (idempotente y monótono), fase-2b.md §4.4."""

import logging
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integraciones.whatsapp.proveedor import EstadoMensaje, ProveedorWhatsApp
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.modelos import EventoMensaje, Mensaje

logger = logging.getLogger("app")
# Orden monótono de los estados de entrega; `fallido` solo se aplica si el actual es < entregado.
RANGO = {"enviando": 0, "enviado": 1, "entregado": 2, "leido": 3}


def rango(estado: str) -> int:
    return RANGO.get(estado, 1 if estado == "fallido" else 0)


def bloquear_sid(db: Session, proveedor_id: str) -> None:
    """Serializa el webhook de estado con la Tx 2 del envío para un mismo SID (PostgreSQL):
    evita que un estado recibido justo mientras se guarda el SID quede sin aplicar."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:sid, 0))"), {"sid": proveedor_id}
        )


def aplicar(
    mensaje: Mensaje, nuevo: str, estado_proveedor: str, error_codigo: str | None, momento: datetime
) -> bool:
    """Aplica un estado de entrega con orden monótono. Devuelve True si cambió el mensaje."""
    if nuevo == "fallido":
        if mensaje.estado == "fallido" or rango(mensaje.estado) >= RANGO["entregado"]:
            return False
        mensaje.estado = "fallido"
        mensaje.error_codigo = (error_codigo or estado_proveedor)[:30]
        return True
    if RANGO[nuevo] <= rango(mensaje.estado):
        return False
    mensaje.estado = nuevo
    mensaje.error_codigo = None
    if mensaje.enviado_en is None:
        mensaje.enviado_en = momento
    if nuevo in ("entregado", "leido") and mensaje.entregado_en is None:
        mensaje.entregado_en = momento
    if nuevo == "leido":
        mensaje.leido_en = momento
    return True


def aplicar_eventos_pendientes(db: Session, mensaje: Mensaje, momento: datetime) -> bool:
    """Tras guardar el SID: aplica en orden los estados llegados antes. Devuelve si cambió."""
    from app.integraciones.whatsapp.parseo import parsear_estado

    cambio = False
    pendientes = db.scalars(
        select(EventoMensaje)
        .where(
            EventoMensaje.proveedor_id == mensaje.proveedor_id,
            EventoMensaje.mensaje_id.is_(None),
        )
        .order_by(EventoMensaje.id)
    )
    for ev in pendientes:
        ev.mensaje_id = mensaje.id
        est = parsear_estado({"MessageSid": ev.proveedor_id, "MessageStatus": ev.estado_proveedor})
        if est is not None and est.estado is not None:
            cambio = (
                aplicar(mensaje, est.estado, ev.estado_proveedor, ev.error_codigo, momento)
                or cambio
            )
    return cambio


def procesar_estado(db: Session, est: EstadoMensaje, ahora: datetime) -> None:
    """Guarda el evento y, si el mensaje ya tiene ese SID, aplica el estado. Confirma."""
    if est.estado is None:  # p. ej. "receiving": se ignora
        return
    bloquear_sid(db, est.proveedor_id)
    evento = EventoMensaje(
        proveedor_id=est.proveedor_id,
        estado_proveedor=est.estado_proveedor,
        error_codigo=est.error_codigo,
        recibido_en=ahora,
    )
    try:
        with db.begin_nested():
            db.add(evento)
            db.flush()
    except IntegrityError:  # duplicado: sin efectos
        db.rollback()
        return
    previo = db.scalar(select(Mensaje).where(Mensaje.proveedor_id == est.proveedor_id))
    if previo is None or previo.conversacion_id is None:
        db.commit()  # el estado llegó antes de guardar el SID: queda pendiente (mensaje_id nulo)
        return
    conv = conversaciones.bloquear(db, previo.conversacion_id)
    mensaje = db.scalar(
        select(Mensaje)
        .where(Mensaje.id == previo.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert mensaje is not None
    evento.mensaje_id = mensaje.id
    if aplicar(mensaje, est.estado, est.estado_proveedor, est.error_codigo, ahora):
        conversaciones.publicar_mensaje(db, conv, mensaje, "estado")
    db.commit()


def procesar_webhook(
    db: Session, proveedor: ProveedorWhatsApp, params: dict[str, str], ahora: datetime
) -> None:
    est = proveedor.parsear_estado(params)
    if est is None:
        return
    procesar_estado(db, est, ahora)
