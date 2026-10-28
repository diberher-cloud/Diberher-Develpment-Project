from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.modulos.conversaciones.esquemas import UsuarioRef
from app.tipos import FechaHoraZ

Finalidad = Literal["venta", "cobranza", "todas"]
CampoPlantilla = Literal["primer_nombre", "empresa", "agente", "producto"]
IdEntrada = Annotated[int, Field(ge=1, le=2**31 - 1)]


class ConfiguracionWhatsApp(BaseModel):
    proveedor: Literal["twilio", "falso"]
    simulacion: bool
    numero_empresa_mascara: str
    margen_ventana_segundos: int
    max_caracteres_texto: int
    max_conversaciones_agente: int
    media_max_bytes: int


class BotonSalida(BaseModel):
    tipo: Literal["respuesta_rapida", "url", "telefono", "otro"]
    texto: str
    payload: str | None


class PlantillaSalida(BaseModel):
    id: int
    content_sid: str
    nombre: str
    idioma: str
    categoria: Literal["marketing", "utility", "authentication", "desconocida"]
    estado_aprobacion: Literal[
        "aprobada", "pendiente", "rechazada", "pausada", "deshabilitada", "eliminada", "desconocido"
    ]
    motivo_rechazo: str | None
    cuerpo: str
    variables: list[str]
    botones: list[BotonSalida]
    tiene_boton_baja: bool
    mapeo_variables: dict[str, CampoPlantilla]
    finalidad: Finalidad | None
    activa: bool
    enviable: bool
    sincronizada_en: FechaHoraZ


class PlantillaActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finalidad: Finalidad | None = None
    mapeo_variables: dict[str, str] | None = None
    activa: bool | None = None


class ResultadoSincronizacion(BaseModel):
    creadas: int
    actualizadas: int
    desactivadas: int


class AutorizacionSalida(BaseModel):
    id: int
    numero_mascara: str
    numero_e164: str | None
    canal: Literal["whatsapp"]
    finalidad: Finalidad
    origen: Literal["importacion", "cliente", "agente", "agente_ia"]
    evidencia: str
    otorgada_en: FechaHoraZ
    vigente: bool
    revocada_en: FechaHoraZ | None
    motivo_revocacion: Literal["opt_out", "manual", "importacion"] | None
    registrada_por: UsuarioRef | None


Evidencia = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class AutorizacionCrear(BaseModel):
    telefono: Annotated[str, Field(max_length=40)]
    finalidad: Finalidad
    evidencia: Evidencia
    otorgada_en: AwareDatetime | None = None


class AutorizacionConversacionCrear(BaseModel):
    finalidad: Finalidad
    evidencia: Evidencia


class SimulacionMedia(BaseModel):
    tipo_contenido: Annotated[str, Field(min_length=3, max_length=100)]


class SimulacionEntrante(BaseModel):
    numero: Annotated[str, Field(max_length=40)]
    texto: Annotated[str, Field(max_length=4096)] | None = None
    nombre_perfil: Annotated[str, Field(max_length=100)] | None = None
    media: Annotated[list[SimulacionMedia], Field(max_length=10)] = Field(default_factory=list)
    boton_payload: Annotated[str, Field(max_length=256)] | None = None
    boton_texto: Annotated[str, Field(max_length=256)] | None = None


class SimulacionEntranteSalida(BaseModel):
    mensaje_id: int
    proveedor_id: str


class SimulacionEstado(BaseModel):
    estado: Literal["delivered", "read", "failed", "undelivered"]
    error_codigo: Annotated[str, Field(max_length=30)] | None = None
