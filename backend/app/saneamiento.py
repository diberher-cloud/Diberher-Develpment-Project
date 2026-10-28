"""Texto libre hostil: NUL (PostgreSQL lo rechaza en `text`) y sustitutos Unicode sueltos
(no son UTF-8 válido y rompen el driver en SQLite y PostgreSQL).

- En la API, la dependencia `rechazar_texto_hostil` (aplicada a todo `/api/v1`) responde
  `422 VALIDACION` indicando el campo del JSON o del query.
- En los webhooks de Twilio (que reintentan ante un 5xx) se sanea con `limpiar` y se procesa.
"""

import json
from typing import Any

from starlette.requests import HTTPConnection, Request

from app.errores import ErrorApp, detalle

_REEMPLAZO = "�"
MENSAJE = "No puede contener caracteres nulos ni sustitutos Unicode inválidos."
_RUTAS_EXENTAS = ("/whatsapp/webhooks/", "/telefonia/twiml/", "/telefonia/webhooks/")


def es_hostil(texto: str) -> bool:
    return "\x00" in texto or any("\ud800" <= c <= "\udfff" for c in texto)


def limpiar(texto: str) -> str:
    """Elimina NUL y sustituye los sustitutos sueltos por U+FFFD."""
    if not es_hostil(texto):
        return texto
    return "".join(_REEMPLAZO if "\ud800" <= c <= "\udfff" else c for c in texto if c != "\x00")


def _buscar(valor: Any, ruta: str) -> str | None:
    """Ruta (con puntos) del primer texto hostil, o None."""
    if isinstance(valor, str):
        return ruta if es_hostil(valor) else None
    if isinstance(valor, dict):
        for clave, v in valor.items():
            if isinstance(clave, str) and es_hostil(clave):
                return ruta or "(clave)"
            hallado = _buscar(v, f"{ruta}.{clave}" if ruta else str(clave))
            if hallado is not None:
                return hallado
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            hallado = _buscar(v, f"{ruta}.{i}" if ruta else str(i))
            if hallado is not None:
                return hallado
    return None


async def rechazar_texto_hostil(conexion: HTTPConnection) -> None:
    """Dependencia global: 422 `VALIDACION` si el JSON o el query traen texto hostil."""
    if not isinstance(conexion, Request):  # WebSocket
        return
    if any(parte in conexion.url.path for parte in _RUTAS_EXENTAS):
        return
    for clave, valor in conexion.query_params.multi_items():
        if es_hostil(clave) or es_hostil(valor):
            raise _error(clave)
    if "json" not in conexion.headers.get("content-type", "").lower():
        return
    cuerpo = await conexion.body()
    if not cuerpo:
        return
    try:
        datos = json.loads(cuerpo)
    except ValueError:  # JSON inválido: lo informa la validación normal
        return
    campo = _buscar(datos, "")
    if campo is not None:
        raise _error(campo or None)


def _error(campo: str | None) -> ErrorApp:
    return ErrorApp(
        422, "VALIDACION", "Los datos enviados no son válidos.", [detalle(campo, MENSAJE)]
    )
