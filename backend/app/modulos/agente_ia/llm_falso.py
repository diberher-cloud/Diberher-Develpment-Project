"""`ClienteLLMFalso`: modelo determinista para tests, evaluación offline y modo demo (§4.2).

Construcción: `ClienteLLMFalso(guion)` con una lista de pasos (uno por llamada) o una función
`(mensajes) -> paso`. Formato de un paso (el mismo que `guion_llm_falso` de los casos):
`{"texto": ...}` · `{"herramientas": [{"name", "input"}], "texto"?: ...}` ·
`{"stop_reason": "refusal", "categoria": "cyber"}` · `{"stop_reason": "max_tokens"}` ·
`{"stop_reason": "pause_turn"}` · `{"error": "RATE_LIMIT"}`; opcionales `thinking`, `uso`,
`retardo` (segundos) y `antes` (función que se ejecuta antes de responder). Con `guion=None` usa el
modo demo para probar a mano con el simulador de WhatsApp.
"""

import copy
import json
import re
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Literal

from app.modulos.agente_ia.llm import ErrorLLM, RespuestaLLM
from app.modulos.consola.guion import formatear_monto

PasoGuion = dict[str, Any]
TRANSITORIOS = frozenset({"RATE_LIMIT", "CONEXION", "TIMEOUT"})


class GuionAgotado(AssertionError):
    """Se pidieron más llamadas al modelo que pasos guionizados (el test debe fallar)."""


def _es_transitorio(codigo: str) -> bool:
    if codigo in TRANSITORIOS:
        return True
    return codigo.startswith("HTTP_5") or codigo == "HTTP_529"


class ClienteLLMFalso:
    def __init__(
        self,
        guion: list[PasoGuion] | Callable[[list[dict[str, Any]]], PasoGuion] | None = None,
        retardo: float = 0.0,
    ) -> None:
        self.guion = guion
        self.retardo = retardo
        self.peticiones: list[dict[str, Any]] = []
        self.llamadas = 0
        self.gancho: Callable[[dict[str, Any]], None] | None = None
        self._prefijos: set[str] = set()
        self._cerrojo = threading.Lock()
        self._n_msg = 0
        self._n_tool = 0

    # ---- API del puerto -----------------------------------------------------------------
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
        peticion = copy.deepcopy(
            {
                "modelo": modelo,
                "max_tokens": max_tokens,
                "esfuerzo": esfuerzo,
                "sistema": sistema,
                "herramientas": herramientas,
                "mensajes": mensajes,
                "fallback_rechazo": fallback_rechazo,
                "cache_ttl": cache_ttl,
            }
        )
        with self._cerrojo:
            self.peticiones.append(peticion)
            indice = self.llamadas
            self.llamadas += 1
            paso = self._siguiente(indice, mensajes)
            prefijo = json.dumps([sistema, herramientas, modelo], sort_keys=True, default=str)
            repetido = prefijo in self._prefijos
            self._prefijos.add(prefijo)
        if self.gancho is not None:
            self.gancho(peticion)
        if callable(paso.get("antes")):
            paso["antes"](peticion)
        if self.retardo or paso.get("retardo"):
            time.sleep(paso.get("retardo", self.retardo))
        if "error" in paso:
            raise ErrorLLM(paso["error"], _es_transitorio(paso["error"]))
        return self._respuesta(paso, modelo, mensajes, repetido)

    # ---- Internos -----------------------------------------------------------------------
    def _siguiente(self, indice: int, mensajes: list[dict[str, Any]]) -> PasoGuion:
        if self.guion is None:
            return paso_demo(mensajes)
        if callable(self.guion):
            return self.guion(mensajes)
        if indice >= len(self.guion):
            raise GuionAgotado(
                f"El guion tiene {len(self.guion)} pasos y se pidió el {indice + 1}."
            )
        return self.guion[indice]

    def _respuesta(
        self, paso: PasoGuion, modelo: str, mensajes: list[dict[str, Any]], repetido: bool
    ) -> RespuestaLLM:
        contenido: list[dict[str, Any]] = []
        if paso.get("thinking"):
            contenido.append(
                {"type": "thinking", "thinking": paso["thinking"], "signature": "falso"}
            )
        if paso.get("texto"):
            contenido.append({"type": "text", "text": paso["texto"], "citations": None})
        stop = paso.get("stop_reason", "end_turn")
        with self._cerrojo:
            self._n_msg += 1
            ident = f"msg_falso_{self._n_msg}"
            for h in paso.get("herramientas", []):
                self._n_tool += 1
                contenido.append(
                    {
                        "type": "tool_use",
                        "id": h.get("id") or f"toolu_falso_{self._n_tool}",
                        "name": h["name"],
                        "input": copy.deepcopy(h.get("input", {})),
                    }
                )
        if paso.get("herramientas"):
            stop = "tool_use"
        if stop == "pause_turn" and not contenido:
            contenido.append(
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_falso",
                    "name": "web_search",
                    "input": {},
                }
            )
        uso = {
            "input_tokens": 100 + 10 * len(mensajes),
            "output_tokens": 50,
            "cache_creation_input_tokens": 0 if repetido else 2000,
            "cache_read_input_tokens": 2000 if repetido else 0,
        }
        uso.update(paso.get("uso", {}))
        return RespuestaLLM(
            id=ident,
            modelo=paso.get("modelo_servido", modelo),
            stop_reason=stop,
            stop_categoria=paso.get("categoria") if stop == "refusal" else None,
            contenido=contenido,
            uso=uso,
            request_id=f"req_falso_{self._n_msg}",
            duracion_ms=1,
        )


# ---- Modo demo ---------------------------------------------------------------------------------
_MENSAJE = re.compile(r"<mensaje_cliente [^>]*>(.*?)</mensaje_cliente>", re.DOTALL)


def _textos_ultimo_user(mensajes: list[dict[str, Any]]) -> list[str]:
    for m in reversed(mensajes):
        if m["role"] == "user":
            return [
                b["text"]
                for b in m["content"]
                if b.get("type") == "text" and isinstance(b.get("text"), str)
            ]
    return []


def _resultados_ultimo_user(mensajes: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(herramienta, resultado) del último `user` si trae `tool_result`."""
    nombres: dict[str, str] = {}
    ultimo_user: dict[str, Any] | None = None
    for m in mensajes:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    nombres[b["id"]] = b["name"]
        elif m["role"] == "user":
            ultimo_user = m
    salida: list[tuple[str, dict[str, Any]]] = []
    if ultimo_user is not None:
        for b in ultimo_user["content"]:
            if b.get("type") == "tool_result":
                try:
                    datos = json.loads(b["content"])
                except (ValueError, TypeError):
                    datos = {}
                salida.append((nombres.get(b["tool_use_id"], ""), datos))
    return salida


def paso_demo(mensajes: list[dict[str, Any]]) -> PasoGuion:
    """Comportamiento determinista para probar a mano desde el simulador (fase-2c.md §4.2)."""
    todo = json.dumps(mensajes, ensure_ascii=False)
    verificada = '"verificada":true' in todo.replace(" ", "")
    cobranza = "Tipo de campaña: cobranza" in todo
    for herramienta, datos in _resultados_ultimo_user(mensajes):
        if herramienta == "verificar_identidad":
            if datos.get("verificada") and cobranza:
                return {"herramientas": [{"name": "consultar_obligacion", "input": {}}]}
            if datos.get("verificada"):
                return {"texto": "Gracias, ya verifiqué su identidad. ¿En qué le puedo ayudar?"}
            return {"texto": "No pude verificar ese número. ¿Puede escribirlo de nuevo?"}
        if herramienta == "consultar_obligacion" and "obligacion" in datos:
            mora = datos["obligacion"].get("saldo_mora")
            if mora is not None:
                return {"texto": f"Su saldo en mora es de {formatear_monto(Decimal(mora))}."}
            return {"texto": "Entendido. ¿En qué más le puedo ayudar?"}
        if herramienta == "derivar_a_humano":
            return {"texto": "Un asesor continuará la conversación por este medio."}
        return {"texto": "Entendido. ¿En qué más le puedo ayudar?"}
    texto = " ".join(m for t in _textos_ultimo_user(mensajes) for m in _MENSAJE.findall(t))
    if "asesor" in texto.lower():
        return {
            "herramientas": [
                {
                    "name": "derivar_a_humano",
                    "input": {
                        "motivo": "solicitud_cliente",
                        "resumen": "El cliente pidió hablar con un asesor.",
                    },
                }
            ]
        }
    documento = re.search(r"\d[\d.\s]{4,}\d", texto)
    if documento and 6 <= len(re.sub(r"\D", "", documento.group(0))) <= 12:
        return {
            "herramientas": [
                {
                    "name": "verificar_identidad",
                    "input": {"numero_documento": re.sub(r"\D", "", documento.group(0))},
                }
            ]
        }
    if not verificada:
        return {
            "texto": (
                "Hola, soy el asistente virtual. Para continuar, escríbame su número de documento."
            )
        }
    return {"texto": "Entendido. ¿En qué más le puedo ayudar?"}
