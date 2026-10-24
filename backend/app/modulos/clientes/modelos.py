from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.catalogos import RESULTADOS, en_lista
from app.db import Base, FechaHoraUTC, ahora_utc

TIPOS_DOCUMENTO = ("CC", "CE", "NIT", "PA", "TI", "PPT")


class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        CheckConstraint(
            "tipo_documento IN ('CC','CE','NIT','PA','TI','PPT')", name="tipo_documento"
        ),
        UniqueConstraint("tipo_documento", "numero_documento"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo_documento: Mapped[str] = mapped_column(String(5))
    numero_documento: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(
        FechaHoraUTC, default=ahora_utc, onupdate=ahora_utc
    )

    telefonos: Mapped[list["Telefono"]] = relationship(
        back_populates="cliente", order_by="Telefono.prioridad"
    )


class Telefono(Base):
    __tablename__ = "telefonos"
    __table_args__ = (
        CheckConstraint("tipo_linea IN ('movil','fijo')", name="tipo_linea"),
        UniqueConstraint("cliente_id", "numero_e164"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"))
    numero_e164: Mapped[str] = mapped_column(String(16), index=True)
    tipo_linea: Mapped[str] = mapped_column(String(10))
    prioridad: Mapped[int] = mapped_column(Integer)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)

    cliente: Mapped[Cliente] = relationship(back_populates="telefonos")


class CampanaCliente(Base):
    __tablename__ = "campana_clientes"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente','en_gestion','gestionado','descartado')", name="estado"
        ),
        CheckConstraint("dias_mora IS NULL OR dias_mora >= 0", name="dias_mora"),
        CheckConstraint(
            "ultimo_resultado IS NULL OR " + en_lista("ultimo_resultado", RESULTADOS),
            name="ultimo_resultado",
        ),
        UniqueConstraint("campana_id", "cliente_id"),
        Index("ix_campana_clientes_campana_id_estado", "campana_id", "estado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_id: Mapped[int] = mapped_column(
        ForeignKey("campanas.id", ondelete="CASCADE"), index=True
    )
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    importacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("importaciones.id"), nullable=True
    )
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", server_default="pendiente")
    numero_obligacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    saldo_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    saldo_mora: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    dias_mora: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    producto: Mapped[str | None] = mapped_column(String(120), nullable=True)
    oferta: Mapped[str | None] = mapped_column(Text, nullable=True)
    datos_adicionales: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    proximo_intento_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    # Fase 2A: reserva por agente y último resultado de gestión
    reservado_por: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True, index=True
    )
    reservado_hasta: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    ultimo_resultado: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ultima_gestion_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)

    cliente: Mapped[Cliente] = relationship()
