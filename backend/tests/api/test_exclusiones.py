from app.modulos.auditoria.modelos import Auditoria

URL = "/api/v1/exclusiones"


def alta(client, h, **extra):
    cuerpo = {"telefono": "300 123 4567", "motivo": "manual", "aplica_a": "todas", **extra}
    return client.post(URL, json=cuerpo, headers=h)


def test_alta_normaliza_y_duplicado(client, h_admin, db):
    r = alta(client, h_admin, observacion="x")
    assert r.status_code == 201
    e = r.json()
    assert (
        e["numero_e164"] == "+573001234567"
        and e["aplica_a"] == "todas"
        and e["creado_en"].endswith("Z")
    )
    d = alta(client, h_admin, telefono="+57 3001234567")
    assert d.status_code == 409 and d.json()["error"]["codigo"] == "EXCLUSION_DUPLICADA"
    assert alta(client, h_admin, aplica_a="venta").status_code == 201  # otra finalidad
    aud = db.query(Auditoria).filter_by(accion="exclusion.crear").all()
    assert len(aud) == 2 and "3001234567" not in str([a.detalle for a in aud])


def test_rne_por_defecto_venta_y_aplica_a_obligatorio(client, h_admin):
    r = client.post(URL, json={"telefono": "3001234567", "motivo": "rne"}, headers=h_admin)
    assert r.status_code == 201 and r.json()["aplica_a"] == "venta"
    r = client.post(URL, json={"telefono": "3001234568", "motivo": "manual"}, headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "aplica_a"


def test_telefono_invalido(client, h_admin):
    r = alta(client, h_admin, telefono="12345")
    assert r.status_code == 422
    d = r.json()["error"]["detalles"][0]
    assert d["campo"] == "telefono" and d["mensaje"].startswith("TELEFONO_INVALIDO")


def test_listar_filtrar_eliminar(client, h_admin, db):
    alta(client, h_admin)
    alta(client, h_admin, telefono="3109998877", motivo="rne", aplica_a="venta")
    assert client.get(URL, headers=h_admin).json()["total"] == 2
    assert client.get(f"{URL}?q=310 999 8877", headers=h_admin).json()["total"] == 1
    assert client.get(f"{URL}?q=basura", headers=h_admin).json() == {
        "items": [], "total": 0, "page": 1, "page_size": 20}  # fmt: skip
    assert client.get(f"{URL}?motivo=rne", headers=h_admin).json()["total"] == 1
    assert client.get(f"{URL}?aplica_a=todas", headers=h_admin).json()["total"] == 1
    eid = client.get(f"{URL}?motivo=rne", headers=h_admin).json()["items"][0]["id"]
    assert client.delete(f"{URL}/{eid}", headers=h_admin).status_code == 204
    assert client.delete(f"{URL}/{eid}", headers=h_admin).status_code == 404
    assert db.query(Auditoria).filter_by(accion="exclusion.eliminar").count() == 1


def test_importacion_masiva(client, h_supervisor, db):
    csv = "Teléfono\n3001234567\n300 123 4567\n3109998877\nabc\n\n6012345678\n"
    # La columna debe llamarse `telefono` tras normalizar la cabecera.
    r = client.post(
        f"{URL}/importar", headers=h_supervisor, data={"motivo": "rne"},
        files={"archivo": ("rne.csv", csv.encode(), "text/csv")},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["total_filas"], res["creadas"], res["duplicadas"], res["invalidas"]) == (5, 3, 1, 1)
    assert res["errores"] == [
        {"fila": 5, "campo": "telefono", "codigo": "TELEFONO_INVALIDO",
         "mensaje": "Teléfono inválido (***abc).", "severidad": "error"}
    ]  # fmt: skip
    assert res["errores_truncados"] is False
    # Repetir: todo duplicado (aplica_a por defecto venta)
    r2 = client.post(
        f"{URL}/importar", headers=h_supervisor, data={"motivo": "rne", "aplica_a": "venta"},
        files={"archivo": ("rne.csv", csv.encode(), "text/csv")},
    )  # fmt: skip
    assert r2.json()["creadas"] == 0 and r2.json()["duplicadas"] == 4
    assert db.query(Auditoria).filter_by(accion="exclusion.importar").count() == 2


def test_importacion_masiva_errores_de_archivo(client, h_admin):
    def post(nombre, contenido, **data):
        return client.post(
            f"{URL}/importar", headers=h_admin, data=data,
            files={"archivo": (nombre, contenido, "text/csv")},
        )  # fmt: skip

    assert post("a.txt", b"telefono\n1", motivo="rne").status_code == 422
    assert post("a.csv", b"tel\n1", motivo="rne").json()["error"]["codigo"] == "COLUMNAS_FALTANTES"
    r = post("a.csv", b"telefono\n3001234567", motivo="manual")
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "aplica_a"
    assert post("a.csv", b"telefono\n3001234567", motivo="otro").status_code == 422


def test_permisos(client, h_agente):
    assert client.get(URL, headers=h_agente).status_code == 403
    assert alta(client, h_agente).status_code == 403
    assert client.delete(f"{URL}/1", headers=h_agente).status_code == 403
