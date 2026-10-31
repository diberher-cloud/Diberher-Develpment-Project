"""`ClienteAnthropic`: adaptador del SDK oficial (única importación de `anthropic`).

Parámetros verificados contra anthropic 1.17.0 (V-C3): `output_config={"effort": ...}`,
`cache_control` de nivel superior, `client.beta.messages.create(betas=[...],
fallbacks="default")`, `_request_id` y `stop_details`. Nunca se envían `temperature`, `top_p`,
`top_k`, `thinking`, `tool_choice` (por defecto `auto`) ni un turno `assistant` final (prefill).
Los logs nunca incluyen contenido ni `str(excepción)`.
"""

import logging
import time
from typing import Any, Literal

import anthropic

from app.modulos.agente_ia.llm import ErrorLLM, RespuestaLLM

logger = logging.getLogger("app.ia")
BETA_FALLBACK = "server-side-fallback-2026-07-01"
STOPS_CONOCIDOS = frozenset({"end_turn", "tool_use", "max_tokens", "refusal", "pause_turn"})
CLAVES_USO = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def traducir_error(exc: Exception) -> ErrorLLM:
    """Excepción del SDK -> `ErrorLLM` (fase-2c.md §4.2)."""
    if isinstance(exc, anthropic.RateLimitError):
        return ErrorLLM("RATE_LIMIT", True)
    if isinstance(exc, anthropic.APITimeoutError):  # subclase de APIConnectionError
        return ErrorLLM("TIMEOUT", True)
    if isinstance(exc, anthropic.APIConnectionError):
        return ErrorLLM("CONEXION", True)
    if isinstance(exc, anthropic.APIStatusError):
        estado = int(exc.status_code)
        return ErrorLLM(f"HTTP_{estado}", estado >= 500)
    return ErrorLLM("ERROR_SDK", False)


def _ttl(cache_ttl: Literal["5m", "1h"]) -> dict[str, str]:
    return {"type": "ephemeral"} if cache_ttl == "5m" else {"type": "ephemeral", "ttl": "1h"}


class ClienteAnthropic:
    def __init__(
        self,
        api_key: str = "",
        timeout_segundos: float = 45,
        cliente: Any | None = None,
    ) -> None:
        # `cliente` permite inyectar un objeto con la forma de `anthropic.Anthropic` (tests).
        self._cliente = cliente or anthropic.Anthropic(
            api_key=api_key,
            max_retries=2,
            timeout=anthropic.Timeout(timeout_segundos, connect=5.0),
        )

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
    ) -> RespuestaLLM:
        parametros: dict[str, Any] = {
            "model": modelo,
            "max_tokens": max_tokens,
            "system": sistema,
            "tools": herramientas,
            "messages": mensajes,
            "output_config": {"effort": esfuerzo},
            "cache_control": _ttl(cache_ttl),
        }
        inicio = time.perf_counter()
        try:
            if fallback_rechazo:
                respuesta = self._cliente.beta.messages.create(
                    **parametros, betas=[BETA_FALLBACK], fallbacks="default"
                )
            else:
                respuesta = self._cliente.messages.create(**parametros)
        except Exception as exc:
            if not isinstance(exc, anthropic.AnthropicError):
                raise
            error = traducir_error(exc)
            logger.warning(
                "ia.error codigo=%s request_id=%s", error.codigo, getattr(exc, "request_id", None)
            )
            raise error from None
        return self._a_respuesta(respuesta, int((time.perf_counter() - inicio) * 1000))

    @staticmethod
    def _a_respuesta(respuesta: Any, duracion_ms: int) -> RespuestaLLM:
        stop = respuesta.stop_reason if respuesta.stop_reason in STOPS_CONOCIDOS else "otro"
        detalles = getattr(respuesta, "stop_details", None)
        categoria = getattr(detalles, "category", None) if stop == "refusal" else None
        usage = respuesta.usage
        return RespuestaLLM(
            id=respuesta.id,
            modelo=respuesta.model,
            stop_reason=stop,
            stop_categoria=categoria,
            contenido=[b.to_dict(mode="json") for b in respuesta.content],
            uso={k: int(getattr(usage, k, None) or 0) for k in CLAVES_USO},
            request_id=getattr(respuesta, "_request_id", None),
            duracion_ms=duracion_ms,
        )
