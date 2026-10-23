from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import CANALES, RESULTADOS, en_lista
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


class IntentoContacto(Base):
    """Cada contacto (o intento) con un cliente por cualquier canal; base de la frecuencia."""

    __tablename__ = "intentos_contacto"
    __table_args__ = (
        CheckConstraint("tipo_campana IN ('venta','cobranza')", name="tipo_campana"),
        CheckConstraint(en_lista("canal", CANALES), name="canal"),
        CheckConstraint("iniciado_por IN ('empresa','cliente')", name="iniciado_por"),
        CheckConstraint(
            "resultado IS NULL OR " + en_lista("resultado", RESULTADOS), name="resultado"
        ),
        Index("ix_intentos_contacto_cliente_id_momento", "cliente_id", "momento"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    campana_id: Mapped[int | None] = mapped_column(ForeignKey("campanas.id"), nullable=True)
    campana_cliente_id: Mapped[int | None] = mapped_column(
        ForeignKey("campana_clientes.id"), nullable=True
    )
    tipo_campana: Mapped[str] = mapped_column(String(20))
    canal: Mapped[str] = mapped_column(String(20))
    iniciado_por: Mapped[str] = mapped_column(String(10))
    telefono_id: Mapped[int | None] = mapped_column(ForeignKey("telefonos.id"), nullable=True)
    momento: Mapped[datetime] = mapped_column(FechaHoraUTC)
    contacto_directo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    resultado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    politica_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
