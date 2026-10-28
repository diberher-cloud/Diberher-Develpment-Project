from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import (
    CANALES,
    ESTADOS_AGENTE,
    MOTIVOS_PAUSA,
    ORIGENES_GESTION,
    RESULTADOS,
    en_lista,
)
from app.db import Base, FechaHoraUTC, ahora_utc


class EstadoAgente(Base):
    """Estado actual del agente (una fila por agente; sin fila = desconectado)."""

    __tablename__ = "estados_agente"
    __table_args__ = (
        CheckConstraint(en_lista("estado", ESTADOS_AGENTE), name="estado"),
        CheckConstraint(
            "motivo_pausa IS NULL OR " + en_lista("motivo_pausa", MOTIVOS_PAUSA),
            name="motivo_pausa",
        ),
    )

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    estado: Mapped[str] = mapped_column(String(15))
    desde: Mapped[datetime] = mapped_column(FechaHoraUTC)
    motivo_pausa: Mapped[str | None] = mapped_column(String(20), nullable=True)
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class HistorialEstadoAgente(Base):
    __tablename__ = "historial_estados_agente"
    __table_args__ = (
        CheckConstraint(en_lista("estado", ESTADOS_AGENTE), name="estado"),
        Index("ix_historial_estados_agente_usuario_id_inicio", "usuario_id", "inicio"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    estado: Mapped[str] = mapped_column(String(15))
    motivo_pausa: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inicio: Mapped[datetime] = mapped_column(FechaHoraUTC)
    fin: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)


class Tipificacion(Base):
    __tablename__ = "tipificaciones"
    __table_args__ = (
        CheckConstraint(en_lista("canal", CANALES), name="canal"),
        CheckConstraint(en_lista("origen", ORIGENES_GESTION), name="origen"),
        CheckConstraint(en_lista("resultado", RESULTADOS), name="resultado"),
        CheckConstraint(
            "origen <> 'agente' OR usuario_id IS NOT NULL", name="agente_requiere_usuario"
        ),
        CheckConstraint(
            "llamada_id IS NULL OR conversacion_id IS NULL", name="llamada_o_conversacion"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_cliente_id: Mapped[int] = mapped_column(ForeignKey("campana_clientes.id"), index=True)
    canal: Mapped[str] = mapped_column(String(20))
    origen: Mapped[str] = mapped_column(String(10))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    llamada_id: Mapped[int | None] = mapped_column(
        ForeignKey("llamadas.id"), unique=True, nullable=True
    )
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), unique=True, nullable=True
    )
    resultado: Mapped[str] = mapped_column(String(20))
    contacto_directo: Mapped[bool] = mapped_column(Boolean)
    observacion: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    volver_a_llamar_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class PromesaPago(Base):
    __tablename__ = "promesas_pago"
    __table_args__ = (
        CheckConstraint("monto > 0", name="monto"),
        CheckConstraint("numero_cuotas BETWEEN 1 AND 36", name="cuotas"),
        CheckConstraint("descuento_porcentaje BETWEEN 0 AND 100", name="descuento"),
        CheckConstraint(
            en_lista("estado", ("vigente", "cumplida", "incumplida", "anulada")), name="estado"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipificacion_id: Mapped[int] = mapped_column(ForeignKey("tipificaciones.id"), unique=True)
    campana_cliente_id: Mapped[int] = mapped_column(ForeignKey("campana_clientes.id"), index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    fecha_pago: Mapped[date] = mapped_column(Date)
    numero_cuotas: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    descuento_porcentaje: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0"), server_default="0"
    )
    estado: Mapped[str] = mapped_column(String(12), default="vigente", server_default="vigente")
    origen: Mapped[str] = mapped_column(String(10))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class Venta(Base):
    __tablename__ = "ventas"
    __table_args__ = (
        CheckConstraint("valor > 0", name="valor"),
        CheckConstraint("unidades >= 1", name="unidades"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipificacion_id: Mapped[int] = mapped_column(ForeignKey("tipificaciones.id"), unique=True)
    campana_cliente_id: Mapped[int] = mapped_column(ForeignKey("campana_clientes.id"), index=True)
    producto: Mapped[str] = mapped_column(String(120))
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    unidades: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    origen: Mapped[str] = mapped_column(String(10))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
