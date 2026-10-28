from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modulos.clientes.esquemas import ClienteSalida, Monto
from app.tipos import FechaHoraZ

EstadoAgenteValor = Literal["desconectado", "disponible", "pausa", "en_llamada", "tipificando"]
MotivoPausa = Literal["descanso", "almuerzo", "capacitacion", "reunion", "otro"]
Resultado = Literal[
    "contactado",
    "no_contesta",
    "numero_errado",
    "promesa_pago",
    "venta",
    "rechazo",
    "volver_a_llamar",
]
TipoCampana = Literal["venta", "cobranza"]
EstadoRegistro = Literal["pendiente", "en_gestion", "gestionado", "descartado"]
Canal = Literal["voz", "whatsapp_mensaje", "whatsapp_llamada"]
Origen = Literal["agente", "agente_ia", "sistema"]
IdEntrada = Annotated[int, Field(ge=1, le=2**31 - 1)]


# ---- Estado ----------------------------------------------------------------------------------
class TipificacionPendiente(BaseModel):
    llamada_id: int
    campana_cliente_id: int


class EstadoAgenteSalida(BaseModel):
    estado: EstadoAgenteValor
    desde: FechaHoraZ
    motivo_pausa: MotivoPausa | None
    llamada_id: int | None
    tipificacion_pendiente: TipificacionPendiente | None


class CambioEstado(BaseModel):
    estado: Literal["disponible", "pausa", "desconectado"]
    motivo_pausa: MotivoPausa | None = None

    @model_validator(mode="after")
    def _motivo(self) -> "CambioEstado":
        if self.estado == "pausa" and self.motivo_pausa is None:
            raise ValueError("El motivo de pausa es obligatorio.")
        if self.estado != "pausa" and self.motivo_pausa is not None:
            raise ValueError("El motivo de pausa solo aplica al estado 'pausa'.")
        return self


# ---- Lista de trabajo y ficha ----------------------------------------------------------------
class CampanaConsola(BaseModel):
    id: int
    nombre: str
    tipo: TipoCampana
    pendientes: int


class RegistroTrabajo(BaseModel):
    id: int
    campana_id: int
    campana_nombre: str
    tipo_campana: TipoCampana
    nombre_cliente: str
    estado: EstadoRegistro
    intentos: int
    max_intentos: int
    ultimo_resultado: Resultado | None
    ultima_gestion_en: FechaHoraZ | None
    proximo_intento_en: FechaHoraZ | None
    saldo_mora: Monto | None
    dias_mora: int | None
    producto: str | None
    reservado_por_mi: bool


class MotivoSalida(BaseModel):
    codigo: str
    mensaje: str


class CumplimientoSalida(BaseModel):
    permitido: bool
    motivos: list[MotivoSalida]
    momento_local: str
    proxima_ventana_inicio: str | None
    politica_version: int


class ConversacionAbiertaRef(BaseModel):
    id: int
    atendida_por: Literal["sin_asignar", "humano", "ia"]
    ventana_abierta: bool


class WhatsAppTelefono(BaseModel):
    """Estado de WhatsApp de un móvil en la ficha (nulo si la campaña no usa WhatsApp)."""

    autorizado: bool
    excluido: bool
    enviable: bool
    motivos: list[MotivoSalida]
    conversacion_abierta: ConversacionAbiertaRef | None


class TelefonoFicha(BaseModel):
    id: int
    numero_mascara: str
    tipo_linea: Literal["movil", "fijo"]
    prioridad: int
    excluido: bool
    llamable: bool
    motivos: list[MotivoSalida]
    whatsapp: WhatsAppTelefono | None = None


class PromesaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monto: Monto
    fecha_pago: date
    numero_cuotas: int
    descuento_porcentaje: Monto
    estado: Literal["vigente", "cumplida", "incumplida", "anulada"]


class VentaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto: str
    valor: Monto
    unidades: int


class GestionHistorial(BaseModel):
    id: int
    canal: Canal
    origen: Origen
    agente_nombre: str | None
    resultado: Resultado
    contacto_directo: bool
    observacion: str | None
    creado_en: FechaHoraZ
    promesa: PromesaSalida | None
    venta: VentaSalida | None
    volver_a_llamar_en: FechaHoraZ | None


class CampanaResumen(BaseModel):
    id: int
    nombre: str
    tipo: TipoCampana


class FichaCliente(BaseModel):
    id: int
    campana: CampanaResumen
    estado: EstadoRegistro
    reservado_hasta: FechaHoraZ | None
    intentos: int
    max_intentos: int
    ultimo_resultado: Resultado | None
    proximo_intento_en: FechaHoraZ | None
    cliente: ClienteSalida
    telefonos: list[TelefonoFicha]
    numero_obligacion: str | None
    saldo_total: Monto | None
    saldo_mora: Monto | None
    dias_mora: int | None
    fecha_vencimiento: date | None
    producto: str | None
    oferta: str | None
    datos_adicionales: dict[str, Any]
    guion: str | None
    cumplimiento: CumplimientoSalida
    historial: list[GestionHistorial]


# ---- Llamadas --------------------------------------------------------------------------------
class LlamadaSalida(BaseModel):
    id: int
    campana_cliente_id: int
    telefono_id: int
    canal: Literal["voz", "whatsapp_llamada"]
    direccion: Literal["saliente", "entrante"]
    estado: str
    motivos_bloqueo: list[MotivoSalida]
    iniciada_en: FechaHoraZ
    contestada_en: FechaHoraZ | None
    finalizada_en: FechaHoraZ | None
    duracion_segundos: int | None
    tipificada: bool


# ---- Tipificaciones --------------------------------------------------------------------------
class PromesaEntrada(BaseModel):
    monto: str
    fecha_pago: date


class VentaEntrada(BaseModel):
    producto: str
    valor: str


class TipificacionDatos(BaseModel):
    """Datos de una tipificación (comunes a llamada y conversación)."""

    resultado: Resultado
    observacion: str | None = None
    contacto_directo: bool | None = None
    promesa: PromesaEntrada | None = None
    venta: VentaEntrada | None = None
    volver_a_llamar_en: AwareDatetime | None = None


class TipificacionCrear(TipificacionDatos):
    llamada_id: IdEntrada


class RegistroResultante(BaseModel):
    estado: EstadoRegistro
    intentos: int
    proximo_intento_en: FechaHoraZ | None


class TipificacionBase(BaseModel):
    id: int
    campana_cliente_id: int
    llamada_id: int | None
    conversacion_id: int | None = None
    canal: Canal
    origen: Origen
    usuario_id: int | None
    resultado: Resultado
    contacto_directo: bool
    observacion: str | None
    promesa: PromesaSalida | None
    venta: VentaSalida | None
    volver_a_llamar_en: FechaHoraZ | None
    creado_en: FechaHoraZ


class TipificacionSalida(TipificacionBase):
    registro: RegistroResultante


class TipificacionCampanaSalida(TipificacionBase):
    cliente_nombre: str
    agente_nombre: str | None
