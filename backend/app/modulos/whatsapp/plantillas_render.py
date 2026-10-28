"""Variables y renderizado de plantillas. Módulo PURO."""

import re
from collections.abc import Mapping

# Lista blanca de campos con valor calculado en el servidor (nunca montos ni documentos).
CAMPOS = ("primer_nombre", "empresa", "agente", "producto")
_VARIABLE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _orden(clave: str) -> tuple[int, int, str]:
    return (0, int(clave), clave) if clave.isdigit() else (1, 0, clave)


def variables_de(cuerpo: str) -> list[str]:
    """Claves distintas de `{{n}}` en el cuerpo, ordenadas numéricamente."""
    return sorted(set(_VARIABLE.findall(cuerpo)), key=_orden)


def renderizar(cuerpo: str, valores: Mapping[str, str]) -> str:
    """Sustituye `{{n}}` (tolera espacios); deja literal lo desconocido."""
    return _VARIABLE.sub(lambda m: valores.get(m.group(1), m.group(0)), cuerpo)


def limpiar_valor(valor: str | None) -> str:
    """Una sola línea y espacios colapsados (WhatsApp rechaza saltos de línea en variables)."""
    return " ".join((valor or "").split())


def primera_palabra(texto: str | None) -> str:
    palabras = (texto or "").split()
    return palabras[0].capitalize() if palabras else ""
