"""Seguridad: tokens, usuarios desactivados, contraseñas y ausencia de datos personales."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.importacion.modelos import ImportacionError

PASSWORD = "ClaveSegura123"
RUTAS_PROTEGIDAS = [
    "/auth/me",
    "/campanas",
    "/usuarios",
    "/exclusiones",
    "/cumplimiento/politicas",
    "/festivos?anio=2026",
]


def _claims(sub, rol="administrador", **extra):
    ahora = datetime.now(UTC)
    return {"sub": str(sub), "rol": rol, "iat": ahora, "exp": ahora + timedelta(hours=1), **extra}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _assert_no_autenticado(r):
    assert r.status_code == 401, r.text
    assert r.json() == {
        "error": {"codigo": "NO_AUTENTICADO", "mensaje": "No autenticado.", "detalles": []}
    }


@pytest.mark.parametrize("ruta", RUTAS_PROTEGIDAS)
def test_token_firmado_con_otro_secreto_en_cada_ruta(client, admin, ruta):
    ajeno = jwt.encode(_claims(admin.id), "otro-secreto-distinto-de-32-caracteres-xx", "HS256")
    _assert_no_autenticado(client.get(f"/api/v1{ruta}", headers=_bearer(ajeno)))


@pytest.mark.parametrize("ruta", RUTAS_PROTEGIDAS)
def test_token_valido_pasa_en_cada_ruta(client, admin, ruta):
    """Control: el mismo token con el secreto correcto sí funciona."""
    token = jwt.encode(_claims(admin.id), get_settings().jwt_secreto, "HS256")
    assert client.get(f"/api/v1{ruta}", headers=_bearer(token)).status_code == 200


@pytest.mark.parametrize("ruta", RUTAS_PROTEGIDAS)
def test_usuario_desactivado_con_token_vigente_en_cada_ruta(
    client, crear_usuario, cabeceras, db, ruta
):
    u = crear_usuario("administrador")
    h = cabeceras(u)
    assert client.get(f"/api/v1{ruta}", headers=h).status_code == 200
    u.activo = False
    db.commit()
    _assert_no_autenticado(client.get(f"/api/v1{ruta}", headers=h))


def test_reactivar_usuario_restituye_el_acceso_con_el_mismo_token(
    client, h_admin, crear_usuario, cabeceras
):
    u = crear_usuario("supervisor")
    h = cabeceras(u)
    client.patch(f"/api/v1/usuarios/{u.id}", json={"activo": False}, headers=h_admin)
    _assert_no_autenticado(client.get("/api/v1/campanas", headers=h))
    client.patch(f"/api/v1/usuarios/{u.id}", json={"activo": True}, headers=h_admin)
    assert client.get("/api/v1/campanas", headers=h).status_code == 200


def test_desactivar_via_api_corta_el_acceso_inmediatamente(client, h_admin, crear_usuario):
    u = crear_usuario("agente", email="ag@empresa.co")
    token = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD}).json()[
        "access_token"
    ]
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200
    client.patch(f"/api/v1/usuarios/{u.id}", json={"activo": False}, headers=h_admin)
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))
    r = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["codigo"] == "CREDENCIALES_INVALIDAS"


def test_login_inactivo_indistinguible_de_inexistente_y_de_clave_mala(client, crear_usuario, admin):
    inactivo = crear_usuario("agente", activo=False)
    respuestas = [
        client.post("/api/v1/auth/login", json={"email": inactivo.email, "password": PASSWORD}),
        client.post("/api/v1/auth/login", json={"email": "nadie@empresa.co", "password": PASSWORD}),
        client.post(
            "/api/v1/auth/login", json={"email": admin.email, "password": "incorrecta-123"}
        ),
    ]
    assert {r.status_code for r in respuestas} == {401}
    assert len({r.text for r in respuestas}) == 1
    assert respuestas[0].json()["error"]["codigo"] == "CREDENCIALES_INVALIDAS"


def test_token_de_usuario_inexistente_o_borrado(client):
    token = jwt.encode(_claims(99999), get_settings().jwt_secreto, "HS256")
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))


def test_token_sin_exp_o_sin_sub_se_rechaza(client, admin):
    secreto = get_settings().jwt_secreto
    sin_exp = {"sub": str(admin.id), "rol": admin.rol}
    sin_sub = {"rol": admin.rol, "exp": datetime.now(UTC) + timedelta(hours=1)}
    for claims in (sin_exp, sin_sub):
        token = jwt.encode(claims, secreto, "HS256")
        _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))


@pytest.mark.parametrize("sub", ["abc", "", "1.5", "-", "null", "0"])
def test_sub_no_entero_o_inexistente(client, sub):
    token = jwt.encode(_claims(sub), get_settings().jwt_secreto, "HS256")
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))


def test_token_alg_none_se_rechaza(client, admin):
    cabecera = _b64({"alg": "none", "typ": "JWT"})
    cuerpo = _b64({"sub": str(admin.id), "rol": admin.rol, "exp": 9999999999})
    for token in (f"{cabecera}.{cuerpo}.", f"{cabecera}.{cuerpo}.firma"):
        _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))


def test_token_con_otro_algoritmo_hmac_se_rechaza(client, admin):
    token = jwt.encode(_claims(admin.id), get_settings().jwt_secreto, "HS512")
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(token)))


def test_token_manipulado_en_el_payload_se_rechaza(client, crear_usuario, cabeceras):
    """Cambiar el rol o el id en el payload invalida la firma."""
    agente = crear_usuario("agente")
    token = cabeceras(agente)["Authorization"].split()[1]
    cab, _, firma = token.split(".")
    falso = _b64({"sub": "1", "rol": "administrador", "exp": 9999999999})
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers=_bearer(f"{cab}.{falso}.{firma}")))


@pytest.mark.parametrize(
    "cabecera",
    ["Basic YWRtaW46YWRtaW4=", "Bearer", "bearer", "Token abc", "abc", "Bearer a b"],
)
def test_esquemas_de_autorizacion_invalidos(client, cabecera):
    _assert_no_autenticado(client.get("/api/v1/auth/me", headers={"Authorization": cabecera}))


def test_token_expirado_en_ruta_de_negocio(client, admin):
    ahora = datetime.now(UTC)
    token = jwt.encode(
        _claims(admin.id, exp=ahora - timedelta(seconds=1)), get_settings().jwt_secreto, "HS256"
    )
    _assert_no_autenticado(client.get("/api/v1/campanas", headers=_bearer(token)))


def test_salud_y_login_no_exigen_token(client):
    assert client.get("/api/v1/salud").status_code == 200
    assert (
        client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code
        == 401
    )


def test_cambio_de_password_invalida_la_anterior(client, h_admin, crear_usuario):
    u = crear_usuario("agente", email="cambio@empresa.co")
    nueva = "OtraClaveNueva456"
    r = client.patch(f"/api/v1/usuarios/{u.id}", json={"password": nueva}, headers=h_admin)
    assert r.status_code == 200 and "password" not in r.text and "hash" not in r.text
    viejo = client.post("/api/v1/auth/login", json={"email": u.email, "password": PASSWORD})
    nuevo = client.post("/api/v1/auth/login", json={"email": u.email, "password": nueva})
    assert viejo.status_code == 401 and nuevo.status_code == 200


def test_ninguna_respuesta_expone_hash_ni_password(client, h_admin, crear_usuario):
    crear_usuario("agente")
    for ruta in ("/usuarios", "/auth/me"):
        texto = client.get(f"/api/v1{ruta}", headers=h_admin).text
        assert "password" not in texto and "$2b$" not in texto


# --------------------------------------------------------------------------------------
# Datos personales: ni en errores de importación, ni en auditoría, ni en mensajes de error.
# --------------------------------------------------------------------------------------

DOC = "1020304050"
DOC_PUNTOS = "1.020.304.050"
TEL = "3001234567"
TEL_FIJO = "6012345678"
EMAIL = "maria.perez@correo.co"
NOMBRE = "María Pérez Gómez"
PII = [DOC, "1020304", TEL, "3001234", TEL_FIJO, "+573001234567", EMAIL, "maria.perez", "Pérez"]


def _sin_pii(texto: str):
    for dato in PII:
        assert dato not in texto, f"filtró {dato!r} en: {texto[:300]}"


def test_importacion_no_filtra_pii_en_mensajes_ni_en_auditoria(client, h_admin, admin, db):
    cid = client.post(
        "/api/v1/campanas", json={"nombre": "PII", "tipo": "cobranza"}, headers=h_admin
    ).json()["id"]
    # Excluir el teléfono para generar TELEFONO_EXCLUIDO / TODOS_TELEFONOS_EXCLUIDOS
    client.post(
        "/api/v1/exclusiones",
        json={"telefono": "3109998877", "motivo": "manual", "aplica_a": "todas"},
        headers=h_admin,
    )
    cab = (
        "tipo_documento,numero_documento,nombre,telefono_1,telefono_2,email,saldo_total,dias_mora\n"
    )
    filas = [
        f"CC,{DOC_PUNTOS},{NOMBRE},{TEL},{TEL_FIJO},{EMAIL},1.500,3",  # válida
        f"CC,{DOC},{NOMBRE},{TEL},{TEL_FIJO},{EMAIL},1.500,3",  # dup. en archivo
        f"CC,{DOC}9,{NOMBRE},{TEL}1,{TEL_FIJO}1,{EMAIL},1.500,3",  # teléfonos inválidos
        f"CC,{DOC}8,{NOMBRE},3109998877,,{EMAIL},1.500,3",  # todos excluidos
        f"CC,12a{DOC},{NOMBRE},{TEL},,{EMAIL},1.500,3",  # documento inválido
        f"CC,{DOC}7,{NOMBRE},{TEL}2,,no-es-email,-5,x",  # monto/entero/email malos
    ]
    imp = client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={"archivo": ("pii.csv", (cab + "\n".join(filas) + "\n").encode(), "text/csv")},
    ).json()
    assert imp["errores"], "el escenario debe producir incidencias"
    _sin_pii(json.dumps(imp["errores"], ensure_ascii=False))
    persistidos = " ".join(f"{e.mensaje} {e.campo}" for e in db.query(ImportacionError))
    _sin_pii(persistidos)
    # segunda importación: DUPLICADO_EN_CAMPANA tampoco filtra
    imp2 = client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={"archivo": ("pii.csv", (cab + filas[0] + "\n").encode(), "text/csv")},
    ).json()
    assert imp2["errores"][0]["codigo"] == "DUPLICADO_EN_CAMPANA"
    _sin_pii(json.dumps(imp2["errores"], ensure_ascii=False))
    # endpoint paginado de errores
    pag = client.get(f"/api/v1/importaciones/{imp['id']}/errores", headers=h_admin).json()
    _sin_pii(json.dumps(pag, ensure_ascii=False))
    # auditoría completa
    _sin_pii(
        " ".join(f"{a.accion} {a.entidad} {a.entidad_id} {a.detalle}" for a in db.query(Auditoria))
    )


def test_auditoria_no_contiene_pii_en_ningun_flujo(client, h_admin, h_supervisor, db):
    """Recorre todas las acciones auditadas con datos personales en la entrada."""
    client.post(
        "/api/v1/usuarios",
        json={"email": EMAIL, "nombre": NOMBRE, "rol": "agente", "password": "SecretoUnico987"},
        headers=h_admin,
    )
    client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "SecretoUnico987"})
    client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "SecretoMalo000"})
    client.post("/api/v1/auth/login", json={"email": "otro@x.co", "password": "SecretoMalo000"})
    client.post(
        "/api/v1/exclusiones",
        json={"telefono": TEL, "motivo": "manual", "aplica_a": "todas", "observacion": NOMBRE},
        headers=h_supervisor,
    )
    client.post(
        "/api/v1/exclusiones/importar",
        headers=h_supervisor,
        data={"motivo": "rne"},
        files={"archivo": ("r.csv", f"telefono\n{TEL_FIJO}\n".encode(), "text/csv")},
    )
    excl = client.get("/api/v1/exclusiones", headers=h_supervisor).json()["items"]
    client.delete(f"/api/v1/exclusiones/{excl[0]['id']}", headers=h_supervisor)
    client.post(
        "/api/v1/campanas",
        json={"nombre": "Campaña PII", "tipo": "venta", "guion": f"Hola {NOMBRE} {DOC}"},
        headers=h_admin,
    )
    texto = " ".join(
        f"{a.accion} {a.entidad} {a.entidad_id} {a.detalle}" for a in db.query(Auditoria)
    )
    _sin_pii(texto)
    for secreto in ("SecretoUnico987", "SecretoMalo000", "ClaveSegura123"):
        assert secreto not in texto
    acciones = {a.accion for a in db.query(Auditoria)}
    assert {"auth.login_ok", "auth.login_fallido", "usuario.crear", "exclusion.crear",
            "exclusion.importar", "exclusion.eliminar", "campana.crear"} <= acciones  # fmt: skip


def test_mensajes_de_validacion_de_exclusiones_no_repiten_el_telefono(client, h_admin):
    for crudo in ("12345", "+1 415 555 2671", "2345678", "3001234567891"):
        r = client.post(
            "/api/v1/exclusiones",
            json={"telefono": crudo, "motivo": "manual", "aplica_a": "todas"},
            headers=h_admin,
        )
        assert r.status_code == 422
        for d in r.json()["error"]["detalles"]:
            assert crudo not in d["mensaje"] and crudo.replace(" ", "") not in d["mensaje"]


def test_errores_de_exclusiones_masivas_enmascaran(client, h_admin):
    r = client.post(
        "/api/v1/exclusiones/importar",
        headers=h_admin,
        data={"motivo": "rne"},
        files={"archivo": ("r.csv", b"telefono\n+1 415 555 2671\n2345678\n", "text/csv")},
    )
    assert r.status_code == 200 and r.json()["invalidas"] == 2
    texto = json.dumps(r.json()["errores"])
    for completo in ("4155552671", "415 555 2671", "2345678"):
        assert completo not in texto
    assert "***" in texto


def test_error_de_login_no_repite_credenciales(client):
    r = client.post(
        "/api/v1/auth/login", json={"email": "persona@empresa.co", "password": "MiClaveSecreta1"}
    )
    assert "MiClaveSecreta1" not in r.text and "persona@empresa.co" not in r.text
    r = client.post("/api/v1/auth/login", json={"email": "persona@empresa.co", "password": ""})
    assert "persona@empresa.co" not in r.text


def test_422_no_devuelve_el_valor_enviado(client, h_admin):
    """El formato de error no debe incluir `input`/`ctx` de Pydantic con los datos enviados."""
    r = client.post(
        "/api/v1/usuarios",
        json={"email": "no-es-correo", "nombre": "X", "rol": "root", "password": "corta-secreta"},
        headers=h_admin,
    )
    assert r.status_code == 422
    assert "corta-secreta" not in r.text
    assert set(r.json()) == {"error"}
    assert set(r.json()["error"]) == {"codigo", "mensaje", "detalles"}
    for d in r.json()["error"]["detalles"]:
        assert set(d) == {"campo", "mensaje"}
