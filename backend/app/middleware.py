"""Middleware ASGI: límite de tamaño del cuerpo antes de autenticar y captura de errores.

- Responde 413 ARCHIVO_DEMASIADO_GRANDE si Content-Length supera IMPORTACION_MAX_BYTES + 1 MiB
  de margen, o si los bytes realmente leídos lo superan (transfer-encoding chunked).
- Captura excepciones no controladas y responde 500 sin que se propaguen a uvicorn, cuyo
  registro incluiría str(exc) (puede contener datos personales en errores de BD).
"""

import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.errores import registrar_error_interno

MARGEN_BYTES = 1024 * 1024
logger = logging.getLogger("app")


class _CuerpoExcedido(Exception):
    pass


def _respuesta(status: int, codigo: str, mensaje: str) -> tuple[Message, Message]:
    cuerpo = json.dumps({"error": {"codigo": codigo, "mensaje": mensaje, "detalles": []}}).encode()
    inicio = {
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(cuerpo)).encode()),
        ],
    }
    return inicio, {"type": "http.response.body", "body": cuerpo}


class ProteccionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limite = get_settings().importacion_max_bytes + MARGEN_BYTES
        demasiado = ("ARCHIVO_DEMASIADO_GRANDE", "El cuerpo de la petición es demasiado grande.")

        for nombre, valor in scope.get("headers", []):
            if nombre == b"content-length":
                try:
                    excede = int(valor) > limite
                except ValueError:
                    excede = False
                if excede:
                    for msg in _respuesta(413, *demasiado):
                        await send(msg)
                    return

        leidos = 0
        iniciada = False
        cortado = False

        async def receive_limitado() -> Message:
            nonlocal leidos
            msg = await receive()
            if msg["type"] == "http.request":
                leidos += len(msg.get("body", b""))
                if leidos > limite:
                    await cortar()
                    raise _CuerpoExcedido
            return msg

        async def cortar() -> None:
            # Responde 413 de inmediato: la aplicación puede convertir la excepción en un 400.
            nonlocal iniciada, cortado
            if not iniciada:
                iniciada = True
                for msg in _respuesta(413, *demasiado):
                    await send(msg)
            cortado = True

        async def send_vigilado(msg: Message) -> None:
            nonlocal iniciada
            if cortado:
                return
            if msg["type"] == "http.response.start":
                iniciada = True
            await send(msg)

        try:
            await self.app(scope, receive_limitado, send_vigilado)
        except _CuerpoExcedido:
            pass
        except Exception as exc:
            registrar_error_interno(exc)
            if not iniciada:
                for msg in _respuesta(500, "ERROR_INTERNO", "Error interno del servidor."):
                    await send(msg)
