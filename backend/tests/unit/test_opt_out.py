"""Opt-out determinista (O1-O20): coincidencia exacta tras normalizar, nunca por subcadena."""

import pytest

from app.modulos.whatsapp import opt_out as oo

WA = oo.cargar_frases("", oo.FRASES_WHATSAPP)
TODOS = oo.cargar_frases("", oo.FRASES_TODOS)


def clasificar(texto, payload=None, wa=WA, todos=TODOS):
    return oo.clasificar(texto, payload, wa, todos, "BAJA")


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("STOP", "whatsapp"),  # O1
        ("stop!!!", "whatsapp"),  # O2
        ("Stop 🙏", "whatsapp"),  # O3
        ("NO ME ESCRIBAN MÁS", "whatsapp"),  # O4
        ("Por favor no me escriban más, gracias.", "whatsapp"),  # O5
        ("Darme de baja", "whatsapp"),  # O6
        ("no me contacten más", "todos"),  # O7
        ("No me llamen ni me escriban", "todos"),  # O8
        ("Buenos días, no me contacten", "todos"),  # O9
        ("quiero cancelar la deuda", None),  # O10
        ("cancelar", None),  # O11
        ("no", None),  # O12
        ("no me escriban mañana sino el lunes", None),  # O13
        ("¿Baja el precio?", None),  # O14
        ("stopped", None),  # O15
        ("stop " + "x" * 80, None),  # O16: más de 80 caracteres
        (None, None),  # O20
        ("", None),
        ("   ", None),
        ("hola", None),
        ("salir", None),
    ],
)
def test_clasificacion(texto, esperado):
    assert clasificar(texto) == esperado


def test_o17_boton_de_baja_y_o18_otro_payload():
    assert clasificar("Darme de baja", "BAJA") == "whatsapp"
    assert clasificar(None, "BAJA") == "whatsapp"
    assert clasificar("hola", "OTRO") is None


def test_o19_lista_configurada_reemplaza_la_de_defecto():
    wa = oo.cargar_frases("alto|PARE ya", oo.FRASES_WHATSAPP)
    assert clasificar("ALTO.", wa=wa) == "whatsapp"
    assert clasificar("pare, ya!", wa=wa) == "whatsapp"
    assert clasificar("stop", wa=wa) is None


def test_normalizar_quita_cortesias_repetidas_y_nunca_vacia_de_mas():
    assert oo.normalizar("Hola, buenas tardes, por favor STOP, muchas gracias") == "stop"
    assert oo.normalizar("  Áéí  ÑANDÚ ") == "aei nandu"
    assert oo.normalizar("gracias") == "gracias"  # un sufijo solo no se elimina
    assert oo.normalizar("😀") == ""


def test_la_coincidencia_es_exacta_no_por_subcadena():
    assert clasificar("no me escriban mas por favor") == "whatsapp"
    assert clasificar("pare de escribirme") is None
    assert clasificar("no me escriban mas ni me llamen") is None
    # Una frase de "todos" prevalece si aparece en ambas listas.
    assert oo.clasificar("x", None, frozenset({"x"}), frozenset({"x"}), "BAJA") == "todos"
