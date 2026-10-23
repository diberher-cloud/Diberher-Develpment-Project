import pytest
from escenario import cab

from app.modulos.consola.modelos import HistorialEstadoAgente

E = "/api/v1/consola/estado"


@pytest.fixture()
def agente(crear_usuario):
    return crear_usuario("agente")


def poner(client, agente, **cuerpo):
    return client.put(E, json=cuerpo, headers=cab(agente))


def test_sin_fila_es_desconectado(client, agente, reloj):
    r = client.get(E, headers=cab(agente))
    assert r.status_code == 200
    assert r.json() == {
        "estado": "desconectado",
        "desde": "2026-10-23T15:15:00Z",
        "motivo_pausa": None,
        "llamada_id": None,
        "tipificacion_pendiente": None,
    }


def test_cambios_manuales_e_historial(client, agente, db, reloj):
    assert poner(client, agente, estado="disponible").json()["estado"] == "disponible"
    reloj.avanzar(minutes=10)
    r = poner(client, agente, estado="pausa", motivo_pausa="almuerzo")
    assert r.json()["estado"] == "pausa" and r.json()["motivo_pausa"] == "almuerzo"
    reloj.avanzar(minutes=30)
    assert poner(client, agente, estado="disponible").json()["motivo_pausa"] is None
    historial = db.query(HistorialEstadoAgente).order_by(HistorialEstadoAgente.id).all()
    assert [(h.estado, h.fin is None) for h in historial] == [
        ("disponible", False),
        ("pausa", False),
        ("disponible", True),
    ]
    assert historial[0].fin == historial[1].inicio


def test_identidad_sin_efectos(client, agente, db):
    poner(client, agente, estado="disponible")
    r = poner(client, agente, estado="disponible")
    assert r.status_code == 200
    assert db.query(HistorialEstadoAgente).count() == 1
    poner(client, agente, estado="pausa", motivo_pausa="otro")
    poner(client, agente, estado="pausa", motivo_pausa="otro")
    assert db.query(HistorialEstadoAgente).count() == 2
    assert (
        poner(client, agente, estado="pausa", motivo_pausa="reunion").json()["motivo_pausa"]
        == "reunion"
    )
    assert db.query(HistorialEstadoAgente).count() == 3


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"estado": "pausa"},
        {"estado": "disponible", "motivo_pausa": "descanso"},
        {"estado": "pausa", "motivo_pausa": "siesta"},
        {"estado": "en_llamada"},
        {"estado": "tipificando"},
        {},
    ],
)
def test_validacion_422(client, agente, cuerpo):
    r = poner(client, agente, **cuerpo)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"


@pytest.mark.parametrize(
    ("estado", "codigo"),
    [("en_llamada", "AGENTE_EN_LLAMADA"), ("tipificando", "TIPIFICACION_PENDIENTE")],
)
@pytest.mark.parametrize(
    "cuerpo",
    [
        {"estado": "disponible"},
        {"estado": "pausa", "motivo_pausa": "otro"},
        {"estado": "desconectado"},
    ],
)
def test_estados_automaticos_bloquean(client, agente, esc, reloj, estado, codigo, cuerpo):
    esc.estado(agente, estado, reloj())
    r = poner(client, agente, **cuerpo)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == codigo


def test_solo_agentes(client, h_admin, h_supervisor):
    for h in (h_admin, h_supervisor):
        assert client.get(E, headers=h).status_code == 403
        assert client.put(E, json={"estado": "disponible"}, headers=h).status_code == 403
    assert client.get(E).status_code == 401
