from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora_utc

TIPOS = ("venta", "cobranza")
ESTADOS = ("borrador", "activa", "pausada", "finalizada")


class Campana(Base):
    __tablename__ = "campanas"
    __table_args__ = (
        CheckConstraint("tipo IN ('venta','cobranza')", name="tipo"),
        CheckConstraint("estado IN ('borrador','activa','pausada','finalizada')", name="estado"),
        CheckConstraint(
            "fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio",
            name="fechas",
        ),
        CheckConstraint("max_intentos BETWEEN 1 AND 10", name="max_intentos"),
        CheckConstraint("intervalo_reintento_minutos BETWEEN 5 AND 10080", name="intervalo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    tipo: Mapped[str] = mapped_column(String(20))
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), default="borrador", server_default="borrador")
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    guion: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_intentos: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    intervalo_reintento_minutos: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60"
    )
    whatsapp_habilitado: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    plantilla_inicial_id: Mapped[int | None] = mapped_column(
        ForeignKey("plantillas_whatsapp.id"), nullable=True
    )
    creado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(
        FechaHoraUTC, default=ahora_utc, onupdate=ahora_utc
    )


class CampanaAgente(Base):
    """Asignación de un agente a una campaña (ADR-0017)."""

    __tablename__ = "campana_agentes"
    __table_args__ = (UniqueConstraint("campana_id", "usuario_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.id", ondelete="CASCADE"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
