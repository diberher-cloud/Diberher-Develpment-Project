"""Cola de trabajos en BD y latido del worker (ADR-0013 §4)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import ESTADOS_TRABAJO, en_lista
from app.db import Base, FechaHoraUTC


class Trabajo(Base):
    """Trabajo diferido. `payload` guarda SOLO ids y catálogos (nunca texto ni números)."""

    __tablename__ = "trabajos"
    __table_args__ = (
        CheckConstraint(en_lista("estado", ESTADOS_TRABAJO), name="estado"),
        CheckConstraint("max_intentos BETWEEN 1 AND 20", name="max_intentos"),
        Index("ix_trabajos_estado_disponible_desde", "estado", "disponible_desde"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(60))
    clave_unica: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    estado: Mapped[str] = mapped_column(String(12))
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_intentos: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    disponible_desde: Mapped[datetime] = mapped_column(FechaHoraUTC)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    bloqueado_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ultimo_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    completado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)


class LatidoWorker(Base):
    __tablename__ = "latidos_worker"

    trabajador: Mapped[str] = mapped_column(String(80), primary_key=True)
    iniciado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    ultimo_latido: Mapped[datetime] = mapped_column(FechaHoraUTC)
    version: Mapped[str] = mapped_column(String(20))
