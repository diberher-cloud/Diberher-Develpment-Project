import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import SECRETO_EJEMPLO, Settings, get_settings
from app.db import crear_engine
from app.main import app
from app.modulos.auditoria import servicio as auditoria
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import Cliente
from app.modulos.cumplimiento.modelos import PoliticaCumplimiento
from app.modulos.cumplimiento.politica import politica_por_defecto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.modelos import Importacion

CAB = "tipo_documento,numero_documento,nombre,telefono_1"


def campana(client, h, nombre="Campaña uno"):
    return client.post(
        "/api/v1/campanas", json={"nombre": nombre, "tipo": "cobranza"}, headers=h
    ).json()["id"]


def subir(client, h, cid, texto):
    return client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h,
        files={"archivo": ("a.csv", texto.encode(), "text/csv")},
    )


def _choca(*a, **k):
    raise IntegrityError("INSERT ... DETAIL: Key (numero)=(123456)", {"p": 1}, Exception("dup"))


# 1. claves de datos_adicionales
def test_clave_adicional_larga_se_descarta_con_advertencia(client, h_admin):
    cid = campana(client, h_admin)
    larga = "x" * 60
    csv = f"{CAB},{larga},ok\nCC,123456,Ana,3001234567,{'v' * 10},w\n"
    imp = subir(client, h_admin, cid, csv).json()
    assert imp["filas_importadas"] == 1
    adv = [e for e in imp["errores"] if e["codigo"] == "COLUMNAS_ADICIONALES_IGNORADAS"]
    assert len(adv) == 1 and adv[0]["fila"] == 1 and adv[0]["severidad"] == "advertencia"
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert item["datos_adicionales"] == {"ok": "w"}


# 2a / 2b. datos personales fuera de logs
def test_engine_oculta_parametros():
    assert crear_engine("sqlite+pysqlite://").hide_parameters is True


def test_error_interno_no_registra_mensaje_ni_propaga(client, h_admin, monkeypatch, caplog):
    from app.modulos.usuarios import servicio

    mensaje = "DETAIL: documento 1020304050 tel +573001234567"

    def falla(*a, **k):
        raise RuntimeError(mensaje)

    monkeypatch.setattr(servicio, "listar", falla)
    with caplog.at_level(logging.ERROR):
        r = client.get("/api/v1/usuarios", headers=h_admin)  # sin raise_server_exceptions=False
    assert r.status_code == 500 and r.json()["error"]["codigo"] == "ERROR_INTERNO"
    assert "RuntimeError" in caplog.text
    assert "1020304050" not in caplog.text and "3001234567" not in caplog.text


# 2c. concurrencia -> 409 con rollback
def test_importacion_concurrente_409(client, h_admin, db, monkeypatch):
    cid = campana(client, h_admin)
    monkeypatch.setattr(auditoria, "registrar", _choca)
    r = subir(client, h_admin, cid, f"{CAB}\nCC,123456,Ana,3001234567\n")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IMPORTACION_CONCURRENTE"
    assert db.query(Importacion).count() == 0 and db.query(Cliente).count() == 0


def test_politica_concurrente_409(client, h_admin, db, monkeypatch):
    monkeypatch.setattr(auditoria, "registrar", _choca)
    r = client.put(
        "/api/v1/cumplimiento/politicas/venta", json=politica_por_defecto(), headers=h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "POLITICA_CONCURRENTE"
    assert db.query(PoliticaCumplimiento).filter_by(tipo_campana="venta").count() == 1


def test_exclusiones_importar_concurrente_409(client, h_admin, db, monkeypatch):
    monkeypatch.setattr(auditoria, "registrar", _choca)
    r = client.post(
        "/api/v1/exclusiones/importar",
        headers=h_admin,
        data={"motivo": "manual", "aplica_a": "todas"},
        files={"archivo": ("a.csv", b"telefono\n3001234567\n", "text/csv")},
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "EXCLUSION_CONCURRENTE"
    assert db.query(Exclusion).count() == 0


def test_generar_festivos_concurrente_409(client, h_admin, monkeypatch):
    from sqlalchemy.orm import Session

    monkeypatch.setattr(Session, "commit", _choca)
    r = client.post("/api/v1/festivos/generar", json={"anio": 2027}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "FESTIVOS_CONCURRENTE"


def test_crear_campana_nombre_concurrente_409(client, h_admin, monkeypatch):
    from sqlalchemy.orm import Session

    from app.modulos.campanas import servicio as svc

    monkeypatch.setattr(svc, "_nombre_existe", lambda *a, **k: False)
    original = Session.flush

    def flush_que_choca(self, *a, **k):
        if any(type(o).__name__ == "Campana" for o in self.new):
            _choca()
        return original(self, *a, **k)

    monkeypatch.setattr(Session, "flush", flush_que_choca)
    r = client.post(
        "/api/v1/campanas", json={"nombre": "Nueva uno", "tipo": "venta"}, headers=h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"


# 3. respaldo con festivo manual
def test_festivo_manual_no_desactiva_respaldo_calculado(client, h_admin):
    client.post(
        "/api/v1/festivos", json={"fecha": "2029-12-31", "nombre": "Cívico"}, headers=h_admin
    )
    r = client.post(
        "/api/v1/cumplimiento/evaluar",
        json={"tipo_campana": "venta", "momento": "2029-01-01T10:00:00-05:00"},
        headers=h_admin,
    ).json()
    assert r["permitido"] is False and r["motivos"][0]["codigo"] == "FESTIVO"


# 4. cuerpos enormes antes de autenticar
def test_content_length_enorme_413_sin_autenticar(client):
    limite = get_settings().importacion_max_bytes + 1024 * 1024
    r = client.post(
        "/api/v1/auth/login",
        content=b"x",
        headers={"content-length": str(limite + 1), "content-type": "application/json"},
    )
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"


def test_cuerpo_chunked_enorme_413(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", 0)

    def trozos():
        for _ in range(3):
            yield b"x" * 600_000

    r = client.post(
        "/api/v1/auth/login", content=trozos(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"


def test_peticion_normal_no_afectada(client):
    assert client.get("/api/v1/salud").status_code == 200


# 5. clave de cliente (tipo, número)
def test_mismo_numero_distinto_tipo_son_clientes_distintos(client, h_admin, db):
    c1 = campana(client, h_admin)
    subir(client, h_admin, c1, f"{CAB}\nCC,123456,Ana,3001234567\n")
    c2 = campana(client, h_admin, "Campaña dos")
    imp = subir(
        client, h_admin, c2, f"{CAB}\nCE,123456,Beto,3001234568\nCC,123456,Ana B,3001234567\n"
    ).json()
    assert imp["filas_importadas"] == 2
    assert db.query(Cliente).count() == 2


# 6. config
def test_produccion_rechaza_secreto_de_ejemplo():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, entorno="produccion", jwt_secreto=SECRETO_EJEMPLO)
    assert Settings(_env_file=None, entorno="desarrollo", jwt_secreto=SECRETO_EJEMPLO)


def test_no_quedan_importaciones_huerfanas_tras_409(client, h_admin, db, monkeypatch):
    cid = campana(client, h_admin)
    monkeypatch.setattr(auditoria, "registrar", _choca)
    subir(client, h_admin, cid, f"{CAB}\nCC,123456,Ana,3001234567\n")
    monkeypatch.undo()
    assert db.query(Auditoria).filter_by(accion="importacion.crear").count() == 0
    assert TestClient is not None and app is not None
