import pytest

from app.modulos.consola.estados import ErrorTransicion, resolver_transicion


@pytest.mark.parametrize(
    ("actual", "motivo_actual", "destino", "motivo", "esperado"),
    [
        ("desconectado", None, "disponible", None, "cambia"),
        ("desconectado", None, "pausa", "descanso", "cambia"),
        ("desconectado", None, "desconectado", None, "igual"),
        ("disponible", None, "disponible", None, "igual"),
        ("disponible", None, "pausa", "almuerzo", "cambia"),
        ("disponible", None, "desconectado", None, "cambia"),
        ("pausa", "almuerzo", "disponible", None, "cambia"),
        ("pausa", "almuerzo", "pausa", "reunion", "cambia"),
        ("pausa", "almuerzo", "pausa", "almuerzo", "igual"),
        ("pausa", "almuerzo", "desconectado", None, "cambia"),
    ],
)
def test_transiciones_validas(actual, motivo_actual, destino, motivo, esperado):
    assert resolver_transicion(actual, motivo_actual, destino, motivo) == esperado


@pytest.mark.parametrize("destino", ["disponible", "pausa", "desconectado"])
def test_en_llamada_y_tipificando_bloquean(destino):
    with pytest.raises(ErrorTransicion) as e:
        resolver_transicion("en_llamada", None, destino, None)
    assert (e.value.status, e.value.codigo) == (409, "AGENTE_EN_LLAMADA")
    with pytest.raises(ErrorTransicion) as e:
        resolver_transicion("tipificando", None, destino, None)
    assert (e.value.status, e.value.codigo) == (409, "TIPIFICACION_PENDIENTE")


def test_destino_automatico_no_es_manual():
    with pytest.raises(ErrorTransicion) as e:
        resolver_transicion("disponible", None, "en_llamada", None)
    assert e.value.codigo == "TRANSICION_ESTADO_INVALIDA"
