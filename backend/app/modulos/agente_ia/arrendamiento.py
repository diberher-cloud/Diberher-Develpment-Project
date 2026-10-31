"""Arrendamiento de turno: un turno por interacción a la vez (ADR-0022 §1, fase-2c.md §4.5).

Siempre se usa con la interacción ya bloqueada (`FOR UPDATE` de la conversación): no hay
transacción abierta durante la llamada al modelo, así que no se puede usar un bloqueo de fila.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.agente_ia.contexto import RefInteraccion
from app.modulos.agente_ia.modelos import BloqueoTurnoIA


def _expira(ahora: datetime) -> datetime:
    return ahora + timedelta(seconds=get_settings().ia_turno_max_segundos + 60)


def adquirir(db: Session, ref: RefInteraccion, trabajador: str, ahora: datetime) -> bool:
    """INSERT en SAVEPOINT; si existe, UPDATE condicional (caducado o mío). 0 filas = ocupado."""
    try:
        with db.begin_nested():
            db.add(
                BloqueoTurnoIA(
                    clave=ref.clave,
                    conversacion_id=ref.id if ref.tipo == "conversacion" else None,
                    llamada_id=ref.id if ref.tipo == "llamada" else None,
                    trabajador=trabajador,
                    adquirido_en=ahora,
                    expira_en=_expira(ahora),
                )
            )
            db.flush()
        return True
    except IntegrityError:
        pass
    r = db.execute(
        update(BloqueoTurnoIA)
        .where(
            BloqueoTurnoIA.clave == ref.clave,
            (BloqueoTurnoIA.expira_en < ahora) | (BloqueoTurnoIA.trabajador == trabajador),
        )
        .values(trabajador=trabajador, adquirido_en=ahora, expira_en=_expira(ahora))
        .execution_options(synchronize_session=False)
    )
    return r.rowcount == 1


def renovar(db: Session, ref: RefInteraccion, trabajador: str, ahora: datetime) -> bool:
    """Antes de cada iteración y de cada herramienta. 0 filas = arrendamiento perdido."""
    r = db.execute(
        update(BloqueoTurnoIA)
        .where(BloqueoTurnoIA.clave == ref.clave, BloqueoTurnoIA.trabajador == trabajador)
        .values(expira_en=_expira(ahora))
        .execution_options(synchronize_session=False)
    )
    return r.rowcount == 1


def liberar(db: Session, ref: RefInteraccion, trabajador: str) -> None:
    db.execute(
        delete(BloqueoTurnoIA)
        .where(BloqueoTurnoIA.clave == ref.clave, BloqueoTurnoIA.trabajador == trabajador)
        .execution_options(synchronize_session=False)
    )


def vigente(db: Session, ref: RefInteraccion, ahora: datetime) -> bool:
    """¿Hay un turno en curso (arrendamiento no caducado)?"""
    return (
        db.scalar(
            select(BloqueoTurnoIA.clave).where(
                BloqueoTurnoIA.clave == ref.clave, BloqueoTurnoIA.expira_en >= ahora
            )
        )
        is not None
    )
