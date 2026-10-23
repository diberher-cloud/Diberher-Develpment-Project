"""Casos límite del motor de cumplimiento: bordes de franja, zonas horarias y traslados."""

import copy
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.modulos.cumplimiento.festivos import festivos_colombia
from app.modulos.cumplimiento.motor import evaluar_horario, proxima_ventana
from app.modulos.cumplimiento.politica import PoliticaCumplimiento, politica_por_defecto

BOG = timezone(timedelta(hours=-5))
F26 = festivos_colombia(2026)
POL = PoliticaCumplimiento.model_validate(politica_por_defecto())


def ev(texto, politica=POL, festivos=F26):
    return evaluar_horario(datetime.fromisoformat(texto), politica, festivos)


def prox(r):
    return r.proxima_ventana_inicio.isoformat() if r.proxima_ventana_inicio else None


def codigos(r):
    return [m.codigo for m in r.motivos]


# --- Bordes exactos de franja -------------------------------------------------------------


@pytest.mark.parametrize(
    ("momento", "permitido"),
    [
        ("2026-10-26T06:59:59.999999-05:00", False),  # lunes, 1 µs antes de abrir
        ("2026-10-26T07:00:00-05:00", True),
        ("2026-10-26T18:59:59.999999-05:00", True),
        ("2026-10-26T19:00:00-05:00", False),  # cierre exacto: excluido
        ("2026-10-26T19:00:00.000001-05:00", False),
        ("2026-10-24T07:59:59-05:00", False),  # sábado abre a las 08:00
        ("2026-10-24T08:00:00-05:00", True),
        ("2026-10-24T14:59:59.999999-05:00", True),
        ("2026-10-24T15:00:00-05:00", False),  # sábado cierra 15:00 exacto
        ("2026-10-24T15:00:00.000001-05:00", False),
        ("2026-10-24T00:00:00-05:00", False),
        ("2026-10-23T23:59:59-05:00", False),
    ],
)
def test_bordes(momento, permitido):
    assert ev(momento).permitido is permitido


def test_cierre_de_viernes_19_00_proxima_es_sabado_8_00():
    r = ev("2026-10-23T19:00:00-05:00")
    assert codigos(r) == ["FUERA_DE_FRANJA"]
    assert prox(r) == "2026-10-24T08:00:00-05:00"
    assert r.momento_local.isoformat() == "2026-10-23T19:00:00-05:00"


def test_cierre_de_sabado_15_00_proxima_es_lunes_7_00():
    r = ev("2026-10-24T15:00:00-05:00")
    assert codigos(r) == ["FUERA_DE_FRANJA"]
    assert prox(r) == "2026-10-26T07:00:00-05:00"


def test_proxima_ventana_antes_de_abrir_con_fracciones():
    r = ev("2026-10-23T06:59:59.500000-05:00")
    assert prox(r) == "2026-10-23T07:00:00-05:00"


def test_madrugada_de_sabado_proxima_es_el_mismo_sabado_8_00():
    assert prox(ev("2026-10-24T03:00:00-05:00")) == "2026-10-24T08:00:00-05:00"


def test_sabado_tarde_y_domingo_siguiente_salta_a_lunes():
    assert prox(ev("2026-10-24T20:00:00-05:00")) == "2026-10-26T07:00:00-05:00"
    assert prox(ev("2026-10-25T23:59:59-05:00")) == "2026-10-26T07:00:00-05:00"


# --- Zonas horarias de entrada ------------------------------------------------------------


@pytest.mark.parametrize(
    ("momento", "local", "permitido"),
    [
        ("2026-10-23T12:00:00Z", "2026-10-23T07:00:00-05:00", True),
        ("2026-10-23T11:59:59Z", "2026-10-23T06:59:59-05:00", False),
        ("2026-10-23T23:59:59Z", "2026-10-23T18:59:59-05:00", True),
        ("2026-10-24T00:00:00Z", "2026-10-23T19:00:00-05:00", False),  # cruza el día en UTC
        ("2026-10-24T00:00:00+00:00", "2026-10-23T19:00:00-05:00", False),
        ("2026-10-23T22:00:00+10:00", "2026-10-23T07:00:00-05:00", True),  # Australia
        ("2026-10-24T02:00:00+14:00", "2026-10-23T07:00:00-05:00", True),  # extremo +14
        ("2026-10-23T07:00:00-05:00", "2026-10-23T07:00:00-05:00", True),
        ("2026-10-23T03:59:59-08:00", "2026-10-23T06:59:59-05:00", False),  # Pacífico
        ("2026-10-23T08:00:00-04:00", "2026-10-23T07:00:00-05:00", True),
        ("2026-10-23T17:30:00+05:30", "2026-10-23T07:00:00-05:00", True),  # India (media hora)
    ],
)
def test_entrada_en_cualquier_zona_se_evalua_en_bogota(momento, local, permitido):
    r = ev(momento)
    assert r.momento_local.isoformat() == local
    assert r.permitido is permitido


def test_utc_que_cae_en_domingo_o_festivo_local():
    # 2026-11-03T03:00Z = lunes 2 de noviembre 22:00 en Bogotá (festivo, y fuera de franja)
    r = ev("2026-11-03T03:00:00Z")
    assert r.momento_local.date() == date(2026, 11, 2)
    assert codigos(r) == ["FESTIVO", "FUERA_DE_FRANJA"]
    r = ev("2026-11-01T17:00:00Z")  # domingo 12:00 local
    assert codigos(r) == ["DIA_SIN_FRANJA"]
    assert prox(r) == "2026-11-03T07:00:00-05:00"  # salta el lunes festivo


def test_momento_local_siempre_en_la_zona_de_la_politica():
    cfg = copy.deepcopy(politica_por_defecto()) | {"zona_horaria": "UTC"}
    p = PoliticaCumplimiento.model_validate(cfg)
    r = evaluar_horario(datetime(2026, 10, 23, 12, tzinfo=BOG), p, F26)  # 17:00 UTC
    assert r.momento_local.utcoffset() == timedelta(0) and r.permitido
    r = evaluar_horario(datetime(2026, 10, 23, 19, tzinfo=BOG), p, F26)  # 00:00 UTC sábado
    assert not r.permitido and prox(r) == "2026-10-24T08:00:00+00:00"


def test_resultado_con_datetime_ingenuo_lanza_valueerror_en_ambas_funciones():
    for fn in (evaluar_horario, proxima_ventana):
        with pytest.raises(ValueError):
            fn(datetime(2026, 10, 23, 10, 0), POL, F26)


# --- Festivos trasladados / Semana Santa --------------------------------------------------


@pytest.mark.parametrize(
    ("fecha", "es_festivo"),
    [
        ("2026-01-06", False),  # Reyes original (martes): se traslada al 12
        ("2026-01-12", True),
        ("2026-03-19", False),  # San José original (jueves): se traslada al 23
        ("2026-03-23", True),
        ("2026-06-29", True),  # San Pedro y San Pablo ya cae en lunes
        ("2026-08-15", False),  # sábado: Asunción se traslada al 17
        ("2026-08-17", True),
        ("2026-11-01", False),  # Todos los Santos original (domingo): se traslada al 2
        ("2026-11-02", True),
        ("2026-11-11", False),
        ("2026-11-16", True),
        ("2026-04-01", False),  # miércoles santo no es festivo
        ("2026-04-02", True),
        ("2026-04-03", True),
        ("2026-04-06", False),  # Lunes de Pascua no es festivo
        ("2026-12-08", True),  # fijo en martes: no se traslada
        ("2026-12-07", False),
    ],
)
def test_traslados_2026_en_el_motor(fecha, es_festivo):
    r = ev(f"{fecha}T10:00:00-05:00")
    assert ("FESTIVO" in codigos(r)) is es_festivo, fecha
    if fecha in ("2026-08-15", "2026-11-01"):
        # sábado/domingo: el día original no es festivo; solo cuenta su franja habitual
        assert r.permitido is (fecha == "2026-08-15")


def test_festivo_en_lunes_trasladado_proxima_ventana_el_martes():
    r = ev("2026-01-12T10:00:00-05:00")
    assert codigos(r) == ["FESTIVO"]
    assert prox(r) == "2026-01-13T07:00:00-05:00"


def test_domingo_previo_a_lunes_festivo_salta_al_martes():
    r = ev("2026-01-11T10:00:00-05:00")
    assert codigos(r) == ["DIA_SIN_FRANJA"] and prox(r) == "2026-01-13T07:00:00-05:00"


def test_semana_santa_jueves_y_viernes_encadenados():
    r = ev("2026-04-02T10:00:00-05:00")
    assert prox(r) == "2026-04-04T08:00:00-05:00"  # viernes santo festivo; sábado abre 08:00
    r = ev("2026-04-03T10:00:00-05:00")
    assert codigos(r) == ["FESTIVO"] and prox(r) == "2026-04-04T08:00:00-05:00"


def test_sabado_festivo_conserva_franja_pero_se_bloquea():
    f27 = festivos_colombia(2027)  # 1-may-2027 es sábado
    assert date(2027, 5, 1) in f27
    r = ev("2027-05-01T10:00:00-05:00", festivos=f27)
    assert codigos(r) == ["FESTIVO"] and not r.permitido
    assert prox(r) == "2027-05-03T07:00:00-05:00"
    p = PoliticaCumplimiento.model_validate(politica_por_defecto() | {"permitir_festivos": True})
    assert ev("2027-05-01T10:00:00-05:00", p, f27).permitido


def test_dos_festivos_seguidos_encadenan_la_busqueda():
    festivos = {date(2026, 10, 26): "A", date(2026, 10, 27): "B", date(2026, 10, 28): "C"}
    r = ev("2026-10-25T10:00:00-05:00", festivos=festivos)  # domingo
    assert prox(r) == "2026-10-29T07:00:00-05:00"


def test_mensaje_de_festivo_incluye_fecha_y_nombre():
    r = ev("2026-12-25T10:00:00-05:00")
    assert r.motivos[0].mensaje == "2026-12-25 es festivo (Navidad)."


def test_festivos_vacios_no_bloquean():
    assert ev("2026-11-02T10:00:00-05:00", festivos={}).permitido


# --- proxima_ventana: horizonte y política degenerada --------------------------------------


def test_horizonte_agotado_devuelve_none():
    # 14 días de festivos consecutivos desde el lunes -> no hay ventana
    festivos = {date(2026, 10, 26) + timedelta(days=i): "F" for i in range(30)}
    m = datetime(2026, 10, 25, 10, tzinfo=BOG)
    assert proxima_ventana(m, POL, festivos) is None
    r = evaluar_horario(m, POL, festivos)
    assert not r.permitido and r.proxima_ventana_inicio is None


def test_horizonte_configurable():
    festivos = {date(2026, 10, 26) + timedelta(days=i): "F" for i in range(3)}  # lun-mié
    m = datetime(2026, 10, 25, 10, tzinfo=BOG)  # domingo
    assert proxima_ventana(m, POL, festivos, horizonte_dias=1) is None
    assert proxima_ventana(m, POL, festivos, horizonte_dias=14) == datetime(
        2026, 10, 29, 7, tzinfo=BOG
    )


def test_proxima_ventana_con_utc_devuelve_el_instante_correcto():
    m = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)  # viernes 19:00 Bogotá
    sig = proxima_ventana(m, POL, F26)
    assert sig == datetime(2026, 10, 24, 13, 0, tzinfo=UTC)  # sábado 08:00 Bogotá
    assert sig > m


def test_solo_un_dia_con_franja():
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"] = {d: [] for d in cfg["franjas"]}
    cfg["franjas"]["miercoles"] = [{"inicio": "10:00", "fin": "11:00"}]
    p = PoliticaCumplimiento.model_validate(cfg)
    r = ev("2026-10-23T10:00:00-05:00", p)  # viernes
    assert codigos(r) == ["DIA_SIN_FRANJA"]
    assert prox(r) == "2026-10-28T10:00:00-05:00"
    assert ev("2026-10-28T10:59:59-05:00", p).permitido
    assert not ev("2026-10-28T11:00:00-05:00", p).permitido


def test_franjas_contiguas_no_dejan_hueco():
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["viernes"] = [
        {"inicio": "07:00", "fin": "12:00"},
        {"inicio": "12:00", "fin": "19:00"},
    ]
    p = PoliticaCumplimiento.model_validate(cfg)
    assert ev("2026-10-23T12:00:00-05:00", p).permitido
    assert ev("2026-10-23T11:59:59-05:00", p).permitido


def test_motivos_en_orden_festivo_dia_fuera():
    # Domingo festivo: FESTIVO y DIA_SIN_FRANJA (en ese orden)
    f = {date(2026, 10, 25): "Prueba"}
    assert codigos(ev("2026-10-25T10:00:00-05:00", festivos=f)) == ["FESTIVO", "DIA_SIN_FRANJA"]
    # Lunes festivo a las 22:00: FESTIVO y FUERA_DE_FRANJA
    f = {date(2026, 10, 26): "Prueba"}
    assert codigos(ev("2026-10-26T22:00:00-05:00", festivos=f)) == ["FESTIVO", "FUERA_DE_FRANJA"]


def test_permitido_implica_sin_motivos_ni_proxima():
    for hora in range(24):
        r = ev(f"2026-10-23T{hora:02d}:30:00-05:00")
        assert r.permitido == (7 <= hora < 19)
        assert (r.motivos == ()) is r.permitido
        assert (r.proxima_ventana_inicio is None) is r.permitido
        if not r.permitido:
            assert r.proxima_ventana_inicio > r.momento_local
            assert ev(
                r.proxima_ventana_inicio.isoformat()
            ).permitido  # el inicio de ventana es válido
