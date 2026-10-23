from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import ESTADOS_LLAMADA, en_lista
from app.db import Base, FechaHoraUTC, ahora_utc


class Llamada(Base):
    __tablename__ = "llamadas"
    __table_args__ = (
        CheckConstraint("canal IN ('voz','whatsapp_llamada')", name="canal"),
        CheckConstraint("direccion IN ('saliente','entrante')", name="direccion"),
        CheckConstraint(en_lista("estado", ESTADOS_LLAMADA), name="estado"),
        CheckConstraint("duracion_segundos IS NULL OR duracion_segundos >= 0", name="duracion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_cliente_id: Mapped[int] = mapped_column(ForeignKey("campana_clientes.id"), index=True)
    telefono_id: Mapped[int] = mapped_column(ForeignKey("telefonos.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    canal: Mapped[str] = mapped_column(String(20), default="voz", server_default="voz")
    direccion: Mapped[str] = mapped_column(
        String(10), default="saliente", server_default="saliente"
    )
    call_sid: Mapped[str] = mapped_column(String(64), unique=True)
    call_sid_cliente: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    estado: Mapped[str] = mapped_column(String(15))
    motivos_bloqueo: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    intento_contacto_id: Mapped[int | None] = mapped_column(
        ForeignKey("intentos_contacto.id"), nullable=True
    )
    iniciada_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    contestada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    finalizada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    duracion_segundos: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EventoLlamada(Base):
    __tablename__ = "eventos_llamada"
    __table_args__ = (UniqueConstraint("call_sid", "estado_proveedor", "secuencia"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    llamada_id: Mapped[int] = mapped_column(
        ForeignKey("llamadas.id", ondelete="CASCADE"), index=True
    )
    call_sid: Mapped[str] = mapped_column(String(64))
    estado_proveedor: Mapped[str] = mapped_column(String(20))
    secuencia: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    datos: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    recibido_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class Grabacion(Base):
    __tablename__ = "grabaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    llamada_id: Mapped[int] = mapped_column(ForeignKey("llamadas.id"), index=True)
    recording_sid: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    estado: Mapped[str] = mapped_column(String(20))
    duracion_segundos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canales: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
