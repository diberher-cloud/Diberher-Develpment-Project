import copy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modulos.cumplimiento.festivos import festivos_colombia
from app.modulos.cumplimiento.motor import evaluar_horario, proxima_ventana
from app.modulos.cumplimiento.politica import PoliticaCumplimiento, politica_por_defecto

BOG = timezone(timedelta(hours=-5))
FESTIVOS = festivos_colombia(2026)
POLITICA = PoliticaCumplimiento.model_validate(politica_por_defecto())


def ev(texto, politica=POLITICA, festivos=FESTIVOS):
    return evaluar_horario(datetime.fromisoformat(texto), politica, festivos)


def prox(r):
    return r.proxima_ventana_inicio.isoformat() if r.proxima_ventana_inicio else None


def test_antes_de_apertura():
    r = ev("2026-10-23T06:59:00-05:00")
    assert not r.permitido
    assert [m.codigo for m in r.motivos] == ["FUERA_DE_FRANJA"]
    assert prox(r) == "2026-10-23T07:00:00-05:00"


@pytest.mark.parametrize("hora", ["07:00:00", "18:59:59"])
def test_dentro(hora):
    r = ev(f"2026-10-23T{hora}-05:00")
    assert r.permitido and r.motivos == () and r.proxima_ventana_inicio is None


def test_cierre_viernes_pasa_a_sabado():
    r = ev("2026-10-23T19:00:00-05:00")
    assert not r.permitido
    assert prox(r) == "2026-10-24T08:00:00-05:00"


def test_sabado():
    assert ev("2026-10-24T14:59:00-05:00").permitido
    r = ev("2026-10-24T15:00:00-05:00")
    assert not r.permitido and prox(r) == "2026-10-26T07:00:00-05:00"


def test_domingo():
    r = ev("2026-10-25T10:00:00-05:00")
    assert [m.codigo for m in r.motivos] == ["DIA_SIN_FRANJA"]
    assert prox(r) == "2026-10-26T07:00:00-05:00"


def test_festivo():
    r = ev("2026-11-02T10:00:00-05:00")
    assert [m.codigo for m in r.motivos] == ["FESTIVO"]
    assert r.motivos[0].mensaje == "2026-11-02 es festivo (Todos los Santos)."
    assert prox(r) == "2026-11-03T07:00:00-05:00"


def test_semana_santa_intermedia():
    r = ev("2026-04-02T10:00:00-05:00")
    assert [m.codigo for m in r.motivos] == ["FESTIVO"]
    assert prox(r) == "2026-04-04T08:00:00-05:00"


def test_festivo_en_domingo_devuelve_ambos_motivos():
    r = ev("2025-07-20T10:00:00-05:00", festivos=festivos_colombia(2025))
    assert [m.codigo for m in r.motivos] == ["FESTIVO", "DIA_SIN_FRANJA"]


def test_utc_equivale_a_bogota():
    r = ev("2026-10-23T12:00:00+00:00")
    assert r.permitido
    assert r.momento_local.isoformat() == "2026-10-23T07:00:00-05:00"
    assert evaluar_horario(datetime(2026, 10, 23, 12, tzinfo=UTC), POLITICA, FESTIVOS).permitido


def test_ingenuo_lanza_valueerror():
    with pytest.raises(ValueError):
        evaluar_horario(datetime(2026, 10, 23, 10), POLITICA, FESTIVOS)
    with pytest.raises(ValueError):
        proxima_ventana(datetime(2026, 10, 23, 10), POLITICA, FESTIVOS)


def test_permitir_festivos():
    cfg = politica_por_defecto() | {"permitir_festivos": True}
    p = PoliticaCumplimiento.model_validate(cfg)
    assert ev("2026-11-02T10:00:00-05:00", p).permitido


def test_dos_franjas():
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["viernes"] = [
        {"inicio": "07:00", "fin": "12:00"},
        {"inicio": "14:00", "fin": "19:00"},
    ]
    p = PoliticaCumplimiento.model_validate(cfg)
    r = ev("2026-10-23T13:00:00-05:00", p)
    assert not r.permitido and prox(r) == "2026-10-23T14:00:00-05:00"


def test_sin_ventanas():
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"] = {d: [] for d in cfg["franjas"]}
    p = PoliticaCumplimiento.model_validate(cfg)
    r = ev("2026-10-23T10:00:00-05:00", p)
    assert not r.permitido and r.proxima_ventana_inicio is None


def test_proxima_ventana_si_ya_permitido_devuelve_el_momento():
    m = datetime.fromisoformat("2026-10-23T10:00:00-05:00")
    assert proxima_ventana(m, POLITICA, FESTIVOS) == m


def test_motor_extremos_lanza_valueerror_no_overflow():
    for m in (datetime(9999, 12, 31, 23, 0, tzinfo=BOG), datetime(1, 1, 1, tzinfo=UTC)):
        with pytest.raises(ValueError):
            evaluar_horario(m, POLITICA, {})
