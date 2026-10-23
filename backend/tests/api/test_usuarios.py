from app.modulos.auditoria.modelos import Auditoria

NUEVO = {
    "email": "Agente1@Empresa.co", "nombre": "Pedro Agente", "rol": "agente",
    "password": "ClaveSegura123",
}  # fmt: skip


def test_crud(client, h_admin, db):
    r = client.post("/api/v1/usuarios", json=NUEVO, headers=h_admin)
    assert r.status_code == 201
    u = r.json()
    assert u["email"] == "agente1@empresa.co" and u["activo"] is True and "password" not in u
    assert u["creado_en"].endswith("Z")

    dup = client.post("/api/v1/usuarios", json=NUEVO, headers=h_admin)
    assert dup.status_code == 409 and dup.json()["error"]["codigo"] == "EMAIL_DUPLICADO"

    p = client.patch(
        f"/api/v1/usuarios/{u['id']}", json={"rol": "supervisor", "activo": False}, headers=h_admin
    )
    assert p.status_code == 200 and p.json()["rol"] == "supervisor" and p.json()["activo"] is False

    lista = client.get("/api/v1/usuarios?rol=supervisor&activo=false", headers=h_admin).json()
    assert lista["total"] == 1 and lista["page"] == 1 and lista["page_size"] == 20
    assert (
        client.patch("/api/v1/usuarios/9999", json={"activo": True}, headers=h_admin).status_code
        == 404
    )

    acciones = {a.accion for a in db.query(Auditoria)}
    assert "usuario.crear" in acciones
    assert all("empresa.co" not in str(a.detalle) for a in db.query(Auditoria))


def test_nuevo_usuario_puede_iniciar_sesion(client, h_admin):
    client.post("/api/v1/usuarios", json=NUEVO, headers=h_admin)
    r = client.post(
        "/api/v1/auth/login", json={"email": "agente1@empresa.co", "password": NUEVO["password"]}
    )
    assert r.status_code == 200


def test_validaciones(client, h_admin):
    malo = {"email": "x", "nombre": "A", "rol": "root", "password": "corta"}
    r = client.post("/api/v1/usuarios", json=malo, headers=h_admin)
    assert r.status_code == 422
    assert {d["campo"] for d in r.json()["error"]["detalles"]} == {
        "email",
        "nombre",
        "rol",
        "password",
    }


def test_admin_no_puede_desactivarse_ni_quitarse_rol(client, admin, h_admin):
    for cuerpo in ({"activo": False}, {"rol": "supervisor"}):
        r = client.patch(f"/api/v1/usuarios/{admin.id}", json=cuerpo, headers=h_admin)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "NO_PUEDE_DESACTIVARSE"
    assert (
        client.patch(
            f"/api/v1/usuarios/{admin.id}", json={"nombre": "Otro Nombre"}, headers=h_admin
        ).status_code
        == 200
    )


def test_solo_admin(client, h_supervisor, h_agente):
    for h in (h_supervisor, h_agente):
        assert client.get("/api/v1/usuarios", headers=h).status_code == 403
        assert client.post("/api/v1/usuarios", json=NUEVO, headers=h).status_code == 403
