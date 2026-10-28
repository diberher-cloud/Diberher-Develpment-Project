"""QA 2B: opt-out con variantes reales del español colombiano (mayúsculas, tildes, emojis,
cortesías) y frases que NO son opt-out (en Colombia "cancelar" es pagar; "no puedo pagar" es
una negociación, no una baja). Complementa O1-O20 de `test_opt_out.py`."""

import unicodedata

import pytest

from app.modulos.whatsapp import opt_out as oo

WA = oo.cargar_frases("", oo.FRASES_WHATSAPP)
TODOS = oo.cargar_frases("", oo.FRASES_TODOS)


def clasificar(texto, payload=None):
    return oo.clasificar(texto, payload, WA, TODOS, "BAJA")


@pytest.mark.parametrize(
    "texto",
    [
        "STOP",
        "Stop.",
        "  stop  ",
        "STOP\n",
        "\tstop\r\n",
        "¡¡STOP!!",
        "'stop'",
        "🛑 STOP 🛑",
        "Stop, por favor",
        "stop gracias",
        "ＳＴＯＰ",  # ancho completo (teclados móviles)
        "NO ME ESCRIBAN MÁS",
        "no me escriban mas",
        "¡¡NO ME ESCRIBAN MÁS!!",
        "NO ME ESCRIBAN MÁS 🙏🙏",
        "No me escriban más. Gracias.",
        "Hola, buenas tardes. No me escriban más, por favor.",
        "Dejen de escribirme",
        "No me vuelvan a escribir",
        "no quiero más mensajes",
        "No quiero mas mensajes por favor",
        "No me envíen más mensajes",
        "Darme de baja",
        "DAR DE BAJA",
        "baja",
        "unsubscribe",
        "UNSUBSCRIBE",
        "parar",
    ],
)
def test_variantes_que_si_son_opt_out_de_whatsapp(texto):
    assert clasificar(texto) == "whatsapp", repr(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "no me contacten más",
        "NO ME CONTACTEN MÁS",
        "Por favor no me contacten más",
        "No me vuelvan a contactar",
        "No me llamen ni me escriban",
        "NO ME LLAMEN NI ME ESCRIBAN MÁS 😡",
        "Hola buenas tardes no me contacten más por favor gracias",
    ],
)
def test_variantes_que_si_son_opt_out_de_todos_los_canales(texto):
    assert clasificar(texto) == "todos", repr(texto)


@pytest.mark.parametrize(
    "texto",
    [
        # Negociación de deuda: jamás deben cerrar la conversación ni excluir al titular.
        "no puedo pagar",
        "no puedo pagar ahora",
        "no puedo",
        "no tengo plata",
        "no tengo cómo pagar",
        "ya pagué",
        "ya pagué la deuda",
        "no gracias",
        "no me interesa",
        "no, gracias",
        "cancelar",
        "quiero cancelar",
        "quiero cancelar la deuda",
        "cancelo mañana",
        "voy a cancelar el saldo",
        "no",
        "NO",
        "salir",
        "no sé",
        "no entiendo",
        "no tengo cédula",
        # Parecidas pero distintas.
        "stopped",
        "stoop",
        "s t o p",
        "stop 123",
        "bajar la cuota",
        "¿Baja el precio?",
        "la baja de la cuota",
        "Pare de sufrir",
        "no me escriban mañana sino el lunes",
        "no me escriban más tarde",
        "no me contacten hasta el lunes",
        "hola",
        "buenos días",
        "gracias",
        "por favor",
        "😀",
        "",
        "   ",
        None,
    ],
)
def test_frases_que_no_son_opt_out(texto):
    assert clasificar(texto) is None, repr(texto)


def test_la_coincidencia_no_depende_de_la_forma_unicode():
    nfd = unicodedata.normalize("NFD", "NO ME ESCRIBAN MÁS")
    nfc = unicodedata.normalize("NFC", "NO ME ESCRIBAN MÁS")
    assert nfd != nfc
    assert clasificar(nfd) == clasificar(nfc) == "whatsapp"


def test_texto_largo_o_con_caracteres_de_control_no_es_opt_out():
    assert clasificar("stop" + " " * 200) is None  # >80 caracteres aunque sean espacios
    assert clasificar("st\x00op") is None
    assert clasificar("stop​") in ("whatsapp", None)  # sin excepción


def test_el_payload_de_baja_manda_aunque_el_texto_diga_otra_cosa():
    assert clasificar("no puedo pagar", "BAJA") == "whatsapp"
    assert clasificar("stop", "OTRO") == "whatsapp"  # el texto sigue contando
    assert clasificar("hola", "baja") is None  # el payload distingue mayúsculas
    assert clasificar("hola", "") is None


def test_no_hay_excepciones_con_entradas_extranas():
    for texto in ("\ud83d", "\U0010ffff", "a" * 10_000, "\x00" * 5, "‮stop"):
        clasificar(texto)
