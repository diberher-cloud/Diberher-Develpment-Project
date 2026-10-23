"""Error común de la API (§4.1) y manejadores globales."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")


class ErrorApp(Exception):
    def __init__(
        self,
        status: int,
        codigo: str,
        mensaje: str,
        detalles: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []


def detalle(campo: str | None, mensaje: str) -> dict[str, Any]:
    return {"campo": campo, "mensaje": mensaje}


def error_validacion(campo: str | None, mensaje: str) -> ErrorApp:
    return ErrorApp(
        422, "VALIDACION", "Los datos enviados no son válidos.", [detalle(campo, mensaje)]
    )


def respuesta_error(
    status: int, codigo: str, mensaje: str, detalles: list[dict[str, Any]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}},
    )


_MENSAJES_TIPO = {
    "extra_forbidden": "Campo no permitido o no editable.",
    "missing": "Campo obligatorio.",
}


def detalles_desde_pydantic(errores: list[Any], prefijo: str | None = None) -> list[dict[str, Any]]:
    """Convierte errores de Pydantic en `detalles` (campo con puntos, sin 'body'/'query'/'path')."""
    resultado = []
    for err in errores:
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "form")]
        if prefijo:
            loc = [prefijo, *loc]
        msg = _MENSAJES_TIPO.get(err.get("type", ""), str(err.get("msg", "Valor inválido.")))
        msg = msg.removeprefix("Value error, ")
        resultado.append(detalle(".".join(loc) or None, msg))
    return resultado


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorApp)
    async def _app(_req: Request, exc: ErrorApp) -> JSONResponse:
        return respuesta_error(exc.status, exc.codigo, exc.mensaje, exc.detalles)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_req: Request, exc: RequestValidationError) -> JSONResponse:
        return respuesta_error(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            detalles_desde_pydantic(list(exc.errors())),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigos = {
            401: ("NO_AUTENTICADO", "No autenticado."),
            403: ("PERMISO_DENEGADO", "No tiene permiso para esta operación."),
            404: ("NO_ENCONTRADO", "Recurso no encontrado."),
            405: ("METODO_NO_PERMITIDO", "Método no permitido."),
        }
        codigo, mensaje = codigos.get(exc.status_code, ("ERROR_HTTP", "Error en la petición."))
        return respuesta_error(exc.status_code, codigo, mensaje)

    @app.exception_handler(Exception)
    async def _interno(_req: Request, exc: Exception) -> JSONResponse:
        logger.error("Error no controlado: %s", type(exc).__name__, exc_info=exc)
        return respuesta_error(500, "ERROR_INTERNO", "Error interno del servidor.")
