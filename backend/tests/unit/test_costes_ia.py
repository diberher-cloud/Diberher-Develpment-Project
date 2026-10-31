from decimal import Decimal

from app.config import PRECIOS_IA_POR_DEFECTO
from app.modulos.agente_ia.costes import costo_usd


def test_costo_con_precios_por_defecto():
    uso = {
        "input_tokens": 1000, "output_tokens": 500,
        "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 10000,
    }  # fmt: skip
    p = PRECIOS_IA_POR_DEFECTO["claude-opus-5-5"]
    # (1000*4 + 500*20 + 2000*5 + 10000*0.4) / 1e6
    assert costo_usd(uso, p) == Decimal("0.028000")
    assert costo_usd(uso, p, "1h") == Decimal("0.034000")
    assert costo_usd({}, p) == Decimal("0.000000")
