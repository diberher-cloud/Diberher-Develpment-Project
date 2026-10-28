"""Programación de trabajos periódicos: en cada vuelta del worker, si no hay uno pendiente o en
proceso del tipo, se encola con `disponible_desde` = siguiente ejecución."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.trabajos.cola import encolar
from app.trabajos.modelos import Trabajo

PERIODICOS: dict[str, timedelta] = {
    "conversaciones.cerrar_inactivas": timedelta(seconds=300),
    "trabajos.purgar": timedelta(hours=24),
}


def programar(db: Session, ahora: datetime) -> int:
    """Encola los periódicos que falten. No hace commit. Devuelve cuántos encoló."""
    creados = 0
    for tipo, cada in PERIODICOS.items():
        activo = db.scalar(
            select(Trabajo.id)
            .where(Trabajo.tipo == tipo, Trabajo.estado.in_(("pendiente", "en_proceso")))
            .limit(1)
        )
        if activo is None:
            encolar(
                db,
                tipo,
                {},
                clave_unica=f"periodico:{tipo}",
                disponible_desde=ahora + cada,
                ahora=ahora,
            )
            creados += 1
    return creados
