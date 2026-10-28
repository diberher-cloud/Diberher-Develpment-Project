from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import (
    CATEGORIAS_PLANTILLA,
    ESTADOS_APROBACION,
    FINALIDADES,
    MOTIVOS_REVOCACION,
    ORIGENES_AUTORIZACION,
    en_lista,
)
from app.db import Base, FechaHoraUTC


class PlantillaWhatsApp(Base):
    __tablename__ = "plantillas_whatsapp"
    __table_args__ = (
        CheckConstraint(en_lista("categoria", CATEGORIAS_PLANTILLA), name="categoria"),
        CheckConstraint(
            en_lista("estado_aprobacion", ESTADOS_APROBACION), name="estado_aprobacion"
        ),
        CheckConstraint(
            "finalidad IS NULL OR " + en_lista("finalidad", FINALIDADES), name="finalidad"
        ),
        CheckConstraint(
            "activa = false OR (estado_aprobacion = 'aprobada' AND finalidad IS NOT NULL)",
            name="activa_requiere_aprobada",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_sid: Mapped[str] = mapped_column(String(64), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    idioma: Mapped[str] = mapped_column(String(10))
    categoria: Mapped[str] = mapped_column(String(15))
    estado_aprobacion: Mapped[str] = mapped_column(String(15))
    motivo_rechazo: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cuerpo: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    botones: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    tiene_boton_baja: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    mapeo_variables: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    finalidad: Mapped[str | None] = mapped_column(String(10), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sincronizada_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class AutorizacionCanal(Base):
    """Opt-in por número, canal y finalidad (ADR-0012)."""

    __tablename__ = "autorizaciones_canal"
    __table_args__ = (
        CheckConstraint("canal IN ('whatsapp')", name="canal"),
        CheckConstraint(en_lista("finalidad", FINALIDADES), name="finalidad"),
        CheckConstraint(en_lista("origen", ORIGENES_AUTORIZACION), name="origen"),
        CheckConstraint(
            "motivo_revocacion IS NULL OR " + en_lista("motivo_revocacion", MOTIVOS_REVOCACION),
            name="motivo_revocacion",
        ),
        CheckConstraint(
            "(revocada_en IS NULL AND clave_vigente IS NOT NULL) OR "
            "(revocada_en IS NOT NULL AND clave_vigente IS NULL)",
            name="vigencia",
        ),
        CheckConstraint(
            "origen NOT IN ('agente','cliente') OR registrada_por IS NOT NULL",
            name="origen_requiere_usuario",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_e164: Mapped[str] = mapped_column(String(16), index=True)
    canal: Mapped[str] = mapped_column(String(10), default="whatsapp")
    finalidad: Mapped[str] = mapped_column(String(10))
    origen: Mapped[str] = mapped_column(String(12))
    evidencia: Mapped[str] = mapped_column(String(500))
    otorgada_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    registrada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    importacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("importaciones.id"), nullable=True
    )
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    clave_vigente: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    revocada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    revocada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    motivo_revocacion: Mapped[str | None] = mapped_column(String(12), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
