"""Validación común de webhooks de Twilio (voz y WhatsApp), ADR-0013 §1.

Se valida `X-Twilio-Signature` ANTES de cualquier otro procesamiento. URL firmada =
`PUBLIC_BASE_URL` + ruta + query original (nunca la URL que ve el servidor detrás de un proxy).
"""

import logging
from collections.abc import Callable, Mapping, Sequence

from fastapi import Request

from app.config import get_settings
from app.errores import ErrorApp

logger = logging.getLogger("app")

ValidadorFirma = Callable[[str, Mapping[str, str | Sequence[str]], str | None], bool]


async def validar_peticion_twilio(
    request: Request, validar_firma: ValidadorFirma
) -> dict[str, str]:
    """Valida la firma y devuelve los parámetros del formulario (primer valor de cada clave).

    Firma inválida o ausente → 403 `FIRMA_INVALIDA` (se registra solo la ruta, sin parámetros).
    """
    formulario = await request.form()
    multiples: dict[str, list[str]] = {}
    for clave, valor in formulario.multi_items():
        if isinstance(valor, str):
            multiples.setdefault(clave, []).append(valor)
    consulta = request.url.query
    url = get_settings().public_base_url + request.url.path + (f"?{consulta}" if consulta else "")
    firma = request.headers.get("X-Twilio-Signature")
    firmables: dict[str, str | Sequence[str]] = {
        k: v[0] if len(v) == 1 else v for k, v in multiples.items()
    }
    if not validar_firma(url, firmables, firma):
        logger.warning("Firma de Twilio inválida en %s", request.url.path)
        raise ErrorApp(403, "FIRMA_INVALIDA", "Firma inválida.")
    return {k: v[0] for k, v in multiples.items()}
