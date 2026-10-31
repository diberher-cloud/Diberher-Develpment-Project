"""Esquemas Pydantic de la API del agente IA (fase-2c.md §6)."""

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modulos.clientes.esquemas import Monto
from app.modulos.conversaciones.esquemas import (
    ConversacionResumen,
    EstadoIAConversacion,
    GestionIA,
    Monto6,
    Requisito,
    UltimoTraspaso,
    UsuarioRef,
)
from app.tipos import FechaHoraZ

Monto4 = Annotated[
    Decimal, PlainSerializer(lambda v: f"{v:.4f}", return_type=str, when_used="json")
]
Esfuerzo = Literal["low", "medium", "high", "xhigh", "max"]
Tratamiento = Literal["usted", "tu"]
TipoCampana = Literal["venta", "cobranza"]


class RequisitosActivacion(BaseModel):
    cumple: bool
    faltantes: list[Requisito]


class VerificacionIA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factores: list[Literal["numero_documento"]]
    max_intentos: int = Field(ge=1, le=5)


class ConfiguracionIA(BaseModel):
    campana_id: int
    campana_tipo: TipoCampana
    configurada: bool
    activa: bool
    version: int
    modelo: str
    esfuerzo: Esfuerzo
    prompt_version: int
    tratamiento: Tratamiento
    instrucciones: str | None
    verificacion: VerificacionIA
    reglas: dict[str, Any] | None
    presupuesto_usd_mensual: Monto
    max_costo_conversacion_usd: Monto4
    max_turnos_conversacion: int
    desactivada_motivo: Literal["manual", "presupuesto", "errores"] | None
    activada_en: FechaHoraZ | None
    desactivada_en: FechaHoraZ | None
    gasto_mes_usd: Monto6
    requisitos: RequisitosActivacion
    actualizado_por: UsuarioRef | None
    actualizado_en: FechaHoraZ | None


class ConfiguracionIAActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_esperada: int = Field(ge=0, le=2**31 - 1)
    modelo: str = Field(min_length=1, max_length=40)
    esfuerzo: Esfuerzo
    prompt_version: int = Field(ge=1, le=1000)
    tratamiento: Tratamiento
    instrucciones: str | None = None
    verificacion: VerificacionIA
    reglas: dict[str, Any]
    presupuesto_usd_mensual: Decimal = Field(ge=0, le=Decimal("9999999999.99"), decimal_places=2)
    max_costo_conversacion_usd: Decimal = Field(
        ge=Decimal("0.01"), le=Decimal("10"), decimal_places=4
    )
    max_turnos_conversacion: int = Field(ge=1, le=200)


class Oferta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campana_id: int
    codigo: str
    nombre: str
    descripcion: str | None
    precio: Monto
    descuento_max_pct: Monto
    max_unidades: int
    condiciones: str | None
    activa: bool
    actualizado_en: FechaHoraZ


class OfertaCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str
    nombre: str
    descripcion: str | None = None
    precio: Decimal
    descuento_max_pct: Decimal = Decimal("0")
    max_unidades: int = 1
    condiciones: str | None = None
    activa: bool = True


class OfertaActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str | None = None
    descripcion: str | None = None
    precio: Decimal | None = None
    descuento_max_pct: Decimal | None = None
    max_unidades: int | None = None
    condiciones: str | None = None
    activa: bool | None = None


class ConfiguracionGlobalIA(BaseModel):
    ia_activa: bool
    ia_habilitada_entorno: bool
    proveedor: Literal["falso", "anthropic"]
    modelos_permitidos: list[str]
    esfuerzos: list[str]
    prompts: dict[str, list[int]]
    exigir_evaluacion_online: bool
    actualizado_por: UsuarioRef | None
    actualizado_en: FechaHoraZ | None


class ConfiguracionGlobalActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ia_activa: bool


class UltimaAccion(BaseModel):
    herramienta: str
    es_error: bool
    creado_en: FechaHoraZ


class IAResumen(BaseModel):
    identidad_verificada: bool
    turnos: int
    costo_usd: Monto6
    modelo: str
    gestion: GestionIA | None
    ultima_accion: UltimaAccion | None
    turno_en_curso: bool
    instrucciones_pendientes: int


class ConversacionIAResumen(ConversacionResumen):
    ia: IAResumen


class AccionIA(BaseModel):
    id: int
    tool_use_id: str
    herramienta: str
    entrada: dict[str, Any]
    resultado: dict[str, Any] | None
    es_error: bool
    codigo_error: str | None
    efecto: str
    referencia: dict[str, Any] | None
    duracion_ms: int
    creado_en: FechaHoraZ


class LlamadaModelo(BaseModel):
    id: int
    iteracion: int
    modelo: str
    modelo_servido: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    costo_usd: Monto6
    duracion_ms: int
    request_id: str | None
    creado_en: FechaHoraZ


class TotalUso(BaseModel):
    llamadas: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    costo_usd: Monto6
    tasa_cache: float | None


class UsoIAConversacion(BaseModel):
    total: TotalUso
    llamadas: list[LlamadaModelo]


class InstruccionCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str


class Instruccion(BaseModel):
    id: int
    conversacion_id: int
    usuario: UsuarioRef
    texto: str
    creado_en: FechaHoraZ
    aplicada_en: FechaHoraZ | None


class TraspasarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resumen: str | None = None


class FilaHistorialSalida(BaseModel):
    secuencia: int
    rol: str
    tipo: str
    contenido: Any
    creado_en: FechaHoraZ


class Importe(BaseModel):
    numero: int
    monto_total: Monto


class ImporteVenta(BaseModel):
    numero: int
    valor_total: Monto


class Tiempos(BaseModel):
    p50: int | None
    p95: int | None


class Tokens(BaseModel):
    entrada: int
    salida: int
    cache_escritura: int
    cache_lectura: int


class MetricasIA(BaseModel):
    campana_id: int | None
    desde: str
    hasta: str
    conversaciones: int
    con_identidad_verificada: int
    tasa_verificacion: float | None
    acuerdos: Importe
    ventas: ImporteVenta
    resultados: dict[str, int]
    derivaciones: dict[str, int]
    opt_outs: int
    cerradas_por_ia: int
    cerradas_por_inactividad: int
    costo_usd: Monto6
    costo_por_acuerdo_usd: Monto6 | None
    tokens: Tokens
    tasa_cache: float | None
    tiempo_respuesta_ms: Tiempos
    errores: dict[str, int]
    guardas: dict[str, int]


class EvaluacionCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modo: Literal["offline", "online"]
    canal: Literal["chat"] = "chat"
    campana_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    casos: str | None = Field(default=None, max_length=100)


class EvaluacionIA(BaseModel):
    id: int
    modo: str
    canal: str
    campana_id: int | None
    modelo: str | None
    esfuerzo: str | None
    prompt_version: int
    huella: str
    patron_casos: str | None
    estado: str
    aprobada: bool | None
    resumen: dict[str, Any]
    casos: list[Any]
    iniciada_por: UsuarioRef | None
    creado_en: FechaHoraZ
    completada_en: FechaHoraZ | None


__all__ = ["EstadoIAConversacion", "GestionIA", "UltimoTraspaso"]
