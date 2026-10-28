from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.catalogos import (
    ATENDIDA_POR,
    AUTORES_MENSAJE,
    DIRECCIONES_MENSAJE,
    ESTADOS_COLA,
    ESTADOS_CONVERSACION,
    ESTADOS_MENSAJE,
    INICIADA_POR,
    MOTIVOS_CIERRE,
    MOTIVOS_COLA,
    TIPOS_MENSAJE,
    en_lista,
)
from app.db import Base, FechaHoraUTC


class Conversacion(Base):
    __tablename__ = "conversaciones"
    __table_args__ = (
        CheckConstraint(en_lista("estado", ESTADOS_CONVERSACION), name="estado"),
        CheckConstraint(en_lista("atendida_por", ATENDIDA_POR), name="atendida_por"),
        CheckConstraint(en_lista("iniciada_por", INICIADA_POR), name="iniciada_por"),
        CheckConstraint(
            "motivo_cierre IS NULL OR " + en_lista("motivo_cierre", MOTIVOS_CIERRE),
            name="motivo_cierre",
        ),
        CheckConstraint("mensajes_sin_leer >= 0", name="mensajes_sin_leer"),
        CheckConstraint(
            "(estado='abierta' AND clave_abierta IS NOT NULL AND cerrada_en IS NULL) OR "
            "(estado='cerrada' AND clave_abierta IS NULL AND cerrada_en IS NOT NULL)",
            name="ciclo_de_vida",
        ),
        CheckConstraint(
            "(atendida_por='humano' AND usuario_asignado_id IS NOT NULL) OR "
            "(atendida_por<>'humano' AND usuario_asignado_id IS NULL)",
            name="dueno_coherente",
        ),
        CheckConstraint(
            "campana_cliente_id IS NULL OR (campana_id IS NOT NULL AND cliente_id IS NOT NULL)",
            name="registro_coherente",
        ),
        Index("ix_conversaciones_estado_atendida_por", "estado", "atendida_por"),
        Index("ix_conversaciones_usuario_asignado_id_estado", "usuario_asignado_id", "estado"),
        Index("ix_conversaciones_campana_id_estado", "campana_id", "estado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clave_abierta: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    numero_cliente_e164: Mapped[str] = mapped_column(String(16), index=True)
    numero_empresa_e164: Mapped[str] = mapped_column(String(16))
    nombre_perfil: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cliente_id: Mapped[int | None] = mapped_column(
        ForeignKey("clientes.id"), nullable=True, index=True
    )
    campana_id: Mapped[int | None] = mapped_column(ForeignKey("campanas.id"), nullable=True)
    campana_cliente_id: Mapped[int | None] = mapped_column(
        ForeignKey("campana_clientes.id"), nullable=True, index=True
    )
    telefono_id: Mapped[int | None] = mapped_column(ForeignKey("telefonos.id"), nullable=True)
    estado: Mapped[str] = mapped_column(String(10))
    atendida_por: Mapped[str] = mapped_column(String(12))
    usuario_asignado_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    asignada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    iniciada_por: Mapped[str] = mapped_column(String(10))
    intento_contacto_id: Mapped[int | None] = mapped_column(
        ForeignKey("intentos_contacto.id"), nullable=True
    )
    ventana_expira_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    ultimo_mensaje_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    ultimo_entrante_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    mensajes_sin_leer: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    aviso_espera_enviado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    aviso_fuera_franja_enviado_en: Mapped[datetime | None] = mapped_column(
        FechaHoraUTC, nullable=True
    )
    abierta_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    cerrada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    motivo_cierre: Mapped[str | None] = mapped_column(String(15), nullable=True)
    cerrada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    # Previstas para 2C (sin lógica en 2B)
    identidad_verificada: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    identidad_intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    turnos_ia: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    costo_usd_acumulado: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0"), server_default="0"
    )
    modelo_ia: Mapped[str | None] = mapped_column(String(40), nullable=True)
    esfuerzo_ia: Mapped[str | None] = mapped_column(String(10), nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aviso_ia_enviado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)


class Mensaje(Base):
    __tablename__ = "mensajes"
    __table_args__ = (
        CheckConstraint(en_lista("direccion", DIRECCIONES_MENSAJE), name="direccion"),
        CheckConstraint(en_lista("autor", AUTORES_MENSAJE), name="autor"),
        CheckConstraint(en_lista("tipo", TIPOS_MENSAJE), name="tipo"),
        CheckConstraint(en_lista("estado", ESTADOS_MENSAJE), name="estado"),
        CheckConstraint(
            "autor <> 'agente' OR usuario_id IS NOT NULL", name="agente_requiere_usuario"
        ),
        CheckConstraint(
            "direccion = 'entrante' OR conversacion_id IS NOT NULL",
            name="saliente_con_conversacion",
        ),
        CheckConstraint(
            "(direccion='entrante' AND autor='cliente' AND estado='recibido') OR "
            "(direccion='saliente' AND autor<>'cliente' AND estado<>'recibido')",
            name="direccion_coherente",
        ),
        Index("ix_mensajes_conversacion_id_id", "conversacion_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversaciones.id"), nullable=True
    )
    numero_cliente_e164: Mapped[str] = mapped_column(String(16))
    direccion: Mapped[str] = mapped_column(String(10))
    autor: Mapped[str] = mapped_column(String(10))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(15))
    cuerpo: Mapped[str | None] = mapped_column(Text, nullable=True)
    plantilla_id: Mapped[int | None] = mapped_column(
        ForeignKey("plantillas_whatsapp.id"), nullable=True
    )
    variables: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    media: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    boton_payload: Mapped[str | None] = mapped_column(String(256), nullable=True)
    boton_texto: Mapped[str | None] = mapped_column(String(256), nullable=True)
    respuesta_a_proveedor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proveedor_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    idempotencia_clave: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    estado: Mapped[str] = mapped_column(String(10))
    error_codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    programado_para: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    enviado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    entregado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    leido_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    procesado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    procesado_ia_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)


class EventoMensaje(Base):
    __tablename__ = "eventos_mensaje"
    __table_args__ = (UniqueConstraint("proveedor_id", "estado_proveedor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proveedor_id: Mapped[str] = mapped_column(String(64))
    mensaje_id: Mapped[int | None] = mapped_column(
        ForeignKey("mensajes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    estado_proveedor: Mapped[str] = mapped_column(String(20))
    error_codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recibido_en: Mapped[datetime] = mapped_column(FechaHoraUTC)


class ColaAtencion(Base):
    __tablename__ = "cola_atencion"
    __table_args__ = (
        CheckConstraint(en_lista("motivo", MOTIVOS_COLA), name="motivo"),
        CheckConstraint("prioridad BETWEEN 1 AND 3", name="prioridad"),
        CheckConstraint(en_lista("estado", ESTADOS_COLA), name="estado"),
        Index("ix_cola_atencion_estado_prioridad_creado_en", "estado", "prioridad", "creado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversacion_id: Mapped[int] = mapped_column(
        ForeignKey("conversaciones.id", ondelete="CASCADE"), index=True
    )
    campana_id: Mapped[int | None] = mapped_column(ForeignKey("campanas.id"), nullable=True)
    motivo: Mapped[str] = mapped_column(String(25))
    resumen: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prioridad: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(10))
    clave_activa: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    asignada_a: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC)
    asignada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
    cerrada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC, nullable=True)
