"""Matriz de permisos completa de §4.1: rol x endpoint, con peticiones VÁLIDAS.

A diferencia de `test_permisos.py` (humo con cuerpo vacío), aquí cada endpoint recibe una
petición correcta sobre datos reales, de modo que:
- el rol autorizado obtiene el código de éxito esperado (no solo "no 401/403");
- el rol no autorizado obtiene 403 `PERMISO_DENEGADO` con el formato de error común;
- sin token se obtiene 401 `NO_AUTENTICADO`.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.usuarios.modelos import Usuario
from app.seguridad import hash_password

A, S, G = "administrador", "supervisor", "agente"
TODOS = {A, S, G}
GESTORES = {A, S}
SOLO_ADMIN = {A}

CSV = b"tipo_documento,numero_documento,nombre,telefono_1\nCC,123456,Ana Cliente,3001234567\n"


@dataclass
class Datos:
    campana_id: int
    importacion_id: int
    exclusion_id: int
    festivo_id: int
    otro_usuario_id: int
    politica: dict[str, Any] = field(default_factory=dict)


@pytest.fixture()
def datos(client, db, admin, h_admin) -> Datos:
    """Una campaña activa con una importación, una exclusión, un festivo y otro usuario."""
    cid = client.post(
        "/api/v1/campanas", json={"nombre": "Base permisos", "tipo": "cobranza"}, headers=h_admin
    ).json()["id"]
    imp = client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={"archivo": ("a.csv", CSV, "text/csv")},
    ).json()
    assert (
        client.patch(
            f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin
        ).status_code
        == 200
    )
    excl = Exclusion(numero_e164="+573009998877", motivo="manual", aplica_a="todas",
                     creado_por=admin.id)  # fmt: skip
    db.add(excl)
    otro = Usuario(email="otro@empresa.co", nombre="Otro Usuario", rol="agente",
                   password_hash=hash_password("ClaveSegura123"))  # fmt: skip
    db.add(otro)
    db.commit()
    fid = client.post(
        "/api/v1/festivos", json={"fecha": "2026-12-31", "nombre": "Cívico"}, headers=h_admin
    ).json()["id"]
    politica = client.get("/api/v1/cumplimiento/politicas", headers=h_admin).json()[0][
        "configuracion"
    ]
    return Datos(cid, imp["id"], excl.id, fid, otro.id, politica)


# (nombre, método, ruta (con {campos de Datos}), kwargs de la petición, roles permitidos, éxito)
def _ep(nombre, metodo, ruta, roles, exito, **kw):
    return pytest.param(metodo, ruta, kw, roles, exito, id=nombre)


ENDPOINTS = [
    _ep("auth_me", "get", "/auth/me", TODOS, 200),
    _ep("usuarios_listar", "get", "/usuarios", SOLO_ADMIN, 200),
    _ep(
        "usuarios_crear",
        "post",
        "/usuarios",
        SOLO_ADMIN,
        201,
        json={
            "email": "nuevo@empresa.co",
            "nombre": "Nuevo Usuario",
            "rol": "agente",
            "password": "ClaveSegura123",
        },
    ),  # fmt: skip
    _ep(
        "usuarios_patch",
        "patch",
        "/usuarios/{otro_usuario_id}",
        SOLO_ADMIN,
        200,
        json={"nombre": "Renombrado"},
    ),  # fmt: skip
    _ep("campanas_listar", "get", "/campanas", TODOS, 200),
    _ep(
        "campanas_crear",
        "post",
        "/campanas",
        GESTORES,
        201,
        json={"nombre": "Otra campaña", "tipo": "venta"},
    ),  # fmt: skip
    # La campaña base está activa, así que el agente también puede leerla.
    _ep("campanas_obtener_activa", "get", "/campanas/{campana_id}", TODOS, 200),
    _ep("campanas_patch", "patch", "/campanas/{campana_id}", GESTORES, 200, json={"guion": "x"}),
    _ep(
        "campanas_estado",
        "patch",
        "/campanas/{campana_id}",
        GESTORES,
        200,
        json={"estado": "pausada"},
    ),  # fmt: skip
    # DELETE sobre una campaña activa: el gestor llega al 409 de negocio (no al 403).
    _ep("campanas_eliminar", "delete", "/campanas/{campana_id}", GESTORES, 409),
    _ep("campanas_clientes", "get", "/campanas/{campana_id}/clientes", GESTORES, 200),
    _ep("importaciones_listar", "get", "/campanas/{campana_id}/importaciones", GESTORES, 200),
    _ep(
        "importaciones_subir",
        "post",
        "/campanas/{campana_id}/importaciones",
        GESTORES,
        201,
        files={"archivo": ("b.csv", CSV.replace(b"123456", b"654321"), "text/csv")},
    ),  # fmt: skip
    _ep("importacion_obtener", "get", "/importaciones/{importacion_id}", GESTORES, 200),
    _ep("importacion_errores", "get", "/importaciones/{importacion_id}/errores", GESTORES, 200),
    _ep("exclusiones_listar", "get", "/exclusiones", GESTORES, 200),
    _ep(
        "exclusiones_crear",
        "post",
        "/exclusiones",
        GESTORES,
        201,
        json={"telefono": "3101112233", "motivo": "manual", "aplica_a": "todas"},
    ),  # fmt: skip
    _ep("exclusiones_eliminar", "delete", "/exclusiones/{exclusion_id}", GESTORES, 204),
    _ep(
        "exclusiones_importar",
        "post",
        "/exclusiones/importar",
        GESTORES,
        200,
        data={"motivo": "rne"},
        files={"archivo": ("rne.csv", b"telefono\n3201112233\n", "text/csv")},
    ),  # fmt: skip
    _ep("politicas_listar", "get", "/cumplimiento/politicas", TODOS, 200),
    _ep("politicas_versiones", "get", "/cumplimiento/politicas/venta/versiones", GESTORES, 200),
    _ep(
        "politicas_put", "put", "/cumplimiento/politicas/venta", SOLO_ADMIN, 201, json="POLITICA"
    ),  # fmt: skip
    _ep("festivos_listar", "get", "/festivos?anio=2026", TODOS, 200),
    _ep("festivos_generar", "post", "/festivos/generar", SOLO_ADMIN, 200, json={"anio": 2027}),
    _ep(
        "festivos_crear",
        "post",
        "/festivos",
        SOLO_ADMIN,
        201,
        json={"fecha": "2026-12-30", "nombre": "Otro cívico"},
    ),  # fmt: skip
    _ep(
        "festivos_patch", "patch", "/festivos/{festivo_id}", SOLO_ADMIN, 200, json={"activo": False}
    ),  # fmt: skip
    _ep(
        "evaluar",
        "post",
        "/cumplimiento/evaluar",
        TODOS,
        200,
        json={"tipo_campana": "venta", "momento": "2026-10-23T10:00:00-05:00"},
    ),  # fmt: skip
]


def _peticion(metodo, ruta, kw, datos):
    kw = dict(kw)
    if kw.get("json") == "POLITICA":
        kw["json"] = datos.politica
    return metodo.upper(), "/api/v1" + ruta.format(**datos.__dict__), kw


@pytest.mark.parametrize("rol", [A, S, G])
@pytest.mark.parametrize(("metodo", "ruta", "kw", "roles", "exito"), ENDPOINTS)
def test_matriz_rol_por_endpoint(
    client, crear_usuario, cabeceras, datos, rol, metodo, ruta, kw, roles, exito
):
    h = cabeceras(crear_usuario(rol))
    m, url, kw = _peticion(metodo, ruta, kw, datos)
    r = client.request(m, url, headers=h, **kw)
    if rol in roles:
        assert r.status_code == exito, f"{rol} {m} {url}: {r.status_code} {r.text}"
    else:
        assert r.status_code == 403, f"{rol} {m} {url}: {r.status_code} {r.text}"
        assert r.json() == {
            "error": {
                "codigo": "PERMISO_DENEGADO",
                "mensaje": "No tiene permiso para esta operación.",
                "detalles": [],
            }
        }


@pytest.mark.parametrize(("metodo", "ruta", "kw", "roles", "exito"), ENDPOINTS)
def test_matriz_sin_token(client, datos, metodo, ruta, kw, roles, exito):
    m, url, kw = _peticion(metodo, ruta, kw, datos)
    r = client.request(m, url, **kw)
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "NO_AUTENTICADO"
    assert r.json()["error"]["detalles"] == []


@pytest.mark.parametrize(
    ("metodo", "ruta", "kw"),
    [
        ("post", "/usuarios", {"json": {}}),
        ("post", "/campanas", {"json": {}}),
        ("post", "/exclusiones", {"json": {}}),
        ("post", "/festivos/generar", {"json": {"anio": 1}}),
        ("put", "/cumplimiento/politicas/venta", {"json": {}}),
    ],
)
def test_sin_permiso_gana_a_validacion(client, h_agente, metodo, ruta, kw):
    """Un rol sin permiso recibe 403 aunque el cuerpo sea inválido (no se filtra el esquema)."""
    r = client.request(metodo.upper(), f"/api/v1{ruta}", headers=h_agente, **kw)
    assert r.status_code == 403


def test_agente_campana_no_activa_es_404_y_no_aparece_en_listado(client, h_admin, h_agente, datos):
    """Decisión del backend: un agente que pide una campaña no activa recibe 404 (no 403)."""
    client.patch(
        f"/api/v1/campanas/{datos.campana_id}", json={"estado": "pausada"}, headers=h_admin
    )
    r = client.get(f"/api/v1/campanas/{datos.campana_id}", headers=h_agente)
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "NO_ENCONTRADO"
    for estado in ("", "?estado=pausada", "?estado=borrador", "?q=Base"):
        lista = client.get(f"/api/v1/campanas{estado}", headers=h_agente).json()
        assert lista["total"] == 0, estado
    # y el recurso inexistente responde con el mismo código
    inexistente = client.get("/api/v1/campanas/987654", headers=h_agente)
    assert inexistente.status_code == 404
    assert inexistente.json()["error"]["codigo"] == "NO_ENCONTRADO"


def test_agente_no_obtiene_campana_en_ningun_estado_no_activo(client, h_admin, h_agente):
    cid = client.post(
        "/api/v1/campanas", json={"nombre": "Borrador x", "tipo": "venta"}, headers=h_admin
    ).json()["id"]
    assert client.get(f"/api/v1/campanas/{cid}", headers=h_agente).status_code == 404


def test_supervisor_no_toca_usuarios_ni_politicas_ni_festivos(client, h_supervisor, datos):
    for metodo, url, kw in (
        ("PATCH", f"/api/v1/usuarios/{datos.otro_usuario_id}", {"json": {"rol": "administrador"}}),
        ("PUT", "/api/v1/cumplimiento/politicas/cobranza", {"json": datos.politica}),
        ("POST", "/api/v1/festivos/generar", {"json": {"anio": 2030}}),
        ("PATCH", f"/api/v1/festivos/{datos.festivo_id}", {"json": {"activo": False}}),
    ):
        assert client.request(metodo, url, headers=h_supervisor, **kw).status_code == 403
    # y nada cambió
    assert (
        client.get("/api/v1/cumplimiento/politicas", headers=h_supervisor).json()[0]["version"] == 1
    )
