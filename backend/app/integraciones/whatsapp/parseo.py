"""Parseo PURO de los formularios de Twilio Messaging (compartido por Twilio y el falso)."""

import re
from collections.abc import Mapping
from typing import Literal

from app.integraciones.whatsapp.proveedor import EstadoMensaje, MediaEntrante, MensajeEntrante

PREFIJO = "whatsapp:"
MAX_TEXTO = 4096
MAX_MEDIA = 10
_E164 = re.compile(r"\+[1-9]\d{7,14}")
_MAPA_ESTADO: dict[str, Literal["enviado", "entregado", "leido", "fallido"]] = {
    "accepted": "enviado",
    "scheduled": "enviado",
    "queued": "enviado",
    "sending": "enviado",
    "sent": "enviado",
    "delivered": "entregado",
    "read": "leido",
    "failed": "fallido",
    "undelivered": "fallido",
    "canceled": "fallido",
}


def numero_whatsapp(valor: str | None) -> str | None:
    """`whatsapp:+57...` → `+57...`; None si no tiene el prefijo o no es E.164."""
    if not valor or not valor.startswith(PREFIJO):
        return None
    numero = valor[len(PREFIJO) :].strip()
    return numero if _E164.fullmatch(numero) else None


def tipo_contenido_limpio(valor: str | None) -> str:
    """Minúsculas y sin parámetros (`audio/ogg; codecs=opus` → `audio/ogg`)."""
    return (valor or "").split(";", 1)[0].strip().lower()[:100]


def _opcional(valor: str | None, maximo: int) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    return valor[:maximo] if valor else None


def parsear_entrante(params: Mapping[str, str]) -> MensajeEntrante | None:
    sid = (params.get("MessageSid") or "").strip()
    cliente = numero_whatsapp(params.get("From"))
    empresa = numero_whatsapp(params.get("To"))
    if not sid or len(sid) > 64 or cliente is None or empresa is None:
        return None
    crudo = (params.get("NumMedia") or "0").strip()
    if not crudo.isascii() or not crudo.isdigit() or int(crudo) > MAX_MEDIA:
        return None
    media = []
    for i in range(int(crudo)):
        url = (params.get(f"MediaUrl{i}") or "").strip()
        if url:
            media.append(
                MediaEntrante(
                    i, url[:500], tipo_contenido_limpio(params.get(f"MediaContentType{i}"))
                )
            )
    cuerpo = params.get("Body")
    return MensajeEntrante(
        proveedor_id=sid,
        numero_cliente=cliente,
        numero_empresa=empresa,
        cuenta=_opcional(params.get("AccountSid"), 64),
        texto=cuerpo[:MAX_TEXTO] if cuerpo and cuerpo.strip() else None,
        nombre_perfil=_opcional(params.get("ProfileName"), 100),
        media=tuple(media),
        boton_payload=_opcional(params.get("ButtonPayload"), 256),
        boton_texto=_opcional(params.get("ButtonText"), 256),
        respuesta_a=_opcional(params.get("OriginalRepliedMessageSid"), 64),
    )


def parsear_estado(params: Mapping[str, str]) -> EstadoMensaje | None:
    sid = (params.get("MessageSid") or "").strip()
    crudo = (params.get("MessageStatus") or "").strip().lower()
    if not sid or len(sid) > 64 or not crudo:
        return None
    return EstadoMensaje(
        proveedor_id=sid,
        estado_proveedor=crudo[:20],
        estado=_MAPA_ESTADO.get(crudo),
        error_codigo=_opcional(params.get("ErrorCode"), 30),
    )
