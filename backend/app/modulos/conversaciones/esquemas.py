from decimal import Decimal
from typing import Annotated, Literal

from pydantic import UUID4, BaseModel, ConfigDict, PlainSerializer

from app.modulos.consola.esquemas import (
    EstadoRegistro,
    IdEntrada,
    MotivoSalida,
    TipificacionDatos,
    TipificacionSalida,
)
from app.tipos import FechaHoraZ

TipoCampana = Literal["venta", "cobranza"]
EstadoConversacion = Literal["abierta", "cerrada"]
AtendidaPor = Literal["sin_asignar", "humano", "ia"]
MotivoCierre = Literal["agente", "supervisor", "inactividad", "opt_out", "sistema"]
CategoriaMedia = Literal["imagen", "audio", "documento", "no_soportado"]


class UsuarioRef(BaseModel):
    id: int
    nombre: str


class CampanaRef(BaseModel):
    id: int
    nombre: str
    tipo: TipoCampana


class ConversacionResumen(BaseModel):
    id: int
    estado: EstadoConversacion
    atendida_por: AtendidaPor
    usuario_asignado: UsuarioRef | None
    numero_mascara: str
    numero_e164: str | None
    nombre_perfil: str | None
    campana: CampanaRef | None
    cliente_nombre: str | None
    iniciada_por: Literal["empresa", "cliente"]
    ventana_abierta: bool
    ventana_expira_en: FechaHoraZ | None
    ultimo_mensaje_en: FechaHoraZ
    mensajes_sin_leer: int
    motivo_cola: str | None
    abierta_en: FechaHoraZ
    cerrada_en: FechaHoraZ | None
    motivo_cierre: MotivoCierre | None


Monto6 = Annotated[
    Decimal, PlainSerializer(lambda v: f"{v:.6f}", return_type=str, when_used="json")
]


class Requisito(BaseModel):
    codigo: str
    mensaje: str


class GestionIA(BaseModel):
    resultado: str
    tipificacion_id: int


class UltimoTraspaso(BaseModel):
    motivo: str
    resumen: str | None
    creado_en: FechaHoraZ


class EstadoIAConversacion(BaseModel):
    identidad_verificada: bool
    turnos: int
    costo_usd: Monto6 | None
    modelo: str | None
    gestion: GestionIA | None
    aviso_enviado: bool
    ultimo_traspaso: UltimoTraspaso | None
    puede_devolver_ia: bool
    motivos_no_devolver: list[Requisito]


class Conversacion(ConversacionResumen):
    campana_cliente_id: int | None
    cliente_id: int | None
    telefono_id: int | None
    tipificada: bool
    puede_responder: bool
    motivos_no_responder: list[MotivoSalida]
    alertas: list[MotivoSalida]
    ia: EstadoIAConversacion | None = None


class MediaMensaje(BaseModel):
    indice: int
    categoria: CategoriaMedia
    tipo_contenido: str
    disponible: bool


class BotonMensaje(BaseModel):
    payload: str
    texto: str | None


class ErrorMensaje(BaseModel):
    codigo: str
    mensaje: str


class PlantillaRef(BaseModel):
    id: int
    nombre: str


class Mensaje(BaseModel):
    id: int
    conversacion_id: int
    direccion: Literal["entrante", "saliente"]
    autor: Literal["cliente", "agente", "ia", "sistema"]
    usuario: UsuarioRef | None
    tipo: Literal["texto", "plantilla", "media", "boton", "no_soportado"]
    cuerpo: str | None
    plantilla: PlantillaRef | None
    media: list[MediaMensaje]
    boton: BotonMensaje | None
    estado: str
    error: ErrorMensaje | None
    programado_para: FechaHoraZ | None
    creado_en: FechaHoraZ
    enviado_en: FechaHoraZ | None
    entregado_en: FechaHoraZ | None
    leido_en: FechaHoraZ | None


class PaginaMensajes(BaseModel):
    items: list[Mensaje]
    hay_mas: bool


class MensajeTextoCrear(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    texto: str
    idempotencia_clave: UUID4


class PlantillaEnvioCrear(BaseModel):
    plantilla_id: IdEntrada
    idempotencia_clave: UUID4


class PlantillaConsolaCrear(PlantillaEnvioCrear):
    telefono_id: IdEntrada


class ResultadoEnvioPlantilla(BaseModel):
    permitido: bool
    motivos: list[MotivoSalida]
    proxima_ventana_inicio: str | None
    politica_version: int | None
    conversacion_id: int | None
    mensaje: Mensaje | None


class ItemCola(BaseModel):
    id: int
    conversacion_id: int
    campana: dict | None
    motivo: str
    prioridad: int
    resumen: str | None
    numero_mascara: str
    creado_en: FechaHoraZ
    espera_segundos: int


class RegistroCandidato(BaseModel):
    campana_cliente_id: int
    campana: CampanaRef
    cliente_nombre: str
    estado: EstadoRegistro


class VincularRegistro(BaseModel):
    campana_cliente_id: IdEntrada


class AsignarEntrada(BaseModel):
    usuario_id: IdEntrada


class OptOutEntrada(BaseModel):
    alcance: Literal["whatsapp", "todos"]


class CierreConversacionCrear(BaseModel):
    tipificacion: TipificacionDatos | None = None


class CierreConversacion(BaseModel):
    conversacion: Conversacion
    tipificacion: TipificacionSalida | None
