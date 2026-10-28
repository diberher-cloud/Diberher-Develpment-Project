import pytest

from app.modulos.conversaciones import dueno as d


class Fila:
    def __init__(self, atendida_por, usuario):
        self.atendida_por, self.usuario_asignado_id = atendida_por, usuario


def test_de_conversacion():
    assert d.de_conversacion(Fila("sin_asignar", None)) == d.SinAsignar()
    assert d.de_conversacion(Fila("humano", 5)) == d.Humano(5)
    assert d.de_conversacion(Fila("ia", None)) == d.IA()


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [
        (d.SinAsignar(), d.Humano(1)),
        (d.Humano(1), d.SinAsignar()),
        (d.Humano(1), d.Humano(2)),  # reasignación
        (d.SinAsignar(), d.IA()),
        (d.Humano(1), d.IA()),
        (d.IA(), d.SinAsignar()),
        (d.IA(), d.Humano(3)),
    ],
)
def test_transiciones_permitidas(actual, nuevo):
    d.validar_transicion(actual, nuevo)


@pytest.mark.parametrize("dueno", [d.SinAsignar(), d.Humano(1), d.IA()])
def test_no_hay_transicion_al_mismo_dueno(dueno):
    with pytest.raises(d.ErrorTransicionDueno):
        d.validar_transicion(dueno, dueno)


def test_dueno_inicial_en_2b():
    assert d.decidir_dueno_inicial(None, None) == d.SinAsignar()
    assert d.decidir_dueno_inicial(None, object(), abre_agente_id=4) == d.Humano(4)
    assert [d.nombre(x) for x in (d.SinAsignar(), d.Humano(1), d.IA())] == [
        "sin_asignar",
        "humano",
        "ia",
    ]
