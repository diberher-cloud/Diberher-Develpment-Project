"""Trabajo periódico `trabajos.purgar`: borra trabajos terminados antiguos."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.trabajos.modelos import Trabajo

RETENCION_COMPLETADOS = timedelta(days=7)
RETENCION_FALLIDOS = timedelta(days=30)


def purgar(db: Session, _payload: dict[str, Any], ahora: datetime) -> None:
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
