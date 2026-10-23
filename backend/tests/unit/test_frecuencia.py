"""Casos F1-F12 de fase-2.md §6 sobre el motor puro (reloj fijo, política por defecto)."""

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.modulos.cumplimiento.frecuencia import (
    IntentoPrevio,
    evaluar_frecuencia,
    proximo_permitido_frecuencia,
)
from app.modulos.cumplimiento.motor import evaluar_contacto
from app.modulos.cumplimiento.politica import PoliticaCumplimiento, politica_por_defecto

BOG = timezone(timedelta(hours=-5))


def dt(dia: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, dia, h, m, tzinfo=BOG)


def politica(**frec) -> PoliticaCumplimiento:
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["frecuencia"].update(frec)
    return PoliticaCumplimiento.model_validate(cfg)


def previo(momento, canal="voz", por="empresa", directo=True) -> IntentoPrevio:
    return IntentoPrevio(momento, canal, por, directo)


def codigos(r) -> list[str]:
    return [m.codigo for m in r.motivos]


P = politica()


def test_f1_historial_vacio_permitido():
    r = evaluar_contacto(dt(23, 10), "voz", P, {}, [])
    assert r.permitido and r.proxima_ventana_inicio is None


def test_f2_sin_contacto_directo_no_aplica_limite():
    r = evaluar_contacto(dt(23, 10), "voz", P, {}, [previo(dt(23, 8), directo=False)])
    assert r.permitido


def test_f3_mismo_dia_tras_contacto_directo():
    r = evaluar_contacto(dt(23, 10), "voz", P, {}, [previo(dt(23, 8))])
    assert not r.permitido and codigos(r) == ["FRECUENCIA_DIA"]
    assert r.proxima_ventana_inicio == dt(24, 8)
    assert "1 contacto(s)" in r.motivos[0].mensaje


def test_f4_dia_siguiente_mismo_medio_permitido():
    assert evaluar_contacto(dt(24, 10), "voz", P, {}, [previo(dt(23, 8))]).permitido


def test_f5_otro_medio_misma_semana():
    r = evaluar_contacto(dt(24, 10), "whatsapp_mensaje", P, {}, [previo(dt(23, 8))])
    assert codigos(r) == ["FRECUENCIA_MEDIOS"]
    assert r.proxima_ventana_inicio == dt(26, 7)


def test_f6_semana_movil_7_dias():
    p = politica(semana="movil_7_dias")
    r = evaluar_contacto(dt(26, 10), "whatsapp_mensaje", p, {}, [previo(dt(22, 8))])
    assert codigos(r) == ["FRECUENCIA_MEDIOS"]
    assert r.proxima_ventana_inicio == dt(29, 8)


def test_f7_intentos_sin_contacto_cuentan_o_no():
    hist = [previo(dt(19, 10)), previo(dt(23, 8), directo=False)]
    assert codigos(evaluar_contacto(dt(23, 10), "voz", P, {}, hist)) == ["FRECUENCIA_DIA"]
    sin = politica(contar_intentos_sin_contacto=False)
    assert evaluar_contacto(dt(23, 10), "voz", sin, {}, hist).permitido


def test_f8_entrantes_no_consumen_cupo():
    hist = [previo(dt(23, 8), "whatsapp_mensaje", por="cliente")]
    assert evaluar_contacto(dt(23, 10), "voz", P, {}, hist).permitido


def test_f9_whatsapp_llamada_cuenta_como_medio_whatsapp():
    r = evaluar_contacto(dt(21, 10), "whatsapp_llamada", P, {}, [previo(dt(19, 10))])
    assert codigos(r) == ["FRECUENCIA_MEDIOS"]


def test_f10_max_canales_dos():
    p = politica(max_canales_semana=2)
    assert evaluar_contacto(dt(24, 10), "whatsapp_mensaje", p, {}, [previo(dt(23, 8))]).permitido


def test_f11_entrante_fuera_de_franja():
    domingo = dt(25, 22)
    assert evaluar_contacto(domingo, "whatsapp_mensaje", P, {}, [], entrante=True).permitido
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["entrantes"]["responder_fuera_de_franja"] = False
    p = PoliticaCumplimiento.model_validate(cfg)
    r = evaluar_contacto(domingo, "whatsapp_mensaje", p, {}, [], entrante=True)
    assert codigos(r) == ["DIA_SIN_FRANJA"]


def test_horario_y_frecuencia_en_orden():
    r = evaluar_contacto(dt(23, 19, 30), "voz", P, {}, [previo(dt(23, 8))])
    assert codigos(r) == ["FUERA_DE_FRANJA", "FRECUENCIA_DIA"]
    assert r.proxima_ventana_inicio == dt(24, 8)


def test_momento_ingenuo_es_error():
    with pytest.raises(ValueError):
        evaluar_contacto(datetime(2026, 10, 23, 10), "voz", P, {}, [])
    with pytest.raises(ValueError):
        evaluar_frecuencia(datetime(2026, 10, 23, 10), "voz", P, [])


def test_entrante_del_cliente_establece_contacto_directo_configurable():
    hist = [
        previo(dt(23, 8), "whatsapp_mensaje", por="cliente", directo=True),
        previo(dt(23, 9), "voz", por="empresa", directo=False),
    ]
    # El entrante establece contacto directo => se aplica el límite diario al intento de la empresa.
    assert codigos(evaluar_contacto(dt(23, 11), "voz", P, {}, hist)) == ["FRECUENCIA_DIA"]
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["entrantes"]["establecen_contacto_directo"] = False
    p = PoliticaCumplimiento.model_validate(cfg)
    assert evaluar_contacto(dt(23, 11), "voz", p, {}, hist).permitido


def test_intentos_futuros_no_cuentan():
    assert evaluar_contacto(dt(23, 10), "voz", P, {}, [previo(dt(23, 12))]).permitido


def test_sin_proximo_en_el_horizonte():
    p = politica(max_contactos_dia=1)
    hist = [previo(dt(23, 8))]
    assert proximo_permitido_frecuencia(dt(23, 10), "voz", p, hist, horizonte_dias=0) is None
    assert proximo_permitido_frecuencia(dt(23, 10), "voz", p, hist) == dt(24, 0)


def test_festivo_desplaza_la_proxima_ventana_conjunta():
    festivos = {datetime(2026, 10, 24).date(): "Festivo de prueba"}
    r = evaluar_contacto(dt(23, 10), "voz", P, festivos, [previo(dt(23, 8))])
    assert r.proxima_ventana_inicio == dt(26, 7)
