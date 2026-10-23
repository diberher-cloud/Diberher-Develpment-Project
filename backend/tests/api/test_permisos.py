"""Humo de la matriz de permisos de §4.1 (rol x endpoint). QA ampliará."""

import pytest

# (método, ruta, cuerpo) -> roles que NO deben recibir 401/403
MATRIZ = [
    ("get", "/usuarios", {"administrador"}),
    ("get", "/campanas", {"administrador", "supervisor", "agente"}),
    ("post", "/campanas", {"administrador", "supervisor"}),
    ("get", "/campanas/999/clientes", {"administrador", "supervisor"}),
    ("get", "/campanas/999/importaciones", {"administrador", "supervisor"}),
    ("get", "/exclusiones", {"administrador", "supervisor"}),
    ("get", "/cumplimiento/politicas", {"administrador", "supervisor", "agente"}),
    ("get", "/cumplimiento/politicas/venta/versiones", {"administrador", "supervisor"}),
    ("put", "/cumplimiento/politicas/venta", {"administrador"}),
    ("get", "/festivos?anio=2026", {"administrador", "supervisor", "agente"}),
    ("post", "/festivos/generar", {"administrador"}),
    ("post", "/cumplimiento/evaluar", {"administrador", "supervisor", "agente"}),
]


@pytest.mark.parametrize("rol", ["administrador", "supervisor", "agente"])
@pytest.mark.parametrize(("metodo", "ruta", "permitidos"), MATRIZ)
def test_matriz(client, crear_usuario, cabeceras, rol, metodo, ruta, permitidos):
    h = cabeceras(crear_usuario(rol))
    r = client.request(metodo.upper(), f"/api/v1{ruta}", headers=h, json={})
    if rol in permitidos:
        assert r.status_code not in (401, 403), r.text
    else:
        assert r.status_code == 403
        assert r.json()["error"]["codigo"] == "PERMISO_DENEGADO"


@pytest.mark.parametrize(("metodo", "ruta", "_p"), MATRIZ)
def test_sin_token(client, metodo, ruta, _p):
    r = client.request(metodo.upper(), f"/api/v1{ruta}", json={})
    assert r.status_code == 401 and r.json()["error"]["codigo"] == "NO_AUTENTICADO"
