"""Festivos de Colombia: fechas y nombres exactos 2025/2026 y propiedades para todo el rango."""

from datetime import date, timedelta

import pytest

from app.modulos.cumplimiento.festivos import (
    ANIO_MAX,
    ANIO_MIN,
    domingo_de_pascua,
    festivos_colombia,
)

NOMBRES_2026 = {
    date(2026, 1, 1): "Año Nuevo",
    date(2026, 1, 12): "Reyes Magos",
    date(2026, 3, 23): "San José",
    date(2026, 4, 2): "Jueves Santo",
    date(2026, 4, 3): "Viernes Santo",
    date(2026, 5, 1): "Día del Trabajo",
    date(2026, 5, 18): "Ascensión del Señor",
    date(2026, 6, 8): "Corpus Christi",
    date(2026, 6, 15): "Sagrado Corazón",
    date(2026, 6, 29): "San Pedro y San Pablo",
    date(2026, 7, 20): "Independencia de Colombia",
    date(2026, 8, 7): "Batalla de Boyacá",
    date(2026, 8, 17): "Asunción de la Virgen",
    date(2026, 10, 12): "Día de la Raza",
    date(2026, 11, 2): "Todos los Santos",
    date(2026, 11, 16): "Independencia de Cartagena",
    date(2026, 12, 8): "Inmaculada Concepción",
    date(2026, 12, 25): "Navidad",
}
NOMBRES_2025 = {
    date(2025, 1, 1): "Año Nuevo",
    date(2025, 1, 6): "Reyes Magos",
    date(2025, 3, 24): "San José",
    date(2025, 4, 17): "Jueves Santo",
    date(2025, 4, 18): "Viernes Santo",
    date(2025, 5, 1): "Día del Trabajo",
    date(2025, 6, 2): "Ascensión del Señor",
    date(2025, 6, 23): "Corpus Christi",
    date(2025, 6, 30): "Sagrado Corazón; San Pedro y San Pablo",
    date(2025, 7, 20): "Independencia de Colombia",
    date(2025, 8, 7): "Batalla de Boyacá",
    date(2025, 8, 18): "Asunción de la Virgen",
    date(2025, 10, 13): "Día de la Raza",
    date(2025, 11, 3): "Todos los Santos",
    date(2025, 11, 17): "Independencia de Cartagena",
    date(2025, 12, 8): "Inmaculada Concepción",
    date(2025, 12, 25): "Navidad",
}


def test_2026_fechas_y_nombres_exactos():
    assert festivos_colombia(2026) == NOMBRES_2026
    assert len(festivos_colombia(2026)) == 18


def test_2025_fechas_y_nombres_exactos():
    assert festivos_colombia(2025) == NOMBRES_2025
    assert len(festivos_colombia(2025)) == 17


def test_2025_coincidencia_de_dos_festivos_nombres_unidos_en_orden_alfabetico():
    nombre = festivos_colombia(2025)[date(2025, 6, 30)]
    partes = nombre.split("; ")
    assert partes == sorted(partes) and len(partes) == 2


@pytest.mark.parametrize(
    ("anio", "esperado"),
    [
        # Años de control (calendario oficial): 2024 (18 festivos), 2027 (18).
        (2024, [(1, 1), (1, 8), (3, 25), (3, 28), (3, 29), (5, 1), (5, 13), (6, 3), (6, 10),
                (7, 1), (7, 20), (8, 7), (8, 19), (10, 14), (11, 4), (11, 11), (12, 8), (12, 25)]),
        (2027, [(1, 1), (1, 11), (3, 22), (3, 25), (3, 26), (5, 1), (5, 10), (5, 31), (6, 7),
                (7, 5), (7, 20), (8, 7), (8, 16), (10, 18), (11, 1), (11, 15), (12, 8), (12, 25)]),
    ],
)  # fmt: skip
def test_anios_de_control(anio, esperado):
    assert sorted(festivos_colombia(anio)) == [date(anio, m, d) for m, d in esperado]


@pytest.mark.parametrize(
    ("anio", "pascua"),
    [(2024, date(2024, 3, 31)), (2027, date(2027, 3, 28)), (2028, date(2028, 4, 16)),
     (2030, date(2030, 4, 21)), (1984, date(1984, 4, 22)), (2100, date(2100, 3, 28))],
)  # fmt: skip
def test_pascua(anio, pascua):
    assert domingo_de_pascua(anio) == pascua


def test_propiedades_para_todo_el_rango_soportado():
    fijos = [(1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25)]
    trasladables = [(1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11)]
    for anio in range(ANIO_MIN, ANIO_MAX + 1):
        f = festivos_colombia(anio)
        assert all(d.year == anio for d in f)
        assert 16 <= len(f) <= 18, (anio, len(f))
        for m, d in fijos:  # nunca se trasladan
            assert date(anio, m, d) in f, (anio, m, d)
        for m, d in trasladables:
            original = date(anio, m, d)
            esperado = (
                original
                if original.weekday() == 0
                else original + timedelta(days=7 - original.weekday())
            )
            assert esperado in f, (anio, m, d)
            if original.weekday() != 0:
                assert original not in f or original in {date(anio, a, b) for a, b in fijos}
        pascua = domingo_de_pascua(anio)
        for delta in (-3, -2):  # Jueves y Viernes Santo
            assert pascua + timedelta(days=delta) in f
        for delta in (43, 64, 71):  # Ascensión, Corpus, Sagrado Corazón: siempre lunes
            d = pascua + timedelta(days=delta)
            assert d.weekday() == 0 and d in f
        # ningún festivo trasladable cae fuera de lunes
        mov = {date(anio, m, d) for m, d in fijos} | {
            pascua - timedelta(days=3),
            pascua - timedelta(days=2),
        }
        assert all(d.weekday() == 0 for d in f if d not in mov)


def test_cada_fecha_tiene_nombre_no_vacio_y_orden_estable():
    for anio in (2025, 2026, 2027, 2028):
        f = festivos_colombia(anio)
        assert all(n.strip() for n in f.values())
        assert list(f) == sorted(f)  # claves ordenadas por fecha
        assert festivos_colombia(anio) == f  # determinista


@pytest.mark.parametrize("anio", [1983, 2101, 0, -1])
def test_fuera_de_rango(anio):
    with pytest.raises(ValueError):
        festivos_colombia(anio)
