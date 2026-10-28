"""Opt-out por patrones normalizados (Ley 1581/2300): cobertura ampliada sin falsos positivos."""

import pytest

from app.modulos.whatsapp import opt_out as oo

WA = oo.cargar_frases("", oo.FRASES_WHATSAPP)
TODOS = oo.cargar_frases("", oo.FRASES_TODOS)


def c(texto, **kw):
    return oo.clasificar(texto, None, WA, TODOS, "BAJA", **kw)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("no me escriban más mensajes", "whatsapp"),
        ("No me escriban mas mensajes!!", "whatsapp"),
        ("no me manden más mensajes", "whatsapp"),
        ("NO ME MANDEN MENSAJES", "whatsapp"),
        ("ya no me escriban", "whatsapp"),
        ("Ya no me escriban más", "whatsapp"),
        ("ya no me manden mas", "whatsapp"),
        ("quiero darme de baja", "whatsapp"),
        ("Quiero que me den de baja", "whatsapp"),
        ("¿me pueden dar de baja?", "whatsapp"),
        ("¿Podrían darme de baja, por favor?", "whatsapp"),
        ("dar de baja", "whatsapp"),
        ("STOPALL", "whatsapp"),
        ("stop all", "whatsapp"),
        ("sáquenme de la lista", "whatsapp"),
        ("Por favor sáquenme de la lista de mensajes", "whatsapp"),
        ("quiero salir de la lista", "whatsapp"),
        ("no me contacten más", "todos"),
        ("Ya no me contacten", "todos"),
        ("no me llamen", "voz"),
        ("No me llamen más", "voz"),
        ("ya no me llamen mas 😡", "voz"),
        ("no me vuelvan a llamar", "voz"),
        ("no me llamen ni me escriban", "todos"),  # sigue siendo todos los canales
    ],
)
def test_positivos(texto, esperado):
    assert c(texto) == esperado, texto


@pytest.mark.parametrize(
    "texto",
    [
        "no puedo pagar",
        "cancelar",
        "ya pagué",
        "no gracias",
        "¿Baja el precio?",
        "no",
        "no me escriban más tarde",
        "no me escriban mañana",
        "no me llamen hasta el lunes",
        "no me llamen a las 3",
        "no me llamen en la mañana",
        "no me contacten hasta el lunes",
        "ya no me escriban a ese número, escríbanme al otro",
        "quiero darme un plazo",
        "quiero pagar",
        "me pueden dar plazo?",
        "me pueden dar un descuento",
        "dar de baja la cuota",
        "sáquenme de dudas",
        "no me manden nada hoy",
        "no me mandaron el recibo",
        "no me escribieron",
        "ya me llamaron",
        "quiero salir de deudas",
        "saquenme el saldo",
    ],
)
def test_negativos(texto):
    assert c(texto) is None, texto


def test_con_listas_configuradas_los_patrones_se_pueden_apagar():
    assert c("ya no me escriban", usar_patrones=False) is None
    assert c("no me escriban", usar_patrones=False) == "whatsapp"  # la lista literal sigue


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("no me contacten más por WhatsApp", "whatsapp"),
        ("No me contacten por whatsapp", "whatsapp"),
        ("ya no me contacten por este chat", "whatsapp"),
        ("no me contacten por ningún medio", "todos"),
        ("No me contacten más por ningún canal", "todos"),
        ("por ningún medio no me contacten", "todos"),
    ],
)
def test_s9_contacto_por_canal_o_por_ningun_medio(texto, esperado):
    assert c(texto) == esperado


@pytest.mark.parametrize("texto", ["no me contacten por la tarde", "no me contacten por correo"])
def test_s9_otras_frases_no_son_opt_out(texto):
    assert c(texto) is None


def test_s9_los_patrones_de_voz_siguen_activos_con_listas_configuradas():
    assert c("no me llamen", usar_patrones=False) == "voz"
    assert c("No me llamen más", usar_patrones=False) == "voz"
    assert c("ya no me escriban", usar_patrones=False) is None  # WhatsApp sí depende de las listas
