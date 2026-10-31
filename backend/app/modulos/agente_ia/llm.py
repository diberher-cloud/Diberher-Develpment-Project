"""Puerto del modelo (fase-2c.md §4.2): `ClienteLLM` aísla el SDK de Anthropic. El resto del
núcleo solo conoce `RespuestaLLM` y `ErrorLLM`."""

import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config import get_settings


@dataclass(frozen=True)
class RespuestaLLM:
    id: str
    modelo: str  # response.model (el servido; difiere del pedido si actuó el fallback)
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal | pause_turn | otro
    stop_categoria: str | None  # stop_details.category si refusal
    contenido: list[dict[str, Any]]  # bloques tal cual los devolvió el modelo (sin modificar)
    uso: dict[str, int]  # input/output/cache_creation_input/cache_read_input _tokens
    request_id: str | None
    duracion_ms: int


class ErrorLLM(Exception):
    """Fallo del proveedor. `codigo` no contiene datos personales ni el mensaje del SDK."""

    def __init__(self, codigo: str, transitorio: bool) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.transitorio = transitorio


class ClienteLLM(Protocol):
    def crear_mensaje(
        self,
        *,
        modelo: str,
        max_tokens: int,
        esfuerzo: str,
        sistema: list[dict[str, Any]],
        herramientas: list[dict[str, Any]],
        mensajes: list[dict[str, Any]],
        fallback_rechazo: bool,
        cache_ttl: Literal["5m", "1h"],
    ) -> RespuestaLLM: ...


_cliente: ClienteLLM | None = None
_cerrojo = threading.Lock()


def obtener_cliente_llm() -> ClienteLLM:
    """Singleton por proceso según `IA_PROVEEDOR` (`falso`: modo demo determinista)."""
    global _cliente
    with _cerrojo:
        if _cliente is None:
            settings = get_settings()
            if settings.ia_proveedor == "anthropic":
                from app.modulos.agente_ia.llm_anthropic import ClienteAnthropic

                _cliente = ClienteAnthropic(
                    api_key=settings.anthropic_api_key.get_secret_value(),
                    timeout_segundos=settings.ia_timeout_segundos,
                )
            else:
                from app.modulos.agente_ia.llm_falso import ClienteLLMFalso

                _cliente = ClienteLLMFalso(None)
        return _cliente


def establecer_cliente_llm(cliente: ClienteLLM | None) -> None:
    """Sustituye el cliente (tests, evaluación)."""
    global _cliente
    with _cerrojo:
        _cliente = cliente
