"""Detección DETERMINISTA de opt-out por texto (ADR-0019 §5). Módulo puro.

Coincidencia EXACTA tras normalizar; nunca por subcadena. "cancelar", "no" y "salir" no están en
las listas a propósito ("cancelar" en Colombia significa pagar).
"""

import re
import unicodedata
from typing import Literal

AlcanceOptOut = Literal["whatsapp", "todos"]
MAX_CARACTERES = 80

FRASES_WHATSAPP = (
    "stop", "parar", "detener", "baja", "dar de baja", "darme de baja", "de baja", "unsubscribe",
    "no me escriban", "no me escriban mas", "no me escriba mas", "no escriban mas",
    "no mas mensajes", "no quiero mas mensajes", "no quiero recibir mas mensajes",
    "no me envien mas mensajes", "no envien mas mensajes", "dejen de escribirme",
    "no me vuelvan a escribir",
)  # fmt: skip
FRASES_TODOS = (
    "no me contacten", "no me contacten mas", "no me vuelvan a contactar",
    "no vuelvan a contactarme", "no quiero que me contacten", "no me llamen ni me escriban",
    "no me llamen ni me escriban mas",
)  # fmt: skip

_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")
# Ordenados de mayor a menor longitud: "buenas tardes" antes que "buenas".
_PREFIJOS = tuple(
    sorted(
        ("por favor", "porfa", "porfavor", "hola", "buenas", "buenos dias", "buenas tardes",
         "buenas noches"),
        key=len,
        reverse=True,
    )
)  # fmt: skip
_SUFIJOS = tuple(sorted(("por favor", "porfa", "gracias", "muchas gracias"), key=len, reverse=True))


def _base(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return _NO_ALFANUMERICO.sub(" ", sin_marcas.lower()).strip()


def normalizar(texto: str) -> str:
    """Sin tildes, signos ni emojis; minúsculas; sin cortesías al inicio ni al final."""
    t = _base(texto)
    cambio = True
    while cambio and t:
        cambio = False
        for prefijo in _PREFIJOS:
            if t == prefijo:
                return ""
            if t.startswith(prefijo + " "):
                t = t[len(prefijo) :].strip()
                cambio = True
                break
        if cambio:
            continue
        for sufijo in _SUFIJOS:
            if t.endswith(" " + sufijo):
                t = t[: -len(sufijo)].strip()
                cambio = True
                break
    return t


def cargar_frases(crudo: str, por_defecto: tuple[str, ...]) -> frozenset[str]:
    """Frases separadas por `|` (normalizadas); vacío = lista por defecto."""
    if crudo.strip():
        frases = {normalizar(f) for f in crudo.split("|")}
        return frozenset(f for f in frases if f)
    return frozenset(normalizar(f) for f in por_defecto)


def clasificar(
    texto: str | None,
    boton_payload: str | None,
    frases_whatsapp: frozenset[str],
    frases_todos: frozenset[str],
    payload_baja: str,
) -> AlcanceOptOut | None:
    if boton_payload is not None and boton_payload == payload_baja:
        return "whatsapp"
    if texto is None or len(texto) > MAX_CARACTERES:
        return None
    normalizado = normalizar(texto)
    if not normalizado:
        return None
    if normalizado in frases_todos:
        return "todos"
    if normalizado in frases_whatsapp:
        return "whatsapp"
    return None
