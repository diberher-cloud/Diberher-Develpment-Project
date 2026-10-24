from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC


class TicketWS(Base):
    """Ticket de un solo uso para abrir el WebSocket (B3). Se guarda solo el hash SHA-256."""

    __tablename__ = "tickets_ws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_hash: Mapped[str] = mapped_column(String(64), unique=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    expira_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    sesion_expira_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    usado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
