"""Ventana de 24 h y `decidir_respuesta` (módulo puro)."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modulos.cumplimiento.politica import PoliticaCumplimiento, politica_por_defecto
from app.modulos.whatsapp.ventana import (
    Enviar,
    Rechazar,
    Retener,
    decidir_respuesta,
    ventana_abierta,
)

BOG = ZoneInfo("America/Bogota")
MARGEN = timedelta(seconds=60)


def politica(responder_fuera: bool) -> PoliticaCumplimiento:
    cfg = politica_por_defecto()
    cfg["entrantes"]["responder_fuera_de_franja"] = responder_fuera
    return PoliticaCumplimiento.model_validate(cfg)


def local(dia, h, m=0, s=0):
    return datetime(2026, 10, dia, h, m, s, tzinfo=BOG)


FESTIVOS: dict[date, str] = {date(2026, 10, 12): "Día de la Raza"}


def test_ventana_abierta_respeta_el_margen():
    conv = SimpleNamespace(ventana_expira_en=local(24, 10, 0).astimezone(UTC))
    assert ventana_abierta(conv, local(24, 9, 58), MARGEN)
    assert not ventana_abierta(conv, local(24, 9, 59, 30), MARGEN)
    assert not ventana_abierta(conv, local(24, 10, 0), MARGEN)
    assert not ventana_abierta(SimpleNamespace(ventana_expira_en=None), local(23, 10), MARGEN)


def test_con_responder_fuera_de_franja_siempre_envia():
    d = decidir_respuesta(local(25, 22), [politica(True)], FESTIVOS, local(26, 22), MARGEN)
    assert d == Enviar()  # domingo 22:00 (V7)


def test_dentro_de_franja_envia_aunque_no_se_permita_fuera():
    assert (
        decidir_respuesta(local(23, 10), [politica(False)], FESTIVOS, local(24, 10), MARGEN)
        == Enviar()
    )


def test_v4_retiene_hasta_la_proxima_franja_si_cabe_en_la_ventana():
    d = decidir_respuesta(local(23, 19, 30), [politica(False)], FESTIVOS, local(24, 19, 20), MARGEN)
    assert d == Retener(local(24, 8, 0))


def test_v5_rechaza_si_la_proxima_franja_empieza_tras_cerrar_la_ventana():
    d = decidir_respuesta(local(24, 15, 30), [politica(False)], FESTIVOS, local(25, 15, 20), MARGEN)
    assert isinstance(d, Rechazar) and d.codigo == "RESPUESTA_FUERA_DE_FRANJA"
    assert d.proxima_franja == local(26, 7, 0)


def test_v8_sin_campana_manda_la_politica_mas_restrictiva():
    d = decidir_respuesta(
        local(23, 19, 30),
        [politica(True), politica(False)],
        FESTIVOS,
        local(24, 19, 20),
        MARGEN,
    )
    assert isinstance(d, Retener)


def test_limite_exacto_de_la_ventana_rechaza():
    # La franja empieza justo al cierre efectivo de la ventana (expira - margen): se rechaza.
    d = decidir_respuesta(local(23, 19, 30), [politica(False)], FESTIVOS, local(24, 8, 1), MARGEN)
    assert isinstance(d, Rechazar)
