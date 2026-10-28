"""Simulación de WhatsApp (§4.12): solo con proveedor falso y fuera de producción."""

import pytest
from escenario import cab
from fastapi.testclient import TestClient
from sqlalchemy import select
from wa import NUMERO, contexto, crear_conv

from app.config import Settings
from app.main import create_app
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.seguridad import crear_token

SIM = "/api/v1/whatsapp/simulacion"


def test_flujo_completo_por_api(
    client, db, esc, crear_usuario, reloj, correr_trabajos, proveedor_whatsapp, h_supervisor
):
    ctx = contexto(esc, crear_usuario, reloj, db)
    r = client.post(
        f"{SIM}/entrante",
        json={
            "numero": "300 123 4567",
            "texto": "Hola",
            "nombre_perfil": "María",
            "media": [{"tipo_contenido": "image/png"}],
        },
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200, r.text
    mid, sid = r.json()["mensaje_id"], r.json()["proveedor_id"]
    assert sid.startswith("SMsim")
    m = db.get(Mensaje, mid)
    assert (m.estado, m.tipo, m.numero_cliente_e164) == ("recibido", "media", NUMERO)
    assert m.media[0]["url_proveedor"].startswith("https://media.falso.invalid/")
    assert m.media[0]["categoria"] == "imagen"
    correr_trabajos()
    db.expire_all()
    conv = db.scalar(select(Conversacion))
    assert conv.campana_cliente_id == ctx.cc.id and conv.nombre_perfil == "María"
    # El agente toma, responde, y el simulador entrega el estado.
    assert (
        client.post(f"/api/v1/conversaciones/{conv.id}/tomar", headers=cab(ctx.agente)).status_code
        == 200
    )
    from wa import clave

    r = client.post(
        f"/api/v1/conversaciones/{conv.id}/mensajes",
        json={"texto": "Buenas", "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    saliente = r.json()["id"]
    assert (
        client.post(
            f"{SIM}/mensajes/{saliente}/estado",
            json={"estado": "delivered"},
            headers=cab(ctx.agente),
        ).status_code
        == 404
    )
    correr_trabajos()
    r = client.post(
        f"{SIM}/mensajes/{saliente}/estado", json={"estado": "read"}, headers=cab(ctx.agente)
    )
    assert r.status_code == 204
    r = client.get(f"/api/v1/conversaciones/{conv.id}/mensajes", headers=cab(ctx.agente)).json()
    assert [x["estado"] for x in r["items"]] == ["recibido", "leido"]
    # El medio simulado se descarga por el proxy.
    r = client.get(
        f"/api/v1/conversaciones/{conv.id}/mensajes/{mid}/media/0", headers=cab(ctx.agente)
    )
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert h_supervisor


def test_simulacion_de_fallo_con_codigo(client, db, esc, crear_usuario, reloj, correr_trabajos):
    ctx = contexto(esc, crear_usuario, reloj, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    from wa import clave

    mid = client.post(
        f"/api/v1/conversaciones/{conv.id}/mensajes",
        json={"texto": "x", "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    ).json()["id"]
    correr_trabajos()
    r = client.post(
        f"{SIM}/mensajes/{mid}/estado",
        json={"estado": "failed", "error_codigo": "63016"},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 204
    db.expire_all()
    m = db.get(Mensaje, mid)
    assert (m.estado, m.error_codigo) == ("fallido", "63016")
    assert (
        client.post(
            f"{SIM}/mensajes/{mid}/estado", json={"estado": "sent"}, headers=cab(ctx.agente)
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"numero": "123"},
        {"numero": "+12025550123"},
        {"numero": ""},
        {"texto": "x"},
        {"numero": "3001234567", "media": [{"tipo_contenido": "a"}] * 11},
    ],
)
def test_entrante_invalido_422(client, h_agente, cuerpo):
    assert client.post(f"{SIM}/entrante", json=cuerpo, headers=h_agente).status_code == 422


def test_mensaje_sin_sid_404(client, db, reloj, h_agente):
    conv = crear_conv(db, reloj())
    from wa import crear_saliente

    m = crear_saliente(db, conv, reloj(), estado="pendiente")
    assert (
        client.post(
            f"{SIM}/mensajes/{m.id}/estado", json={"estado": "read"}, headers=h_agente
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{SIM}/mensajes/99999/estado", json={"estado": "read"}, headers=h_agente
        ).status_code
        == 404
    )


def test_la_simulacion_exige_autenticacion(client):
    assert client.post(f"{SIM}/entrante", json={"numero": "3001234567"}).status_code == 401


def test_configuracion_refleja_la_simulacion(client, h_agente):
    r = client.get("/api/v1/whatsapp/configuracion", headers=h_agente)
    assert r.status_code == 200
    assert r.json() == {
        "proveedor": "falso",
        "simulacion": True,
        "numero_empresa_mascara": "+57300****001",
        "margen_ventana_segundos": 60,
        "max_caracteres_texto": 4096,
        "max_conversaciones_agente": 5,
        "media_max_bytes": 16777216,
    }
    assert client.get("/api/v1/whatsapp/configuracion").status_code == 401


def test_simulacion_inexistente_con_produccion_o_con_proveedor_twilio():
    casos = [
        dict(
            entorno="produccion",
            twilio_auth_token="token-real",
            public_base_url="https://x.co",
            jwt_secreto="x" * 32,
        ),
        dict(
            entorno="desarrollo",
            jwt_secreto="x" * 32,
            whatsapp_proveedor="twilio",
            twilio_account_sid="AC1",
            twilio_auth_token="t",
            twilio_api_key_sid="SK1",
            twilio_api_key_secret="s",
            public_base_url="https://x.co",
        ),
    ]
    for kw in casos:
        app = create_app(Settings(_env_file=None, **kw))
        with TestClient(app) as c:
            rutas = c.get("/openapi.json").json()["paths"]
            assert not [p for p in rutas if "whatsapp/simulacion" in p], kw
            h = {"Authorization": "Bearer " + crear_token(1, "agente")[0]}
            assert (
                c.post(f"{SIM}/entrante", json={"numero": "3001234567"}, headers=h).status_code
                == 404
            )
            assert (
                c.post(f"{SIM}/mensajes/1/estado", json={"estado": "read"}, headers=h).status_code
                == 404
            )
    app = create_app(Settings(_env_file=None, entorno="test"))
    with TestClient(app) as c:
        assert [p for p in c.get("/openapi.json").json()["paths"] if "whatsapp/simulacion" in p]
