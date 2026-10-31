"""Tablas del agente IA (fase-2c.md §3.1). Las canal-agnósticas llevan `conversacion_id` o
`llamada_id` (CHECK: exactamente uno); en 2C `llamada_id` siempre es nulo."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import (
    CANALES,
    EFECTOS_ACCION_IA,
    ESFUERZOS_IA,
    ESTADOS_EVALUACION,
    MODOS_EVALUACION,
    MOTIVOS_DESACTIVACION_IA,
    ROLES_HISTORIAL_IA,
    TIPOS_HISTORIAL_IA,
    TRATAMIENTOS,
    en_lista,
)
from app.db import Base, FechaHoraUTC

EXACTAMENTE_UNO = "(conversacion_id IS NULL) <> (llamada_id IS NULL)"


class ConfiguracionIACampana(Base):
    __tablename__ = "configuracion_ia_campana"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(en_lista("esfuerzo", ESFUERZOS_IA), name="esfuerzo"),
        CheckConstraint("prompt_version >= 1", name="prompt_version"),
        CheckConstraint(en_lista("tratamiento", TRATAMIENTOS), name="tratamiento"),
        CheckConstraint("presupuesto_usd_mensual >= 0", name="presupuesto"),
        CheckConstraint("max_costo_conversacion_usd > 0", name="max_costo"),
        CheckConstraint("max_turnos_conversacion BETWEEN 1 AND 200", name="max_turnos"),
        CheckConstraint(
            "desactivada_motivo IS NULL OR "
            + en_lista("desactivada_motivo", MOTIVOS_DESACTIVACION_IA),
            name="desactivada_motivo",
        ),
    )

    campana_id: Mapped[int] = mapped_column(
        ForeignKey("campanas.id", ondelete="CASCADE"), primary_key=True
    )
    activa: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    modelo: Mapped[str] = mapped_column(String(40))
    esfuerzo: Mapped[str] = mapped_column(String(10))
    prompt_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    tratamiento: Mapped[str] = mapped_column(String(5), default="usted", server_default="usted")
    instrucciones: Mapped[str | None] = mapped_column(Text, nullable=True)
    verificacion: Mapped[dict[str, Any]] = mapped_column(JSON)
    reglas: Mapped[dict[str, Any]] = mapped_column(JSON)
    presupuesto_usd_mensual: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    max_costo_conversacion_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    max_turnos_conversacion: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    desactivada_motivo: Mapped[str | None] = mapped_column(String(12), nullable=True)
    activada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    desactivada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    alerta_presupuesto_mes: Mapped[str | None] = mapped_column(String(7), nullable=True)
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class OfertaCampana(Base):
    __tablename__ = "ofertas_campana"
    __table_args__ = (
        CheckConstraint("precio > 0", name="precio"),
        CheckConstraint("descuento_max_pct BETWEEN 0 AND 100", name="descuento"),
        CheckConstraint("max_unidades BETWEEN 1 AND 100", name="max_unidades"),
        UniqueConstraint("campana_id", "codigo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campana_id: Mapped[int] = mapped_column(
        ForeignKey("campanas.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(30))
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    precio: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    descuento_max_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0"), server_default="0"
    )
    max_unidades: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    condiciones: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class PromesaCuota(Base):
    __tablename__ = "promesa_cuotas"
    __table_args__ = (
        CheckConstraint("numero >= 1", name="numero"),
        CheckConstraint("monto > 0", name="monto"),
        UniqueConstraint("promesa_id", "numero"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promesa_id: Mapped[int] = mapped_column(ForeignKey("promesas_pago.id", ondelete="CASCADE"))
    numero: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[date] = mapped_column(Date)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class UsoIA(Base):
    __tablename__ = "uso_ia"
    __table_args__ = (
        CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),
        CheckConstraint(en_lista("canal", CANALES), name="canal"),
        CheckConstraint("iteracion >= 1", name="iteracion"),
        CheckConstraint("input_tokens >= 0", name="input_tokens"),
        CheckConstraint("output_tokens >= 0", name="output_tokens"),
        CheckConstraint("costo_usd >= 0", name="costo"),
        Index("ix_uso_ia_campana_id_creado_en", "campana_id", "creado_en"),
        Index("ix_uso_ia_conversacion_id_id", "conversacion_id", "id"),
        Index("ix_uso_ia_llamada_id_id", "llamada_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.id"))
    canal: Mapped[str] = mapped_column(String(20))
    modelo: Mapped[str] = mapped_column(String(40))
    modelo_servido: Mapped[str] = mapped_column(String(40))
    esfuerzo: Mapped[str] = mapped_column(String(10))
    respuesta_id: Mapped[str] = mapped_column(String(80))
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    iteracion: Mapped[int] = mapped_column(Integer)
    stop_reason: Mapped[str] = mapped_column(String(20))
    stop_categoria: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    costo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    duracion_ms: Mapped[int] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class HistorialIA(Base):
    """Lo que vio el modelo; append-only (nunca se actualiza ni se borra una fila)."""

    __tablename__ = "historial_ia"
    __table_args__ = (
        CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),
        CheckConstraint("secuencia >= 1", name="secuencia"),
        CheckConstraint(en_lista("rol", ROLES_HISTORIAL_IA), name="rol"),
        CheckConstraint(en_lista("tipo", TIPOS_HISTORIAL_IA), name="tipo"),
        UniqueConstraint("conversacion_id", "secuencia"),
        UniqueConstraint("llamada_id", "secuencia"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    secuencia: Mapped[int] = mapped_column(Integer)
    rol: Mapped[str] = mapped_column(String(10))
    tipo: Mapped[str] = mapped_column(String(25))
    contenido: Mapped[Any] = mapped_column(JSON)
    modelo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    uso_ia_id: Mapped[int | None] = mapped_column(ForeignKey("uso_ia.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class AccionIA(Base):
    __tablename__ = "acciones_ia"
    __table_args__ = (
        CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),
        CheckConstraint(en_lista("efecto", EFECTOS_ACCION_IA), name="efecto"),
        CheckConstraint("duracion_ms >= 0", name="duracion"),
        Index("ix_acciones_ia_conversacion_id_id", "conversacion_id", "id"),
        Index("ix_acciones_ia_llamada_id_id", "llamada_id", "id"),
        Index("ix_acciones_ia_campana_id_creado_en", "campana_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.id"))
    tool_use_id: Mapped[str] = mapped_column(String(64), unique=True)
    herramienta: Mapped[str] = mapped_column(String(40))
    entrada: Mapped[Any] = mapped_column(JSON)
    resultado: Mapped[Any] = mapped_column(JSON)
    es_error: Mapped[bool] = mapped_column(Boolean)
    codigo_error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    efecto: Mapped[str] = mapped_column(String(20))
    referencia_tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    referencia_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reglas_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duracion_ms: Mapped[int] = mapped_column(Integer)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class ErrorIA(Base):
    __tablename__ = "errores_ia"
    __table_args__ = (
        CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),
        Index("ix_errores_ia_campana_id_creado_en", "campana_id", "creado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    campana_id: Mapped[int] = mapped_column(ForeignKey("campanas.id"))
    codigo: Mapped[str] = mapped_column(String(40))
    transitorio: Mapped[bool] = mapped_column(Boolean)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class InstruccionSupervisor(Base):
    __tablename__ = "instrucciones_supervisor"
    __table_args__ = (
        CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),
        Index(
            "ix_instrucciones_supervisor_conversacion_id_aplicada_en",
            "conversacion_id",
            "aplicada_en",
        ),
        Index("ix_instrucciones_supervisor_llamada_id_aplicada_en", "llamada_id", "aplicada_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(ForeignKey("llamadas.id"), nullable=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    texto: Mapped[str] = mapped_column(String(1000))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    aplicada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)


class BloqueoTurnoIA(Base):
    """Arrendamiento: un turno por interacción a la vez (ADR-0022 §1)."""

    __tablename__ = "bloqueos_turno_ia"
    __table_args__ = (CheckConstraint(EXACTAMENTE_UNO, name="exactamente_uno"),)

    clave: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id", ondelete="CASCADE"), nullable=True
    )
    llamada_id: Mapped[int | None] = mapped_column(
        ForeignKey("llamadas.id", ondelete="CASCADE"), nullable=True
    )
    trabajador: Mapped[str] = mapped_column(String(120))
    adquirido_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    expira_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class ConfiguracionGlobal(Base):
    __tablename__ = "configuracion_global"

    clave: Mapped[str] = mapped_column(String(40), primary_key=True)
    valor: Mapped[Any] = mapped_column(JSON)
    actualizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class EvaluacionIA(Base):
    __tablename__ = "evaluaciones_ia"
    __table_args__ = (
        CheckConstraint(en_lista("modo", MODOS_EVALUACION), name="modo"),
        CheckConstraint(en_lista("canal", ("chat", "voz")), name="canal"),
        CheckConstraint(en_lista("estado", ESTADOS_EVALUACION), name="estado"),
        Index(
            "ix_evaluaciones_ia_modo_canal_prompt_version_huella_creado_en",
            "modo",
            "canal",
            "prompt_version",
            "huella",
            "creado_en",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    modo: Mapped[str] = mapped_column(String(8))
    canal: Mapped[str] = mapped_column(String(5))
    campana_id: Mapped[int | None] = mapped_column(
        ForeignKey("campanas.id", ondelete="SET NULL"), nullable=True
    )
    modelo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    esfuerzo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer)
    huella: Mapped[str] = mapped_column(String(64))
    patron_casos: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado: Mapped[str] = mapped_column(String(12))
    aprobada: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resumen: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    casos: Mapped[list[Any]] = mapped_column(JSON, default=list, server_default="[]")
    iniciada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    completada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
