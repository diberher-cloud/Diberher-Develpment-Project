from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, FechaHoraUTC, ahora_utc


class Importacion(Base):
    __tablename__ = "importaciones"
    __table_args__ = (CheckConstraint("estado IN ('completada','fallida')", name="estado"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.id", ondelete="CASCADE"))
    nombre_archivo: Mapped[str] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(20))
    total_filas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_importadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_duplicadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_invalidas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filas_excluidas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    creado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class ImportacionError(Base):
    __tablename__ = "importacion_errores"
    __table_args__ = (CheckConstraint("severidad IN ('error','advertencia')", name="severidad"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacion_id: Mapped[int] = mapped_column(
        ForeignKey("importaciones.id", ondelete="CASCADE"), index=True
    )
    fila: Mapped[int] = mapped_column(Integer)
    campo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    codigo: Mapped[str] = mapped_column(String(40))
    mensaje: Mapped[str] = mapped_column(String(300))
    severidad: Mapped[str] = mapped_column(String(12))
