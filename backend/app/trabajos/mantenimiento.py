"""Trabajo periódico `trabajos.purgar`: borra trabajos terminados antiguos."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.conversaciones.modelos import EventoMensaje
from app.trabajos.modelos import LatidoWorker, Trabajo

RETENCION_COMPLETADOS = timedelta(days=7)
RETENCION_FALLIDOS = timedelta(days=30)


RETENCION_LATIDOS = timedelta(days=7)


def purgar(db: Session, _payload: dict[str, Any], ahora: datetime) -> None:
    """Borra trabajos terminados antiguos, latidos de workers muertos (> 7 días) y eventos de
    estado que nunca se enlazaron a un mensaje (> `PURGA_EVENTOS_HUERFANOS_DIAS`)."""
    db.execute(delete(LatidoWorker).where(LatidoWorker.ultimo_latido < ahora - RETENCION_LATIDOS))
    dias = get_settings().purga_eventos_huerfanos_dias
    db.execute(
        delete(EventoMensaje).where(
            EventoMensaje.mensaje_id.is_(None),
            EventoMensaje.recibido_en < ahora - timedelta(days=dias),
        )
    )
    db.execute(
        delete(Trabajo).where(
            or_(
                Trabajo.estado.in_(("completado", "cancelado"))
                & (Trabajo.actualizado_en < ahora - RETENCION_COMPLETADOS),
                (Trabajo.estado == "fallido")
                & (Trabajo.actualizado_en < ahora - RETENCION_FALLIDOS),
            )
        )
    )
