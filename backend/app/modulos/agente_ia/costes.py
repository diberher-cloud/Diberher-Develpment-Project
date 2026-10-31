"""Coste de una llamada al modelo (fase-2c.md §4.11). Módulo PURO."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

SEIS_DECIMALES = Decimal("0.000001")
MILLON = Decimal(1_000_000)


def costo_usd(
    uso: dict[str, int],
    precios: dict[str, float],
    ttl: Literal["5m", "1h"] = "5m",
) -> Decimal:
    """USD de una respuesta: (entrada·in + salida·out + escritura_ttl·cache_w + lectura·cache_r)
    / 1e6 con los precios (USD por millón) del modelo servido, a 6 decimales."""
    escritura = precios["cache_escritura_1h" if ttl == "1h" else "cache_escritura_5m"]
    total = (
        Decimal(uso.get("input_tokens", 0)) * Decimal(str(precios["entrada"]))
        + Decimal(uso.get("output_tokens", 0)) * Decimal(str(precios["salida"]))
        + Decimal(uso.get("cache_creation_input_tokens", 0)) * Decimal(str(escritura))
        + Decimal(uso.get("cache_read_input_tokens", 0)) * Decimal(str(precios["cache_lectura"]))
    ) / MILLON
    return total.quantize(SEIS_DECIMALES, rounding=ROUND_HALF_UP)
