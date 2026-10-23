from pathlib import Path

import pytest

from app.config import get_settings
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.modelos import Importacion, ImportacionError

FIXTURES = Path(__file__).parent.parent / "fixtures"
CAB = "tipo_documento,numero_documento,nombre,telefono_1\n"


def nueva_campana(client, h, nombre="Campaña", tipo="cobranza"):
    return client.post("/api/v1/campanas", json={"nombre": nombre, "tipo": tipo}, headers=h).json()[
        "id"
    ]


def subir(client, h, cid, contenido, nombre="datos.csv"):
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")
    return client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h,
        files={"archivo": (nombre, contenido, "text/csv")},
    )


def excluir(db, numero, aplica_a, creado_por):
    db.add(Exclusion(numero_e164=numero, motivo="manual", aplica_a=aplica_a, creado_por=creado_por))
    db.commit()


def test_fixture_mixto(client, h_admin, admin, db):
    excluir(db, "+573005550000", "cobranza", admin.id)
    excluir(db, "+573007771111", "venta", admin.id)  # no aplica a cobranza
    cid = nueva_campana(client, h_admin)
    r = subir(client, h_admin, cid, (FIXTURES / "cobranza_mixta.csv").read_bytes())
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["total_filas"] == 7
    assert (imp["filas_importadas"], imp["filas_duplicadas"], imp["filas_invalidas"],
            imp["filas_excluidas"]) == (3, 1, 2, 1)  # fmt: skip
    suma = sum(
        imp[k]
        for k in ("filas_importadas", "filas_duplicadas", "filas_invalidas", "filas_excluidas")
    )
    assert suma == imp["total_filas"]
    codigos = {(e["fila"], e["codigo"], e["severidad"]) for e in imp["errores"]}
    assert (3, "TELEFONO_INVALIDO", "advertencia") in codigos  # abc, pero telefono_2 es válido
    assert (4, "DUPLICADO_EN_ARCHIVO", "advertencia") in codigos
    assert (5, "SIN_TELEFONO_VALIDO", "error") in codigos
    assert (5, "TELEFONO_REQUERIDO", "error") in codigos
    assert (6, "MONTO_INVALIDO", "error") in codigos
    assert (7, "TODOS_TELEFONOS_EXCLUIDOS", "advertencia") in codigos
    assert imp["errores_truncados"] is False
    # Sin datos personales completos en los mensajes
    assert all(
        "1020304050" not in e["mensaje"] and "3005550000" not in e["mensaje"]
        for e in imp["errores"]
    )
    assert db.query(ImportacionError).count() == len(imp["errores"])

    clientes = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()
    assert clientes["total"] == 3
    maria = clientes["items"][0]
    assert maria["cliente"]["numero_documento"] == "1020304050"
    assert maria["saldo_total"] == "1500000.00" and maria["saldo_mora"] == "250000.50"
    assert maria["dias_mora"] == 45 and maria["fecha_vencimiento"] == "2026-09-15"
    assert maria["datos_adicionales"] == {"segmento": "A"}
    assert [t["numero_e164"] for t in maria["telefonos"]] == ["+573001234567", "+576012345678"]
    assert [t["prioridad"] for t in maria["telefonos"]] == [1, 2]
    juan = clientes["items"][1]
    assert [(t["numero_e164"], t["prioridad"]) for t in juan["telefonos"]] == [("+573109876543", 2)]
    parcial = clientes["items"][2]
    assert [(t["numero_e164"], t["excluido"]) for t in parcial["telefonos"]] == [
        ("+573005550000", True), ("+573007771111", False)]  # fmt: skip
    assert "TELEFONO_EXCLUIDO" in {e["codigo"] for e in imp["errores"] if e["fila"] == 9}
    assert any(a.accion == "importacion.crear" for a in db.query(Auditoria))


def test_segunda_importacion_y_cliente_global(client, h_admin, db):
    c1 = nueva_campana(client, h_admin, "Uno")
    c2 = nueva_campana(client, h_admin, "Dos", "venta")
    csv = CAB + "CC,123456,Ana Uno,3001234567\n"
    assert subir(client, h_admin, c1, csv).json()["filas_importadas"] == 1
    again = subir(client, h_admin, c1, csv).json()
    assert (
        again["filas_duplicadas"] == 1 and again["errores"][0]["codigo"] == "DUPLICADO_EN_CAMPANA"
    )
    # Misma persona en otra campaña, con nombre y email actualizados y teléfono nuevo
    csv2 = (
        CAB.rstrip()
        + ",telefono_2,email,ciudad\nCC,123.456,Ana Dos,3001234567,3109998877,ana@x.co,Cali\n"
    )
    assert subir(client, h_admin, c2, csv2).json()["filas_importadas"] == 1
    assert db.query(Cliente).count() == 1
    cli = db.query(Cliente).one()
    assert (cli.nombre, cli.email, cli.ciudad) == ("Ana Dos", "ana@x.co", "Cali")
    assert db.query(Telefono).count() == 2
    assert db.query(CampanaCliente).count() == 2
    # Una actualización posterior con email/ciudad vacíos no los borra
    c3 = nueva_campana(client, h_admin, "Tres")
    subir(client, h_admin, c3, CAB + "CC,123456,Ana Tres,3001234567\n")
    db.expire_all()
    assert (db.query(Cliente).one().email, db.query(Cliente).one().ciudad) == ("ana@x.co", "Cali")


def test_exclusion_venta_rne(client, h_admin, admin, db):
    excluir(db, "+573001234567", "venta", admin.id)
    cv = nueva_campana(client, h_admin, "Venta uno", "venta")
    cc = nueva_campana(client, h_admin, "Cobranza uno", "cobranza")
    csv = CAB + "CC,123456,Ana,3001234567\n"
    rv = subir(client, h_admin, cv, csv).json()
    assert rv["filas_excluidas"] == 1 and rv["filas_importadas"] == 0
    assert "venta" in rv["errores"][0]["mensaje"]
    assert subir(client, h_admin, cc, csv).json()["filas_importadas"] == 1


def test_venta_columnas_de_cobranza_van_a_adicionales(client, h_admin):
    cid = nueva_campana(client, h_admin, "Venta uno", "venta")
    csv = (
        CAB.rstrip()
        + ",producto,oferta,saldo_total\nCC,123456,Ana,3001234567,Plan A,10% dto,1.000\n"
    )
    assert subir(client, h_admin, cid, csv).json()["filas_importadas"] == 1
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert item["producto"] == "Plan A" and item["oferta"] == "10% dto"
    assert item["saldo_total"] is None and item["datos_adicionales"] == {"saldo_total": "1.000"}


def test_errores_a_nivel_de_archivo(client, h_admin, db):
    cid = nueva_campana(client, h_admin)
    r = subir(client, h_admin, cid, "x", "datos.txt")
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "FORMATO_ARCHIVO_INVALIDO"
    r = subir(client, h_admin, cid, "tipo_documento,nombre\nCC,A\n")
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "COLUMNAS_FALTANTES"
    assert {"campo": "telefono_1", "mensaje": "Columna obligatoria ausente."} in r.json()["error"][
        "detalles"
    ]
    assert subir(client, h_admin, cid, CAB).json()["error"]["codigo"] == "ARCHIVO_VACIO"
    assert db.query(Importacion).count() == 0
    assert subir(client, h_admin, 999, CAB).status_code == 404
    r = client.post(f"/api/v1/campanas/{cid}/importaciones", headers=h_admin)
    assert r.status_code == 422


def test_limites_de_tamano_y_filas(client, h_admin, monkeypatch):
    cid = nueva_campana(client, h_admin)
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", 50)
    r = subir(client, h_admin, cid, CAB + "CC,123456,Ana,3001234567\n" * 3)
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", 10_000)
    monkeypatch.setattr(get_settings(), "importacion_max_filas", 2)
    r = subir(
        client, h_admin, cid, CAB + "".join(f"CC,12345{i},Ana,3001234567\n" for i in range(3))
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "DEMASIADAS_FILAS"


def test_campana_finalizada(client, h_admin, db):
    cid = nueva_campana(client, h_admin)
    subir(client, h_admin, cid, CAB + "CC,123456,Ana,3001234567\n")
    client.patch(f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin)
    client.patch(f"/api/v1/campanas/{cid}", json={"estado": "finalizada"}, headers=h_admin)
    r = subir(client, h_admin, cid, CAB + "CC,654321,Beto,3001234568\n")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_FINALIZADA"


def test_errores_truncados_y_detalle_paginado(client, h_admin):
    cid = nueva_campana(client, h_admin)
    filas = "".join(f"XX,{i},Ana,3001234567\n" for i in range(120))
    imp = subir(client, h_admin, cid, CAB + filas).json()
    assert imp["filas_invalidas"] == 120 and len(imp["errores"]) == 100 and imp["errores_truncados"]
    assert imp["errores"][0]["fila"] == 2
    lista = client.get(f"/api/v1/campanas/{cid}/importaciones", headers=h_admin).json()
    assert lista["total"] == 1 and "errores" not in lista["items"][0]
    det = client.get(f"/api/v1/importaciones/{imp['id']}", headers=h_admin).json()
    assert det["id"] == imp["id"] and "errores" not in det
    e = client.get(
        f"/api/v1/importaciones/{imp['id']}/errores?page=2&page_size=100&severidad=error",
        headers=h_admin,
    ).json()
    assert e["total"] == 120 and len(e["items"]) == 20 and e["items"][0]["fila"] == 102
    assert client.get("/api/v1/importaciones/999", headers=h_admin).status_code == 404
    assert client.get("/api/v1/importaciones/999/errores", headers=h_admin).status_code == 404


def test_rollback_ante_error_inesperado(client, h_admin, db, monkeypatch):
    from app.modulos.importacion import servicio

    cid = nueva_campana(client, h_admin)

    def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(servicio, "_guardar", falla)
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        r = subir(c, h_admin, cid, CAB + "CC,123456,Ana,3001234567\n")
    assert r.status_code == 500
    assert db.query(Importacion).count() == 0 and db.query(Cliente).count() == 0


def test_columnas_adicionales_limite(client, h_admin):
    cid = nueva_campana(client, h_admin)
    extra = [f"x{i}" for i in range(22)]
    csv = (
        CAB.rstrip()
        + ","
        + ",".join(extra)
        + "\nCC,123456,Ana,3001234567,"
        + ",".join("v" * 22)
        + "\n"
    )
    imp = subir(client, h_admin, cid, csv).json()
    assert (
        imp["errores"][0]["codigo"] == "COLUMNAS_ADICIONALES_IGNORADAS"
        and imp["errores"][0]["fila"] == 1
    )
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert len(item["datos_adicionales"]) == 20


def test_busqueda_de_clientes(client, h_admin):
    cid = nueva_campana(client, h_admin)
    subir(
        client,
        h_admin,
        cid,
        CAB + "CC,123456,María Pérez,3001234567\nCC,654321,Otro Cliente,3109998877\n",
    )

    def n(q):
        return client.get(
            f"/api/v1/campanas/{cid}/clientes", params={"q": q}, headers=h_admin
        ).json()["total"]

    assert n("pérez") == 1 and n("MARÍA") == 1
    assert n("mar") == 1 and n("654321") == 1 and n("310 999 8877") == 1 and n("zzz") == 0
    assert (
        client.get(f"/api/v1/campanas/{cid}/clientes?estado=pendiente", headers=h_admin).json()[
            "total"
        ]
        == 2
    )
    assert client.get("/api/v1/campanas/999/clientes", headers=h_admin).status_code == 404


@pytest.mark.parametrize(
    "ruta", ["/campanas/1/importaciones", "/campanas/1/clientes", "/importaciones/1"]
)
def test_agente_sin_acceso(client, h_agente, ruta):
    assert client.get(f"/api/v1{ruta}", headers=h_agente).status_code == 403


def test_agente_no_importa(client, h_agente):
    assert subir(client, h_agente, 1, CAB).status_code == 403
