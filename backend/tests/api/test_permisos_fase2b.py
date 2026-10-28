"""Matriz de permisos de 2B (§4.1): rol × endpoint nuevo, y webhooks sin JWT."""

import pytest
from escenario import cab
from wa import RUTA_ENTRANTE, RUTA_ESTADO, clave

API = "/api/v1"
ROLES = {"administrador": "A", "supervisor": "S", "agente": "G"}
UUID = clave()
CUERPO_TEXTO = {"texto": "hola", "idempotencia_clave": UUID}
CUERPO_PLANTILLA = {"plantilla_id": 1, "idempotencia_clave": UUID}

# (método, ruta, cuerpo, roles permitidos)
MATRIZ = [
    ("GET", "/whatsapp/configuracion", None, "ASG"),
    ("GET", "/whatsapp/plantillas?campana_id=1", None, "ASG"),
    ("POST", "/whatsapp/plantillas/sincronizar", None, "A"),
    ("PUT", "/whatsapp/plantillas/1", {}, "AS"),
    ("GET", "/autorizaciones", None, "AS"),
    (
        "POST",
        "/autorizaciones",
        {"telefono": "3001234567", "finalidad": "venta", "evidencia": "abcde"},
        "AS",
    ),
    ("DELETE", "/autorizaciones/1", None, "AS"),
    ("GET", "/conversaciones", None, "ASG"),
    ("GET", "/conversaciones/1", None, "ASG"),
    ("GET", "/conversaciones/1/mensajes", None, "ASG"),
    ("GET", "/conversaciones/1/ficha", None, "ASG"),
    ("GET", "/conversaciones/1/mensajes/1/media/0", None, "ASG"),
    ("POST", "/conversaciones/1/mensajes", CUERPO_TEXTO, "ASG"),
    ("POST", "/conversaciones/1/plantillas", CUERPO_PLANTILLA, "ASG"),
    ("POST", "/conversaciones/1/leida", None, "ASG"),
    ("POST", "/conversaciones/1/opt-out", {"alcance": "whatsapp"}, "ASG"),
    ("POST", "/conversaciones/1/autorizacion", {"finalidad": "venta", "evidencia": "abcde"}, "ASG"),
    ("POST", "/conversaciones/1/tomar", None, "ASG"),
    ("POST", "/conversaciones/1/asignar", {"usuario_id": 1}, "AS"),
    ("POST", "/conversaciones/1/liberar", None, "ASG"),
    ("POST", "/conversaciones/1/cerrar", {}, "ASG"),
    ("GET", "/conversaciones/1/registros-candidatos", None, "ASG"),
    ("PUT", "/conversaciones/1/registro", {"campana_cliente_id": 1}, "ASG"),
    ("GET", "/atencion/cola", None, "ASG"),
    ("POST", "/atencion/tomar-siguiente", None, "G"),
    (
        "POST",
        "/consola/registros/1/whatsapp/plantilla",
        {"telefono_id": 1, "plantilla_id": 1, "idempotencia_clave": UUID},
        "G",
    ),  # fmt: skip
    ("POST", "/whatsapp/simulacion/entrante", {"numero": "3001234567"}, "ASG"),
    ("POST", "/whatsapp/simulacion/mensajes/1/estado", {"estado": "read"}, "ASG"),
    ("GET", "/supervision/trabajos", None, "AS"),
]
IDS = [f"{m} {r.split('?')[0]}" for m, r, _, _ in MATRIZ]


def llamar(client, metodo, ruta, cuerpo, headers=None):
    return client.request(metodo, API + ruta, json=cuerpo, headers=headers)


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "roles"), MATRIZ, ids=IDS)
def test_sin_token_401(client, metodo, ruta, cuerpo, roles):
    r = llamar(client, metodo, ruta, cuerpo)
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "NO_AUTENTICADO"


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "roles"), MATRIZ, ids=IDS)
def test_rol_no_permitido_403_y_permitido_pasa_el_control_de_rol(
    client, crear_usuario, metodo, ruta, cuerpo, roles
):
    for rol, letra in ROLES.items():
        r = llamar(client, metodo, ruta, cuerpo, cab(crear_usuario(rol)))
        if letra in roles:
            codigo = r.json().get("error", {}).get("codigo") if r.status_code >= 400 else None
            assert codigo != "PERMISO_DENEGADO", (rol, r.text)
            assert r.status_code != 401
        else:
            assert r.status_code == 403, (rol, r.status_code, r.text)
            assert r.json()["error"]["codigo"] == "PERMISO_DENEGADO"


@pytest.mark.parametrize("ruta", [RUTA_ENTRANTE, RUTA_ESTADO])
def test_webhooks_exigen_firma_no_jwt(client, h_admin, ruta):
    r = client.post(ruta, data={"MessageSid": "SM1"})
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "FIRMA_INVALIDA"
    # Un JWT válido no sustituye a la firma de Twilio.
    r = client.post(ruta, data={"MessageSid": "SM1"}, headers=h_admin)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "FIRMA_INVALIDA"


def test_el_agente_no_recibe_e164_en_ninguna_respuesta_de_conversaciones(
    client, db, esc, crear_usuario, reloj
):
    from wa import contexto, crear_conv

    from app.modulos.conversaciones.dueno import Humano

    ctx = contexto(esc, crear_usuario, reloj, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    for ruta in (
        "/conversaciones",
        f"/conversaciones/{conv.id}",
        f"/conversaciones/{conv.id}/mensajes",
        "/atencion/cola",
    ):
        r = client.get(API + ruta, headers=cab(ctx.agente))
        assert r.status_code == 200
        assert "3001234567" not in r.text and "+573001234567" not in r.text, ruta
    ficha = client.get(f"{API}/conversaciones/{conv.id}/ficha", headers=cab(ctx.agente))
    assert ficha.status_code == 200
    assert "numero_e164" not in ficha.text or "+573001234567" not in ficha.text
