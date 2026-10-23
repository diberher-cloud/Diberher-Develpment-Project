from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora_utc


class Auditoria(Base):
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    accion: Mapped[str] = mapped_column(String(60))
    entidad: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entidad_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
