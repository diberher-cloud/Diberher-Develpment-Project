"""Detección DETERMINISTA de opt-out por texto (ADR-0019 §5). Módulo puro.

Coincidencia EXACTA tras normalizar; nunca por subcadena. "cancelar", "no" y "salir" no están en
las listas a propósito ("cancelar" en Colombia significa pagar).
"""

import re
import unicodedata
from typing import Literal

AlcanceOptOut = Literal["whatsapp", "todos", "voz"]
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

# Patrones sobre el texto YA normalizado (minúsculas, sin tildes ni signos), con coincidencia
# COMPLETA (`fullmatch`): "no me escriban más tarde" o "no me contacten hasta el lunes"
# no coinciden.
_DEJAR = r"(?:escriban|escribas|escriba|manden|mandes|envien|envies|envie|mande)"
_BAJA = r"(?:que me (?:den|de|dan) de baja|darme de baja|dar de baja)"
_PODER = r"(?:pueden|podrian|podria|puede|podrias|puedes|pueda)"
_LISTA = r"(?: de (?:mensajes|difusion|contactos))?"
_PATRONES_WHATSAPP = tuple(
    re.compile(p)
    for p in (
        r"(?:ya )?no me contacten(?: (?:nunca )?mas)? por (?:whatsapp|este medio|este chat|aqui)",
        rf"(?:ya )?no me {_DEJAR}(?: (?:nunca|ya))?(?: mas)?(?: mensajes| msj| whatsapp)?"
        r"(?: mas)?(?: ya)?",
        rf"(?:quiero|deseo|necesito|solicito|quisiera) {_BAJA}",
        rf"(?:me )?{_PODER} (?:me )?dar(?:me)? de baja",
        r"(?:por favor )?(?:den|dar|denme|deme|dame) de baja",
        r"stop ?all",
        rf"(?:por favor )?(?:saquenme|sacame|saqueme|sacarme) de la lista{_LISTA}",
        r"(?:quiero|deseo|necesito|quisiera) (?:salir|que me saquen|sacarme) de la lista",
    )
)
_MEDIO = r"(?:ningun medio|ningun canal|ninguna via|ningun lado|ninguna parte)"
_PATRONES_TODOS = tuple(
    re.compile(p)
    for p in (
        rf"(?:ya )?no me contacten(?: (?:nunca )?mas)? por {_MEDIO}",
        rf"por {_MEDIO} no me contacten(?: mas)?",
        r"(?:ya )?no me contacten(?: (?:nunca )?mas)?(?: ya)?",
        r"(?:ya )?no me vuelvan a contactar(?: nunca)?",
    )
)
_PATRONES_VOZ = tuple(
    re.compile(p)
    for p in (
        r"(?:ya )?no me llamen(?: (?:nunca )?mas)?(?: ya)?",
        r"(?:ya )?no me vuelvan a llamar(?: nunca)?",
        r"(?:ya )?no me llamen mas por telefono",
    )
)
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
    usar_patrones: bool = True,
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
    if usar_patrones:
        if any(p.fullmatch(normalizado) for p in _PATRONES_TODOS):
            return "todos"
        if any(p.fullmatch(normalizado) for p in _PATRONES_WHATSAPP):
            return "whatsapp"
    # "No me llamen" es opt-out de voz aunque haya listas de WhatsApp configuradas.
    if any(p.fullmatch(normalizado) for p in _PATRONES_VOZ):
        return "voz"
    return None


def normalizar_sin_cortesia(texto: str) -> str:
    """Normalización base (sin tildes, signos ni mayúsculas) SIN quitar fórmulas de cortesía.
    La usan las citas de la IA (fase-2c.md §4.6)."""
    return _base(texto)
