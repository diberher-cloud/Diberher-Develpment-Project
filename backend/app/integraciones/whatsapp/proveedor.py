"""Interfaz del proveedor de WhatsApp y tipos neutros (ADR-0010, fase-2b.md §4.3)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

CategoriaMedia = Literal["imagen", "audio", "documento", "no_soportado"]


@dataclass(frozen=True)
class MediaEntrante:
    indice: int
    url: str  # URL del proveedor; NUNCA se envía al navegador
    tipo_contenido: str  # en minúsculas, sin parámetros (";codecs=opus" se descarta)


@dataclass(frozen=True)
class MensajeEntrante:
    proveedor_id: str  # MessageSid
    numero_cliente: str  # E.164 sin prefijo "whatsapp:"
    numero_empresa: str  # E.164
    cuenta: str | None  # AccountSid
    texto: str | None  # Body (recortado a 4096)
    nombre_perfil: str | None  # ProfileName (<= 100)
    media: tuple[MediaEntrante, ...]
    boton_payload: str | None  # ButtonPayload
    boton_texto: str | None  # ButtonText
    respuesta_a: str | None  # OriginalRepliedMessageSid


@dataclass(frozen=True)
class EstadoMensaje:
    proveedor_id: str
    estado_proveedor: str  # valor crudo (MessageStatus)
    estado: Literal["enviado", "entregado", "leido", "fallido"] | None  # None = ignorar
    error_codigo: str | None  # ErrorCode


@dataclass(frozen=True)
class EnvioResultado:
    proveedor_id: str
    estado_proveedor: str


@dataclass(frozen=True)
class BotonPlantilla:
    tipo: Literal["respuesta_rapida", "url", "telefono", "otro"]
    texto: str
    payload: str | None


@dataclass(frozen=True)
class PlantillaRemota:
    ref: str  # ContentSid
    nombre: str
    idioma: str
    categoria: str  # ya mapeada al catálogo de plantillas_whatsapp
    estado_aprobacion: str  # ya mapeado al catálogo de plantillas_whatsapp
    motivo_rechazo: str | None
    cuerpo: str
    variables: tuple[str, ...]
    botones: tuple[BotonPlantilla, ...]


class ErrorProveedorWhatsApp(Exception):
    """Error del proveedor. `codigo` nunca contiene datos personales."""

    def __init__(self, codigo: str, transitorio: bool) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.transitorio = transitorio


class ProveedorWhatsApp(Protocol):
    nombre: Literal["twilio", "falso"]

    def enviar_texto(
        self, *, origen: str, destino: str, texto: str, url_estado: str
    ) -> EnvioResultado: ...

    def enviar_plantilla(
        self,
        *,
        origen: str,
        destino: str,
        plantilla_ref: str,
        variables: dict[str, str],
        url_estado: str,
    ) -> EnvioResultado: ...

    def listar_plantillas(self) -> list[PlantillaRemota]: ...

    def validar_firma(
        self, url: str, params: Mapping[str, str | Sequence[str]], firma: str | None
    ) -> bool: ...

    def parsear_entrante(self, params: Mapping[str, str]) -> MensajeEntrante | None: ...

    def parsear_estado(self, params: Mapping[str, str]) -> EstadoMensaje | None: ...

    def url_media_valida(self, url: str) -> bool: ...

    def descargar_media(self, url: str, max_bytes: int) -> tuple[str, bytes]: ...
