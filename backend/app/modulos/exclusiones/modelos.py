from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import CANALES_EXCLUSION, ORIGENES_EXCLUSION, en_lista
from app.db import Base, FechaHoraUTC, ahora_utc

MOTIVOS = ("rne", "solicitud_titular", "numero_errado", "manual")
APLICA_A = ("venta", "cobranza", "todas")


class Exclusion(Base):
    __tablename__ = "exclusiones"
    __table_args__ = (
        CheckConstraint(
            "motivo IN ('rne','solicitud_titular','numero_errado','manual')", name="motivo"
        ),
        CheckConstraint("aplica_a IN ('venta','cobranza','todas')", name="aplica_a"),
        CheckConstraint(en_lista("canal", CANALES_EXCLUSION), name="canal"),
        CheckConstraint(en_lista("origen", ORIGENES_EXCLUSION), name="origen"),
        CheckConstraint(
            "origen <> 'usuario' OR creado_por IS NOT NULL", name="usuario_requiere_creador"
        ),
        UniqueConstraint("numero_e164", "aplica_a", "canal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_e164: Mapped[str] = mapped_column(String(16), index=True)
    motivo: Mapped[str] = mapped_column(String(30))
    aplica_a: Mapped[str] = mapped_column(String(10))
    canal: Mapped[str] = mapped_column(String(10), default="todos", server_default="todos")
    origen: Mapped[str] = mapped_column(String(10), default="usuario", server_default="usuario")
    observacion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
