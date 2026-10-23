"""Festivos de Colombia (Ley 51 de 1983, Ley Emiliani). Módulo puro."""

from datetime import date, timedelta

ANIO_MIN = 1984
ANIO_MAX = 2100

_FIJOS = (
    (1, 1, "Año Nuevo"),
    (5, 1, "Día del Trabajo"),
    (7, 20, "Independencia de Colombia"),
    (8, 7, "Batalla de Boyacá"),
    (12, 8, "Inmaculada Concepción"),
    (12, 25, "Navidad"),
)
_TRASLADABLES = (
    (1, 6, "Reyes Magos"),
    (3, 19, "San José"),
    (6, 29, "San Pedro y San Pablo"),
    (8, 15, "Asunción de la Virgen"),
    (10, 12, "Día de la Raza"),
    (11, 1, "Todos los Santos"),
    (11, 11, "Independencia de Cartagena"),
)
_PASCUA = (
    (-3, "Jueves Santo"),
    (-2, "Viernes Santo"),
    (43, "Ascensión del Señor"),
    (64, "Corpus Christi"),
    (71, "Sagrado Corazón"),
)


def domingo_de_pascua(anio: int) -> date:
    """Algoritmo gregoriano anónimo (Meeus/Jones/Butcher)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes, dia = divmod(h + l_ - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _siguiente_lunes(fecha: date) -> date:
    return fecha + timedelta(days=(7 - fecha.weekday()) % 7)


def festivos_colombia(anio: int) -> dict[date, str]:
    if not ANIO_MIN <= anio <= ANIO_MAX:
        raise ValueError(f"El año debe estar entre {ANIO_MIN} y {ANIO_MAX}.")
    nombres: dict[date, list[str]] = {}

    def agregar(fecha: date, nombre: str) -> None:
        nombres.setdefault(fecha, []).append(nombre)

    for mes, dia, nombre in _FIJOS:
        agregar(date(anio, mes, dia), nombre)
    for mes, dia, nombre in _TRASLADABLES:
        agregar(_siguiente_lunes(date(anio, mes, dia)), nombre)
    pascua = domingo_de_pascua(anio)
    for delta, nombre in _PASCUA:
        agregar(pascua + timedelta(days=delta), nombre)
    return {f: "; ".join(sorted(n)) for f, n in sorted(nombres.items())}
