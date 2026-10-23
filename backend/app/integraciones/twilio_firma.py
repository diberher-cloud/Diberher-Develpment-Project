"""Firma de webhooks de Twilio (`X-Twilio-Signature`). Módulo PURO (ADR-0013).

Algoritmo: base64(HMAC-SHA1(auth_token, url + concat(clave + valor, claves ordenadas))).
`url` es la URL pública EXACTA con la que Twilio hizo la petición (incluye la query).
"""

import base64
import hashlib
import hmac
from collections.abc import Mapping, Sequence


def firma_twilio(url: str, params: Mapping[str, str | Sequence[str]], auth_token: str) -> str:
    texto = url
    for clave in sorted(params):
        valor = params[clave]
        valores = [valor] if isinstance(valor, str) else sorted(valor)
        for v in valores:
            texto += clave + v
    digest = hmac.new(auth_token.encode(), texto.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def validar_firma(
    url: str, params: Mapping[str, str | Sequence[str]], firma: str | None, auth_token: str
) -> bool:
    """Compara en tiempo constante; firma ausente o vacía => False."""
    if not firma or not auth_token:
        return False
    esperada = firma_twilio(url, params, auth_token)
    return hmac.compare_digest(esperada.encode(), firma.encode())
