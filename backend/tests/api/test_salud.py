def test_salud(client):
    r = client.get("/api/v1/salud")
    assert r.status_code == 200
    assert r.json() == {"estado": "ok", "version": "0.1.0"}


def test_404_formato_comun(client):
    r = client.get("/api/v1/no-existe")
    assert r.status_code == 404
    assert r.json() == {
        "error": {"codigo": "NO_ENCONTRADO", "mensaje": "Recurso no encontrado.", "detalles": []}
    }


def test_422_formato_comun(client, h_admin):
    r = client.post("/api/v1/campanas", json={"nombre": "x"}, headers=h_admin)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["codigo"] == "VALIDACION"
    campos = {d["campo"] for d in err["detalles"]}
    assert {"nombre", "tipo"} <= campos


def test_error_interno_sin_trazas(client, h_admin, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.modulos.usuarios import servicio

    def _falla(*a, **k):
        raise RuntimeError("secreto interno")

    monkeypatch.setattr(servicio, "listar", _falla)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/v1/usuarios", headers=h_admin)
    assert r.status_code == 500
    assert r.json()["error"]["codigo"] == "ERROR_INTERNO"
    assert "secreto" not in r.text
