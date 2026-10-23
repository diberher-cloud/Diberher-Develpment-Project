import pytest

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente, Cliente

BASE = {"nombre": "  Cobranza octubre ", "tipo": "cobranza"}


def crear(client, h, **extra):
    return client.post("/api/v1/campanas", json={**BASE, **extra}, headers=h)


def con_cliente(db, campana_id):
    cli = Cliente(tipo_documento="CC", numero_documento=f"1000{campana_id}", nombre="Ana Cliente")
    db.add(cli)
    db.flush()
    db.add(CampanaCliente(campana_id=campana_id, cliente_id=cli.id))
    db.commit()


def test_crear_y_obtener(client, h_admin, db):
    r = crear(client, h_admin, guion="Hola {{nombre}}")
    assert r.status_code == 201
    c = r.json()
    assert c["nombre"] == "Cobranza octubre" and c["estado"] == "borrador"
    assert c["max_intentos"] == 3 and c["intervalo_reintento_minutos"] == 60
    assert c["total_clientes"] == 0 and c["creado_en"].endswith("Z")
    assert client.get(f"/api/v1/campanas/{c['id']}", headers=h_admin).json() == c
    assert client.get("/api/v1/campanas/999", headers=h_admin).status_code == 404
    assert "campana.crear" in {a.accion for a in db.query(Auditoria)}


def test_nombre_duplicado_y_validaciones(client, h_admin):
    assert crear(client, h_admin).status_code == 201
    r = crear(client, h_admin, nombre="cobranza OCTUBRE")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"
    for extra in (
        {"nombre": "ab"}, {"max_intentos": 11}, {"intervalo_reintento_minutos": 4},
        {"fecha_inicio": "2026-11-02", "fecha_fin": "2026-11-01"}, {"tipo": "otro"},
    ):  # fmt: skip
        assert crear(client, h_admin, **{"nombre": "Nueva campaña", **extra}).status_code == 422


def test_tipo_no_editable(client, h_admin):
    cid = crear(client, h_admin).json()["id"]
    r = client.patch(f"/api/v1/campanas/{cid}", json={"tipo": "venta"}, headers=h_admin)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == "tipo"


def test_patch_fechas_y_nulos(client, h_admin):
    cid = crear(client, h_admin, fecha_inicio="2026-11-01", descripcion="x").json()["id"]
    r = client.patch(f"/api/v1/campanas/{cid}", json={"fecha_fin": "2026-10-01"}, headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "fecha_fin"
    r = client.patch(
        f"/api/v1/campanas/{cid}", json={"descripcion": None, "guion": "g"}, headers=h_admin
    )
    assert r.json()["descripcion"] is None and r.json()["guion"] == "g"


def test_transiciones(client, h_admin, db):
    cid = crear(client, h_admin).json()["id"]

    def estado(e):
        return client.patch(f"/api/v1/campanas/{cid}", json={"estado": e}, headers=h_admin)

    r = estado("activa")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_SIN_CLIENTES"
    assert estado("pausada").json()["error"]["codigo"] == "TRANSICION_INVALIDA"
    assert estado("borrador").status_code == 200  # misma: sin cambio
    con_cliente(db, cid)
    assert estado("activa").json()["estado"] == "activa"
    assert estado("activa").status_code == 200
    assert estado("borrador").json()["error"]["codigo"] == "TRANSICION_INVALIDA"
    assert estado("pausada").json()["estado"] == "pausada"
    assert estado("activa").json()["total_clientes"] == 1
    assert estado("pausada").status_code == 200
    assert estado("finalizada").json()["estado"] == "finalizada"
    for e in ("activa", "pausada"):
        assert estado(e).json()["error"]["codigo"] == "CAMPANA_FINALIZADA"
    r = client.patch(f"/api/v1/campanas/{cid}", json={"nombre": "Nuevo nombre"}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_FINALIZADA"
    assert "campana.estado" in {a.accion for a in db.query(Auditoria)}


def test_activa_a_finalizada_directa(client, h_admin, db):
    cid = crear(client, h_admin).json()["id"]
    con_cliente(db, cid)
    client.patch(f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin)
    r = client.patch(f"/api/v1/campanas/{cid}", json={"estado": "finalizada"}, headers=h_admin)
    assert r.status_code == 200


def test_eliminar(client, h_admin, db):
    a = crear(client, h_admin, nombre="Para borrar").json()["id"]
    b = crear(client, h_admin, nombre="Activa").json()["id"]
    con_cliente(db, b)
    client.patch(f"/api/v1/campanas/{b}", json={"estado": "activa"}, headers=h_admin)
    r = client.delete(f"/api/v1/campanas/{b}", headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_NO_ELIMINABLE"
    con_cliente(db, a)
    assert client.delete(f"/api/v1/campanas/{a}", headers=h_admin).status_code == 204
    assert client.get(f"/api/v1/campanas/{a}", headers=h_admin).status_code == 404
    assert db.query(CampanaCliente).filter_by(campana_id=a).count() == 0
    assert db.query(Cliente).count() == 2  # los clientes globales permanecen
    assert client.delete(f"/api/v1/campanas/{a}", headers=h_admin).status_code == 404


def test_listado_filtros_y_paginacion(client, h_admin, db):
    for i in range(3):
        crear(client, h_admin, nombre=f"Venta {i}", tipo="venta")
    crear(client, h_admin, nombre="Cobranza uno")
    r = client.get("/api/v1/campanas?tipo=venta&page_size=2", headers=h_admin).json()
    assert r["total"] == 3 and len(r["items"]) == 2 and r["items"][0]["nombre"] == "Venta 2"
    assert client.get("/api/v1/campanas?q=COBRANZA", headers=h_admin).json()["total"] == 1
    assert client.get("/api/v1/campanas?page_size=101", headers=h_admin).status_code == 422
    assert client.get("/api/v1/campanas?estado=borrador", headers=h_admin).json()["total"] == 4


def test_agente_solo_ve_activas_y_no_escribe(client, h_admin, h_agente, db):
    a = crear(client, h_admin, nombre="Borrador uno").json()["id"]
    b = crear(client, h_admin, nombre="Activa uno").json()["id"]
    con_cliente(db, b)
    client.patch(f"/api/v1/campanas/{b}", json={"estado": "activa"}, headers=h_admin)
    lista = client.get("/api/v1/campanas?estado=borrador", headers=h_agente).json()
    assert [c["id"] for c in lista["items"]] == [b]
    assert client.get(f"/api/v1/campanas/{b}", headers=h_agente).status_code == 200
    assert client.get(f"/api/v1/campanas/{a}", headers=h_agente).status_code == 404
    assert crear(client, h_agente).status_code == 403
    assert (
        client.patch(f"/api/v1/campanas/{b}", json={"guion": "x"}, headers=h_agente).status_code
        == 403
    )
    assert client.delete(f"/api/v1/campanas/{a}", headers=h_agente).status_code == 403


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_sin_token(client, metodo):
    assert getattr(client, metodo)("/api/v1/campanas").status_code == 401
