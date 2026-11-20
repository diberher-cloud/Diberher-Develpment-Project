"""H1 (cifras en letras, abreviadas y sin símbolo) y H2 (citas negadas o parciales)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.modulos.agente_ia import guardas as g
from app.modulos.agente_ia.canal import EntradaCliente, TextoCliente

AHORA = datetime(2026, 10, 23, 15, tzinfo=UTC)


def ctx(verificada=True, montos=("300000", "1500000", "90000"), pct=("10", "20", "100")):
    return g.ContextoGuardas(
        "1020304050", verificada, frozenset(D(m) for m in montos), frozenset(D(p) for p in pct),
        frozenset(), 1000,
    )  # fmt: skip


@pytest.mark.parametrize(
    "texto,valor",
    [
        ("doscientos cincuenta mil pesos", 250000),
        ("noventa y cinco mil", 95000),
        ("un millón quinientos mil pesos", 1500000),
        ("medio millón de pesos", 500000),
        ("dos millones", 2000000),
        ("cien mil pesos", 100000),
        ("trescientos pesos", 300),
        ("mil quinientos pesos", 1500),
        ("Debe trescientos mil pesos", 300000),
        ("250  mil", 250000),
        ("250 000 pesos", 250000),
        ("250,000 pesos", 250000),
        ("$２５０.０００", 250000),
    ],
)
def test_montos_en_letras_y_variantes(texto, valor):
    assert g.extraer_montos(texto) == [D(valor)]


@pytest.mark.parametrize(
    "texto,valor",
    [("treinta por ciento", 30), ("el veinticinco por ciento", 25), ("35 porciento", 35),
     ("cien por ciento", 100), ("35 %", 35)],
)  # fmt: skip
def test_porcentajes_en_letras(texto, valor):
    assert g.extraer_porcentajes(texto) == [D(valor)]


@pytest.mark.parametrize(
    "texto",
    ["mil gracias", "una cuota de tres pagos", "media hora", "un asesor le llamará en dos días",
     "pague el 30/10/2026, referencia AP-1234, en 2026", "45 días de mora"],
)  # fmt: skip
def test_lenguaje_normal_no_es_una_cifra(texto):
    c = g.analizar_cifras(texto)
    assert not c.montos and not c.porcentajes and not c.inciertas


@pytest.mark.parametrize(
    "texto",
    ["250k", "1.5M", "dosientos mil pesos", "descuento del mucho por ciento", "250000",
     "treinta y y cinco por ciento"],
)  # fmt: skip
def test_lo_dudoso_se_bloquea(texto):
    assert g.salida(texto, ctx()).codigo == "MONTO_NO_RESPALDADO"


def test_antes_de_verificar_tambien_las_cifras_en_letras():
    f = g.salida("Debe trescientos mil pesos", ctx(verificada=False))
    assert f.codigo == "MONTO_ANTES_DE_VERIFICAR"


def test_lo_respaldado_sigue_pasando_en_cualquier_forma():
    for t in ("300 mil pesos", "trescientos mil pesos", "$ 300.000", "1,5 millones",
              "un millón quinientos mil pesos", "el diez por ciento", "10 por ciento",
              "noventa mil pesos por cuota"):  # fmt: skip
        assert g.salida(t, ctx()) is None, t


# ---- Citas ------------------------------------------------------------------------------------
def msg(texto, minutos=5, i=1):
    return TextoCliente(i, AHORA + timedelta(minutes=minutos), texto)


@pytest.mark.parametrize(
    "texto", ["Sí, acepto", "de acuerdo, pago el 15", "ok listo", "Sí, acepto el plan"]
)
def test_positivos_siguen_valiendo(texto):
    assert g.verificar_cita(texto, [msg(texto)], AHORA) is None


def test_cita_parcial_de_mensaje_largo_no_vale():
    m = [msg("Sí, acepto, pero antes necesito que me expliquen los intereses y el plazo")]
    assert g.verificar_cita("acepto", m, AHORA) == "CITA_NO_VALIDA"
    assert (
        g.verificar_cita(
            "Sí, acepto, pero antes necesito que me expliquen los intereses y el plazo", m, AHORA
        )
        is None
    )


@pytest.mark.parametrize(
    "texto", ["No acepto, es abusivo", "nunca voy a aceptar", "tampoco acepto", "ni modo, acepto",
              "para nada, acepto", "no estoy de acuerdo", "no quiero"],
)  # fmt: skip
def test_negacion_no_es_aceptacion(texto):
    if "acepto" in texto.split():
        assert g.verificar_cita("acepto", [msg(texto)], AHORA) == "CITA_NEGADA"
    assert g.verificar_cita(texto, [msg(texto)], AHORA) == "CITA_NEGADA"  # ni citando completo


def test_opt_out_exige_mensaje_completo_y_admite_negacion():
    m = [msg("por WhatsApp sí, pero no me llamen")]
    kw = dict(afirmacion=False, completo=True)
    assert g.verificar_cita("no me llamen", m, AHORA, **kw) == "CITA_NO_VALIDA"
    assert g.verificar_cita("por WhatsApp sí, pero no me llamen", m, AHORA, **kw) is None


def test_localizar_devuelve_el_mensaje():
    m = [msg("ok listo", i=7)]
    assert g.localizar_cita("ok listo", m, AHORA).id == 7


def test_ge2_evalua_todos_los_entrantes_del_lote():
    es = [EntradaCliente(1, AHORA, "texto", "asesor", None, None),
          EntradaCliente(2, AHORA, "texto", "gracias por todo", None, None)]  # fmt: skip
    assert g.entrada(es, g.cargar_frases_humano(""), "ASESOR", 2000).pide_humano
