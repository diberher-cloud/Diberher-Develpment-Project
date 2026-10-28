"""Trabajo periódico `conversaciones.cerrar_inactivas`: cierra (motivo `inactividad`) las
conversaciones abiertas cuya ventana expiró y sin mensajes en `CONVERSACION_INACTIVIDAD_HORAS`.
No crea tipificación (el registro queda como esté)."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.conversaciones import servicio
from app.modulos.conversaciones.modelos import Conversacion

LOTE = 200
MAX_LOTES = 50


def cerrar_inactivas(db: Session, _payload: dict[str, Any], ahora: datetime) -> None:
    limite = ahora - timedelta(hours=get_settings().conversacion_inactividad_horas)
    for _ in range(MAX_LOTES):
        # ahora >= max(COALESCE(ventana_expira_en, abierta_en), ultimo_mensaje_en + horas)
        ids = list(
            db.scalars(
                select(Conversacion.id)
                .where(
                    Conversacion.estado == "abierta",
                    func.coalesce(Conversacion.ventana_expira_en, Conversacion.abierta_en) <= ahora,
                    Conversacion.ultimo_mensaje_en <= limite,
                )
                .order_by(Conversacion.id)
                .limit(LOTE)
            )
        )
        if not ids:
            return
        for conv in db.scalars(
            select(Conversacion)
            .where(Conversacion.id.in_(ids))
            .order_by(Conversacion.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ):
            if conv.estado == "abierta":
                servicio.cerrar(db, conv, "inactividad", None, ahora)
        db.commit()
