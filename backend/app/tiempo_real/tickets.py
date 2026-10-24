"""Tickets de un solo uso para el WebSocket (B3).

El JWT de sesión NO viaja en la URL del WebSocket (acabaría en logs de uvicorn y de proxies). El
cliente pide `POST /ws/ticket` (autenticado con Bearer) y abre `/ws?ticket=<ticket>`. El ticket es
aleatorio, dura 30 s y se consume una sola vez; se guarda su hash SHA-256 en BD, de modo que
funciona con varias instancias de la API.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.tiempo_real.modelos import TicketWS

TTL_SEGUNDOS = 30


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def emitir(
    db: Session, usuario_id: int, ahora: datetime, sesion_expira_en: datetime | None = None
) -> str:
    ticket = secrets.token_urlsafe(32)
    # Limpieza oportunista de tickets vencidos hace más de un minuto.
    db.execute(delete(TicketWS).where(TicketWS.expira_en < ahora - timedelta(minutes=1)))
    db.add(
        TicketWS(
            ticket_hash=_hash(ticket),
            usuario_id=usuario_id,
            expira_en=ahora + timedelta(seconds=TTL_SEGUNDOS),
            sesion_expira_en=sesion_expira_en,
            creado_en=ahora,
        )
    )
    db.commit()
    return ticket


def consumir(
    db: Session, ticket: str | None, ahora: datetime
) -> tuple[int, datetime | None] | None:
    """Consume el ticket de forma atómica. Devuelve (usuario_id, fin de sesión) o None si no es
    válido, caducó o ya se usó."""
    if not ticket or len(ticket) > 200:
        return None
    h = _hash(ticket)
    r = db.execute(
        update(TicketWS)
        .where(TicketWS.ticket_hash == h, TicketWS.usado_en.is_(None), TicketWS.expira_en > ahora)
        .values(usado_en=ahora)
        .execution_options(synchronize_session=False)
    )
    if r.rowcount != 1:
        db.rollback()
        return None
    fila = db.execute(
        select(TicketWS.usuario_id, TicketWS.sesion_expira_en).where(TicketWS.ticket_hash == h)
    ).one()
    db.commit()
    return fila[0], fila[1]
