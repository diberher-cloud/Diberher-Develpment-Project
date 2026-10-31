import pytest
from escenario import cab, telefono_de
from fastapi.testclient import TestClient
from voz import contexto

from app.config import Settings
from app.main import create_app
from app.modulos.telefonia.modelos import EventoLlamada, Llamada

S = "/api/v1/telefonia/simulacion"
K = "/api/v1/consola"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


def iniciar(client, ctx, db):
    return client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(ctx.agente),
    )


def test_flujo_completo_por_api(client, ctx, db, reloj):
    h = cab(ctx.agente)
    r = iniciar(client, ctx, db)
    assert r.status_code == 200 and r.json()["permitida"] is True and r.json()["motivos"] == []
    lid = r.json()["llamada_id"]
    assert client.get(f"{K}/estado", headers=h).json()["estado"] == "en_llamada"
    assert client.get(f"{K}/llamadas/{lid}", headers=h).json()["estado"] == "iniciando"
    assert (
        client.post(
            f"{S}/llamadas/{lid}/eventos", json={"evento": "contestada"}, headers=h
        ).status_code
        == 204
    )
    assert client.get(f"{K}/llamadas/{lid}", headers=h).json()["estado"] == "en_curso"
    reloj.avanzar(seconds=42)
    fin = {"evento": "finalizada", "resultado": "completed", "duracion_segundos": 42}
    assert client.post(f"{S}/llamadas/{lid}/eventos", json=fin, headers=h).status_code == 204
    ll = client.get(f"{K}/llamadas/{lid}", headers=h).json()
    assert (ll["estado"], ll["duracion_segundos"], ll["tipificada"]) == ("completada", 42, False)
    est = client.get(f"{K}/estado", headers=h).json()
    assert est["estado"] == "tipificando"
    assert est["tipificacion_pendiente"] == {"llamada_id": lid, "campana_cliente_id": ctx.cc.id}
    # Repetir el evento final no cambia nada.
    assert client.post(f"{S}/llamadas/{lid}/eventos", json=fin, headers=h).status_code == 204
    assert db.query(EventoLlamada).filter_by(estado_proveedor="dial-terminado").count() == 1


@pytest.mark.parametrize(
    ("resultado", "estado"),
    [
        ("busy", "ocupado"),
        ("no-answer", "no_contesta"),
        ("failed", "fallida"),
        ("canceled", "cancelada"),
    ],
)
def test_finalizaciones_sin_contestar(client, ctx, db, resultado, estado):
    lid = iniciar(client, ctx, db).json()["llamada_id"]
    h = cab(ctx.agente)
    body = {"evento": "finalizada", "resultado": resultado}
    assert client.post(f"{S}/llamadas/{lid}/eventos", json=body, headers=h).status_code == 204
    assert client.get(f"{K}/llamadas/{lid}", headers=h).json()["estado"] == estado


def test_llamada_bloqueada_devuelve_motivos(client, ctx, db, esc, reloj):
    esc.estado(ctx.agente, "pausa", reloj())
    r = iniciar(client, ctx, db)
    assert r.status_code == 200 and r.json()["permitida"] is False
    assert r.json()["llamada_id"] is not None
    assert [m["codigo"] for m in r.json()["motivos"]] == ["AGENTE_NO_DISPONIBLE"]
    ll = client.get(f"{K}/llamadas/{r.json()['llamada_id']}", headers=cab(ctx.agente)).json()
    assert (
        ll["estado"] == "bloqueada" and ll["motivos_bloqueo"][0]["codigo"] == "AGENTE_NO_DISPONIBLE"
    )


def test_parametros_invalidos_sin_fila(client, ctx, db):
    r = client.post(f"{S}/llamadas", json={"campana_cliente_id": ctx.cc.id, "telefono_id": 99999},
                    headers=cab(ctx.agente))  # fmt: skip
    assert r.json() == {
        "llamada_id": None,
        "permitida": False,
        "motivos": [{"codigo": "PARAMETROS_INVALIDOS", "mensaje": "Parámetros inválidos."}],
    }
    assert db.query(Llamada).count() == 0
    assert client.post(f"{S}/llamadas", json={}, headers=cab(ctx.agente)).status_code == 422


def test_solo_llamadas_propias_y_solo_agentes(client, ctx, db, crear_usuario, h_admin):
    lid = iniciar(client, ctx, db).json()["llamada_id"]
    otro = crear_usuario("agente")
    body = {"evento": "contestada"}
    assert (
        client.post(f"{S}/llamadas/{lid}/eventos", json=body, headers=cab(otro)).status_code == 404
    )
    assert (
        client.post(f"{S}/llamadas/9999/eventos", json=body, headers=cab(ctx.agente)).status_code
        == 404
    )
    assert client.get(f"{K}/llamadas/{lid}", headers=cab(otro)).status_code == 404
    assert client.post(f"{S}/llamadas/{lid}/eventos", json=body, headers=h_admin).status_code == 403
    assert (
        client.post(
            f"{S}/llamadas", json={"campana_cliente_id": 1, "telefono_id": 1}, headers=h_admin
        ).status_code
        == 403
    )


def test_evento_invalido_422(client, ctx, db):
    lid = iniciar(client, ctx, db).json()["llamada_id"]
    h = cab(ctx.agente)
    for body in ({"evento": "otro"}, {"evento": "finalizada", "resultado": "xx"},
                 {"evento": "finalizada", "duracion_segundos": -1}):  # fmt: skip
        assert client.post(f"{S}/llamadas/{lid}/eventos", json=body, headers=h).status_code == 422


@pytest.mark.parametrize(
    "kwargs",
    [
        {"entorno": "produccion", "ia_habilitada": False, "twilio_auth_token": "token-real",
         "public_base_url": "https://x.co", "jwt_secreto": "x" * 32},
        {"entorno": "test", "telefonia_proveedor": "twilio", "twilio_account_sid": "AC1",
         "twilio_auth_token": "t", "twilio_api_key_sid": "SK1", "twilio_api_key_secret": "s",
         "twilio_twiml_app_sid": "AP1", "twilio_numero_saliente": "+576015550000"},
    ],
)  # fmt: skip
def test_simulacion_no_existe_en_produccion_ni_con_twilio(kwargs):
    app = create_app(Settings(_env_file=None, **kwargs))
    with TestClient(app) as c:
        assert c.post(f"{S}/llamadas", json={}).status_code == 404
        assert c.post(f"{S}/llamadas/1/eventos", json={}).status_code == 404
