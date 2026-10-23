"""Matriz de permisos de fase-2.md §4.1 (rol x endpoint nuevo)."""

import pytest
from escenario import cab

API = "/api/v1"

# (método, ruta, cuerpo, roles permitidos)
MATRIZ = [
    ("GET", "/campanas/1/agentes", None, {"administrador", "supervisor"}),
    ("PUT", "/campanas/1/agentes", {"usuario_ids": []}, {"administrador", "supervisor"}),
    ("GET", "/campanas/1/tipificaciones", None, {"administrador", "supervisor"}),
    ("GET", "/consola/estado", None, {"agente"}),
    ("PUT", "/consola/estado", {"estado": "disponible"}, {"agente"}),
    ("GET", "/consola/campanas", None, {"agente"}),
    ("GET", "/consola/registros", None, {"agente"}),
    ("POST", "/consola/registros/1/tomar", None, {"agente"}),
    ("POST", "/consola/registros/1/soltar", None, {"agente"}),
    ("GET", "/consola/registros/1", None, {"agente"}),
    ("GET", "/consola/llamadas/1", None, {"agente"}),
    ("POST", "/consola/tipificaciones", {"llamada_id": 1, "resultado": "rechazo"}, {"agente"}),
    ("POST", "/telefonia/token", None, {"agente"}),
    (
        "POST",
        "/telefonia/simulacion/llamadas",
        {"campana_cliente_id": 1, "telefono_id": 1},
        {"agente"},
    ),
    ("POST", "/telefonia/simulacion/llamadas/1/eventos", {"evento": "contestada"}, {"agente"}),
    ("GET", "/supervision/agentes", None, {"administrador", "supervisor"}),
]
ROLES = ("administrador", "supervisor", "agente")


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "permitidos"), MATRIZ)
@pytest.mark.parametrize("rol", ROLES)
def test_matriz(client, crear_usuario, esc, rol, metodo, ruta, cuerpo, permitidos):
    esc.campana()  # existe la campaña 1
    headers = cab(crear_usuario(rol))
    r = client.request(metodo, API + ruta, json=cuerpo, headers=headers)
    if rol in permitidos:
        assert r.status_code != 403, (rol, ruta, r.text)
        assert r.status_code != 401
    else:
        assert r.status_code == 403, (rol, ruta)
        assert r.json()["error"]["codigo"] == "PERMISO_DENEGADO"


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo", "permitidos"), MATRIZ)
def test_sin_token_401(client, metodo, ruta, cuerpo, permitidos):
    r = client.request(metodo, API + ruta, json=cuerpo)
    assert r.status_code == 401


TWILIO = [
    "/telefonia/twiml/saliente",
    "/telefonia/twiml/aviso-grabacion",
    "/telefonia/twiml/dial-terminado",
    "/telefonia/webhooks/estado",
    "/telefonia/webhooks/grabacion",
]


@pytest.mark.parametrize("ruta", TWILIO)
@pytest.mark.parametrize("rol", ROLES)
def test_endpoints_de_twilio_no_aceptan_jwt(client, crear_usuario, rol, ruta):
    """Se autentican por firma, no por JWT: un JWT válido sin firma es 403 FIRMA_INVALIDA."""
    r = client.post(API + ruta, data={"CallSid": "CA1"}, headers=cab(crear_usuario(rol)))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "FIRMA_INVALIDA"


def test_evaluar_con_cliente_id_solo_admin_y_supervisor(client, esc, crear_usuario):
    cc = esc.registro(esc.campana())
    cuerpo = {"tipo_campana": "cobranza", "cliente_id": cc.cliente_id}
    agente = client.post(
        f"{API}/cumplimiento/evaluar", json=cuerpo, headers=cab(crear_usuario("agente"))
    )
    assert agente.status_code == 403 and agente.json()["error"]["codigo"] == "PERMISO_DENEGADO"
    for rol in ("administrador", "supervisor"):
        r = client.post(f"{API}/cumplimiento/evaluar", json=cuerpo, headers=cab(crear_usuario(rol)))
        assert r.status_code == 200
    # El agente sigue pudiendo evaluar solo horario (compatibilidad con Fase 1).
    sin = {"tipo_campana": "cobranza", "momento": "2026-10-23T10:00:00-05:00"}
    assert (
        client.post(
            f"{API}/cumplimiento/evaluar", json=sin, headers=cab(crear_usuario("agente"))
        ).status_code
        == 200
    )
