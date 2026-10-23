from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

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
        UniqueConstraint("numero_e164", "aplica_a"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_e164: Mapped[str] = mapped_column(String(16), index=True)
    motivo: Mapped[str] = mapped_column(String(30))
    aplica_a: Mapped[str] = mapped_column(String(10))
    observacion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    creado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
