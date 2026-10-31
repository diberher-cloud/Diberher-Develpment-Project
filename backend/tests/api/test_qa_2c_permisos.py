"""QA 2C: barrido de TODAS las rutas de la aplicación (no solo las conocidas) y permisos de las
rutas del agente IA para el rol `agente` con identificadores ajenos o inexistentes."""

import re

import pytest

from app.main import app

API = "/api/v1"
PUBLICAS = re.compile(
    r"^/api/v1/(auth/|salud|health|whatsapp/webhooks/|telefonia/webhooks/|webhooks/|openapi)|"
    r"^/(docs|redoc|openapi\.json)|^/api/v1/ws|^/ws"
)


def _rutas():
    for r in app.routes:
        path = getattr(r, "path", "")
        for metodo in sorted(getattr(r, "methods", None) or ()):
            if metodo in ("HEAD", "OPTIONS"):
                continue
            yield metodo, path


RUTAS = sorted(set(_rutas()))


def _url(path):
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.parametrize("metodo,path", RUTAS)
def test_toda_ruta_privada_exige_token(client, metodo, path):
    if PUBLICAS.match(path) or "websocket" in path:
        pytest.skip("ruta pública por diseño (webhook firmado, login, salud o WebSocket)")
    r = client.request(metodo, _url(path), json={})
    assert r.status_code in (401, 403), (metodo, path, r.status_code)


RUTAS_IA_SOLO_GESTION = [
    ("GET", "/campanas/1/ia"), ("PUT", "/campanas/1/ia"), ("POST", "/campanas/1/ia/activar"),
    ("POST", "/campanas/1/ia/desactivar"), ("GET", "/campanas/1/ofertas"),
    ("POST", "/campanas/1/ofertas"), ("PATCH", "/campanas/1/ofertas/1"),
    ("GET", "/configuracion/ia"), ("PUT", "/configuracion/ia"), ("POST", "/ia/evaluaciones"),
    ("GET", "/ia/evaluaciones"), ("GET", "/ia/evaluaciones/1"),
    ("GET", "/supervision/ia/conversaciones"), ("GET", "/supervision/ia/metricas"),
    ("GET", "/conversaciones/1/instrucciones"), ("POST", "/conversaciones/1/instrucciones"),
    ("GET", "/conversaciones/1/uso-ia"), ("GET", "/conversaciones/1/historial-ia"),
    ("POST", "/conversaciones/1/traspasar"),
    ("POST", "/conversaciones/1/asignar"),
]  # fmt: skip


@pytest.mark.parametrize("metodo,ruta", RUTAS_IA_SOLO_GESTION)
def test_agente_no_accede_a_rutas_de_gestion_de_ia(client, h_agente, metodo, ruta):
    r = client.request(metodo, API + ruta, headers=h_agente, json={})
    assert r.status_code == 403, (metodo, ruta, r.status_code, r.text[:200])


@pytest.mark.parametrize("ruta", ["acciones-ia"])
def test_agente_con_conversacion_inexistente_o_ajena_no_filtra(client, h_agente, ruta):
    for cid in (1, 999999):
        r = client.get(f"{API}/conversaciones/{cid}/{ruta}", headers=h_agente)
        assert r.status_code in (403, 404), r.status_code
        assert "saldo" not in r.text.lower()


def test_ninguna_ruta_de_ia_acepta_cliente_id_en_el_cuerpo(client, h_admin):
    """Los esquemas de entrada prohíben propiedades extra: un `cliente_id` se rechaza (422)."""
    for metodo, ruta in [("PUT", "/campanas/1/ia"), ("POST", "/conversaciones/1/instrucciones"),
                         ("POST", "/ia/evaluaciones"), ("POST", "/campanas/1/ofertas"),
                         ("PUT", "/configuracion/ia")]:  # fmt: skip
        r = client.request(metodo, API + ruta, headers=h_admin, json={"cliente_id": 10})
        assert r.status_code in (404, 409, 422), (ruta, r.status_code)
        assert r.status_code != 200 and r.status_code != 201
