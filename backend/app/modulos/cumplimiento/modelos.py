from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora_utc


class PoliticaCumplimiento(Base):
    __tablename__ = "politicas_cumplimiento"
    __table_args__ = (
        CheckConstraint("tipo_campana IN ('venta','cobranza')", name="tipo_campana"),
        UniqueConstraint("tipo_campana", "version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_campana: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    configuracion: Mapped[dict[str, Any]] = mapped_column(JSON)
    activa: Mapped[bool] = mapped_column(Boolean)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class Festivo(Base):
    __tablename__ = "festivos"
    __table_args__ = (CheckConstraint("origen IN ('calculado','manual')", name="origen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    origen: Mapped[str] = mapped_column(String(12))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
