from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from app.modulos.auditoria.modelos import Auditoria

PASSWORD = "ClaveSegura123"


def _login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_login_ok_y_me(client, admin):
    r = _login(client, admin.email.upper())
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer" and cuerpo["expires_in"] == 480 * 60
    assert cuerpo["usuario"]["rol"] == "administrador"
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {cuerpo['access_token']}"}
    )
    assert me.status_code == 200 and me.json()["email"] == admin.email


def test_login_fallido_y_auditoria(client, admin, db):
    r = _login(client, admin.email, "otra-clave-larga")
    assert r.status_code == 401 and r.json()["error"]["codigo"] == "CREDENCIALES_INVALIDAS"
    r2 = _login(client, "nadie@empresa.co")
    assert r2.json()["error"] == r.json()["error"]
    acciones = [a.accion for a in db.query(Auditoria).order_by(Auditoria.id)]
    assert acciones == ["auth.login_fallido", "auth.login_fallido"]
    assert all("password" not in str(a.detalle) for a in db.query(Auditoria))


def test_login_ok_audita(client, admin, db):
    _login(client, admin.email)
    assert [a.accion for a in db.query(Auditoria)] == ["auth.login_ok"]


def test_login_usuario_inactivo(client, crear_usuario):
    u = crear_usuario("agente", activo=False)
    assert _login(client, u.email).status_code == 401


def test_login_validacion(client):
    r = client.post("/api/v1/auth/login", json={"email": "no-email", "password": ""})
    assert r.status_code == 422


def test_sin_token_y_token_invalido(client):
    assert client.get("/api/v1/auth/me").json()["error"]["codigo"] == "NO_AUTENTICADO"
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


def test_token_expirado_y_firma_ajena(client, admin):
    s = get_settings()
    ahora = datetime.now(UTC)
    base = {"sub": str(admin.id), "rol": admin.rol, "iat": ahora}
    expirado = jwt.encode({**base, "exp": ahora - timedelta(minutes=1)}, s.jwt_secreto, "HS256")
    ajeno = jwt.encode({**base, "exp": ahora + timedelta(hours=1)}, "otro-secreto" * 4, "HS256")
    for token in (expirado, ajeno):
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401 and r.json()["error"]["codigo"] == "NO_AUTENTICADO"


def test_usuario_desactivado_con_token_vigente(client, admin, h_admin, db):
    admin.activo = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=h_admin).status_code == 401


def test_rol_efectivo_se_lee_de_bd(client, crear_usuario, cabeceras, db):
    u = crear_usuario("administrador")
    h = cabeceras(u)  # token emitido como administrador
    u.rol = "agente"
    db.commit()
    assert client.get("/api/v1/usuarios", headers=h).status_code == 403
