"""Renderizado PURO del guion de la campaña (§4.4)."""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


def formatear_monto(valor: Decimal | None) -> str:
    """`$ 1.500.000`; con decimales distintos de 00: `$ 250.000,50`."""
    if valor is None:
        return ""
    entero, _, decimales = f"{valor:.2f}".partition(".")
    signo = "-" if entero.startswith("-") else ""
    entero = entero.lstrip("-")
    miles = f"{int(entero):,}".replace(",", ".")
    sufijo = "" if decimales == "00" else f",{decimales}"
    return f"$ {signo}{miles}{sufijo}"


def formatear_fecha(valor: date | None) -> str:
    return "" if valor is None else valor.strftime("%d/%m/%Y")


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return formatear_monto(valor)
    if isinstance(valor, date):
        return formatear_fecha(valor)
    return str(valor)


def renderizar_guion(plantilla: str | None, contexto: Mapping[str, Any]) -> str | None:
    """Sustituye `{{variable}}` (espacios tolerados). Variable desconocida: se deja literal;
    valor nulo: cadena vacía; `{{datos.<clave>}}` toma de `contexto["datos"]`."""
    if plantilla is None:
        return None

    def _sustituir(m: re.Match[str]) -> str:
        nombre = m.group(1)
        if nombre.startswith("datos."):
            datos = contexto.get("datos") or {}
            clave = nombre[len("datos.") :]
            return _texto(datos[clave]) if clave in datos else m.group(0)
        if nombre == "datos" or nombre not in contexto:
            return m.group(0)
        return _texto(contexto[nombre])

    return _VARIABLE.sub(_sustituir, plantilla)
