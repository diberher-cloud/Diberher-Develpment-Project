from datetime import date

import pytest

from app.modulos.cumplimiento.festivos import domingo_de_pascua, festivos_colombia

FESTIVOS_2026 = [
    (1, 1), (1, 12), (3, 23), (4, 2), (4, 3), (5, 1), (5, 18), (6, 8), (6, 15), (6, 29),
    (7, 20), (8, 7), (8, 17), (10, 12), (11, 2), (11, 16), (12, 8), (12, 25),
]  # fmt: skip
FESTIVOS_2025 = [
    (1, 1), (1, 6), (3, 24), (4, 17), (4, 18), (5, 1), (6, 2), (6, 23), (6, 30), (7, 20),
    (8, 7), (8, 18), (10, 13), (11, 3), (11, 17), (12, 8), (12, 25),
]  # fmt: skip


def test_2026():
    assert sorted(festivos_colombia(2026)) == [date(2026, m, d) for m, d in FESTIVOS_2026]
    assert festivos_colombia(2026)[date(2026, 11, 2)] == "Todos los Santos"


def test_2025_nombres_unidos():
    f = festivos_colombia(2025)
    assert sorted(f) == [date(2025, m, d) for m, d in FESTIVOS_2025]
    assert f[date(2025, 6, 30)] == "Sagrado Corazón; San Pedro y San Pablo"
    assert date(2025, 7, 20) in f  # domingo, no se traslada


def test_pascua():
    assert domingo_de_pascua(2026) == date(2026, 4, 5)
    assert domingo_de_pascua(2025) == date(2025, 4, 20)
    assert domingo_de_pascua(2000) == date(2000, 4, 23)


@pytest.mark.parametrize("anio", [1983, 2101])
def test_fuera_de_rango(anio):
    with pytest.raises(ValueError):
        festivos_colombia(anio)


def test_limites_validos():
    assert festivos_colombia(1984) and festivos_colombia(2100)
