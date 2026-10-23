from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora_utc

ROLES = ("administrador", "supervisor", "agente")


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("rol IN ('administrador','supervisor','agente')", name="rol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    rol: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(
        FechaHoraUTC, default=ahora_utc, onupdate=ahora_utc
    )
