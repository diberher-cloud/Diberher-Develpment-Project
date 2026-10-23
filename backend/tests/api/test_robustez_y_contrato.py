"""Formato de error común en todos los códigos, transiciones exhaustivas, auditoría y robustez."""

import itertools

import pytest

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente, Cliente

CLAVES_ERROR = {"codigo", "mensaje", "detalles"}


def _es_error_comun(r):
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}, cuerpo
    assert set(cuerpo["error"]) == CLAVES_ERROR, cuerpo
    assert isinstance(cuerpo["error"]["detalles"], list)
    assert isinstance(cuerpo["error"]["codigo"], str) and cuerpo["error"]["mensaje"]
    for d in cuerpo["error"]["detalles"]:
        assert set(d) == {"campo", "mensaje"}
    return cuerpo["error"]


def _campana(client, h, nombre="Campaña x", tipo="cobranza"):
    return client.post("/api/v1/campanas", json={"nombre": nombre, "tipo": tipo}, headers=h).json()[
        "id"
    ]


def _con_cliente(db, cid, doc="100001"):
    cli = Cliente(tipo_documento="CC", numero_documento=doc, nombre="Ana Cliente")
    db.add(cli)
    db.flush()
    db.add(CampanaCliente(campana_id=cid, cliente_id=cli.id))
    db.commit()


def test_formato_de_error_en_401_403_404_405_409_413_422(client, h_admin, h_agente, monkeypatch):
    from app.config import get_settings

    casos = {
        401: client.get("/api/v1/campanas"),
        403: client.post("/api/v1/campanas", json={}, headers=h_agente),
        404: client.get("/api/v1/campanas/9999", headers=h_admin),
        405: client.delete("/api/v1/salud"),
        422: client.post("/api/v1/campanas", json={"nombre": "x"}, headers=h_admin),
    }
    cid = _campana(client, h_admin)
    casos[409] = client.post(
        "/api/v1/campanas", json={"nombre": "Campaña x", "tipo": "venta"}, headers=h_admin
    )
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", 5)
    casos[413] = client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={"archivo": ("a.csv", b"tipo_documento,x\n" * 5, "text/csv")},
    )
    for status, r in casos.items():
        assert r.status_code == status, (status, r.text)
        _es_error_comun(r)
    assert _es_error_comun(casos[404])["codigo"] == "NO_ENCONTRADO"
    assert _es_error_comun(casos[409])["codigo"] == "NOMBRE_DUPLICADO"
    assert _es_error_comun(casos[413])["codigo"] == "ARCHIVO_DEMASIADO_GRANDE"


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("get", "/campanas/abc"), ("get", "/importaciones/x"), ("delete", "/exclusiones/x"),
     ("patch", "/festivos/x"), ("get", "/festivos?anio=abc"), ("get", "/campanas?page=x"),
     ("get", "/campanas?page_size=0"), ("get", "/campanas?page_size=101")],
)  # fmt: skip
def test_parametros_mal_formados_son_422_con_formato_comun(client, h_admin, metodo, ruta):
    r = client.request(metodo.upper(), f"/api/v1{ruta}", headers=h_admin, json=None)
    assert r.status_code == 422
    assert _es_error_comun(r)["codigo"] == "VALIDACION"


def test_json_roto_y_cuerpo_de_tipo_incorrecto(client, h_admin):
    r = client.post(
        "/api/v1/campanas",
        headers={**h_admin, "content-type": "application/json"},
        content=b"{no es json",
    )
    assert r.status_code == 422 and _es_error_comun(r)["codigo"] == "VALIDACION"
    r = client.post("/api/v1/campanas", headers=h_admin, json=[1, 2])
    assert r.status_code == 422 and _es_error_comun(r)["codigo"] == "VALIDACION"


def test_paginacion_fuera_de_rango_devuelve_lista_vacia(client, h_admin):
    _campana(client, h_admin)
    r = client.get("/api/v1/campanas?page=50", headers=h_admin).json()
    assert r == {"items": [], "total": 1, "page": 50, "page_size": 20}


# ----------------------------------------------------------------------------------------
# Transiciones: tabla completa estado -> estado
# ----------------------------------------------------------------------------------------

ESTADOS = ["borrador", "activa", "pausada", "finalizada"]
VALIDAS = {
    ("borrador", "activa"), ("activa", "pausada"), ("pausada", "activa"),
    ("activa", "finalizada"), ("pausada", "finalizada"),
}  # fmt: skip


def _llevar_a(client, h, db, cid, destino):
    camino = {
        "borrador": [], "activa": ["activa"], "pausada": ["activa", "pausada"],
        "finalizada": ["activa", "finalizada"],
    }  # fmt: skip
    for e in camino[destino]:
        assert (
            client.patch(f"/api/v1/campanas/{cid}", json={"estado": e}, headers=h).status_code
            == 200
        )


@pytest.mark.parametrize(("origen", "destino"), list(itertools.product(ESTADOS, ESTADOS)))
def test_tabla_completa_de_transiciones(client, h_admin, db, origen, destino):
    cid = _campana(client, h_admin)
    _con_cliente(db, cid)
    _llevar_a(client, h_admin, db, cid, origen)
    r = client.patch(f"/api/v1/campanas/{cid}", json={"estado": destino}, headers=h_admin)
    if origen == "finalizada":
        # cualquier cambio sobre una finalizada -> 409 CAMPANA_FINALIZADA
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_FINALIZADA"
    elif origen == destino:
        assert r.status_code == 200 and r.json()["estado"] == origen
    elif (origen, destino) in VALIDAS:
        assert r.status_code == 200 and r.json()["estado"] == destino
    else:
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "TRANSICION_INVALIDA"
    # el estado persistido es coherente con la respuesta
    real = client.get(f"/api/v1/campanas/{cid}", headers=h_admin).json()["estado"]
    esperado = destino if r.status_code == 200 else origen
    assert real == esperado


@pytest.mark.parametrize("destino", ["pausada", "finalizada"])
def test_borrador_a_pausada_o_finalizada_es_invalida_incluso_con_clientes(
    client, h_admin, db, destino
):
    cid = _campana(client, h_admin)
    _con_cliente(db, cid)
    r = client.patch(f"/api/v1/campanas/{cid}", json={"estado": destino}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "TRANSICION_INVALIDA"


def test_activar_sin_clientes_tras_borrar_no_aplica_a_pausada(client, h_admin, db):
    """CAMPANA_SIN_CLIENTES solo se exige al activar desde borrador/pausada."""
    cid = _campana(client, h_admin)
    r = client.patch(f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin)
    assert r.json()["error"]["codigo"] == "CAMPANA_SIN_CLIENTES"
    assert client.get(f"/api/v1/campanas/{cid}", headers=h_admin).json()["estado"] == "borrador"


def test_total_clientes_se_actualiza_tras_importar(client, h_admin):
    cid = _campana(client, h_admin)
    assert client.get(f"/api/v1/campanas/{cid}", headers=h_admin).json()["total_clientes"] == 0
    csv = (
        "tipo_documento,numero_documento,nombre,telefono_1\n"
        "CC,100001,Ana Uno,3001230002\nCC,100002,Bea Dos,3001230003\n"
    )
    client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={"archivo": ("a.csv", csv.encode(), "text/csv")},
    )
    assert client.get(f"/api/v1/campanas/{cid}", headers=h_admin).json()["total_clientes"] == 2
    lista = client.get("/api/v1/campanas", headers=h_admin).json()["items"]
    assert lista[0]["total_clientes"] == 2


def test_cambios_simultaneos_estado_y_nombre(client, h_admin, db):
    cid = _campana(client, h_admin)
    _con_cliente(db, cid)
    r = client.patch(
        f"/api/v1/campanas/{cid}",
        json={"estado": "activa", "nombre": "Nombre nuevo"},
        headers=h_admin,
    )
    assert r.status_code == 200 and (r.json()["estado"], r.json()["nombre"]) == (
        "activa",
        "Nombre nuevo",
    )


# ----------------------------------------------------------------------------------------
# Nombre único sin distinguir mayúsculas
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("otro", ["COBRANZA OCTUBRE", "cobranza octubre", "  Cobranza Octubre  ",
                                  "CoBrAnZa OcTuBrE"])  # fmt: skip
def test_nombre_unico_sin_distinguir_mayusculas_ni_espacios_en_bordes(client, h_admin, otro):
    assert _campana(client, h_admin, "Cobranza octubre").__class__ is int
    r = client.post("/api/v1/campanas", json={"nombre": otro, "tipo": "venta"}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"


def test_renombrar_a_nombre_ajeno_es_409_y_a_si_mismo_cambiando_mayusculas_es_200(client, h_admin):
    a = _campana(client, h_admin, "Campaña Alfa")
    _campana(client, h_admin, "Campaña Beta")
    r = client.patch(f"/api/v1/campanas/{a}", json={"nombre": "campaña beta"}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "NOMBRE_DUPLICADO"
    r = client.patch(f"/api/v1/campanas/{a}", json={"nombre": "CAMPAÑA ALFA"}, headers=h_admin)
    assert r.status_code == 200 and r.json()["nombre"] == "CAMPAÑA ALFA"


def test_nombre_se_recorta_y_longitud_limite(client, h_admin):
    r = client.post(
        "/api/v1/campanas", json={"nombre": "  abc  ", "tipo": "venta"}, headers=h_admin
    )
    assert r.status_code == 201 and r.json()["nombre"] == "abc"
    assert client.post("/api/v1/campanas", json={"nombre": "x" * 120, "tipo": "venta"},
                       headers=h_admin).status_code == 201  # fmt: skip
    assert client.post("/api/v1/campanas", json={"nombre": "y" * 121, "tipo": "venta"},
                       headers=h_admin).status_code == 422  # fmt: skip
    assert client.post("/api/v1/campanas", json={"nombre": "   ", "tipo": "venta"},
                       headers=h_admin).status_code == 422  # fmt: skip
    assert client.post("/api/v1/campanas", json={"nombre": "ab ", "tipo": "venta"},
                       headers=h_admin).status_code == 422  # fmt: skip


def test_limites_de_campos_numericos_y_guion(client, h_admin):
    def crear(i, **extra):
        return client.post(
            "/api/v1/campanas",
            json={"nombre": f"Lim {i}", "tipo": "venta", **extra},
            headers=h_admin,
        ).status_code

    assert crear(1, max_intentos=1) == 201 and crear(2, max_intentos=10) == 201
    assert crear(3, max_intentos=0) == 422 and crear(4, max_intentos=11) == 422
    assert crear(5, intervalo_reintento_minutos=5) == 201
    assert crear(6, intervalo_reintento_minutos=10080) == 201
    assert crear(7, intervalo_reintento_minutos=4) == 422
    assert crear(8, intervalo_reintento_minutos=10081) == 422
    assert crear(9, guion="x" * 20000) == 201 and crear(10, guion="x" * 20001) == 422
    assert crear(11, fecha_inicio="2026-11-01", fecha_fin="2026-11-01") == 201
    assert crear(12, fecha_inicio="2026-11-01", fecha_fin="2026-10-31") == 422
    assert crear(13, fecha_inicio="2026-02-30") == 422


# ----------------------------------------------------------------------------------------
# Auditoría: cada acción de §3 genera una fila
# ----------------------------------------------------------------------------------------


def test_cada_accion_de_la_lista_deja_una_fila_de_auditoria(client, h_admin, db):
    import copy

    from app.modulos.cumplimiento.politica import politica_por_defecto

    client.post("/api/v1/auth/login", json={"email": "no@x.co", "password": "mala-clave-1"})
    client.post(
        "/api/v1/usuarios",
        json={"email": "aud@empresa.co", "nombre": "Aud Ito", "rol": "agente",
              "password": "ClaveSegura123"},
        headers=h_admin,
    )  # fmt: skip
    client.post(
        "/api/v1/auth/login", json={"email": "aud@empresa.co", "password": "ClaveSegura123"}
    )
    cid = _campana(client, h_admin)
    client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h_admin,
        files={
            "archivo": (
                "a.csv",
                b"tipo_documento,numero_documento,nombre,telefono_1\n"
                b"CC,100001,Ana Uno,3001230002\n",
                "text/csv",
            )
        },
    )
    client.patch(f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin)
    ex = client.post(
        "/api/v1/exclusiones", json={"telefono": "3101112233", "motivo": "rne"}, headers=h_admin
    )
    client.post(
        "/api/v1/exclusiones/importar",
        headers=h_admin,
        data={"motivo": "rne"},
        files={"archivo": ("r.csv", b"telefono\n3201112233\n", "text/csv")},
    )
    client.delete(f"/api/v1/exclusiones/{ex.json()['id']}", headers=h_admin)
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["permitir_festivos"] = True
    client.put("/api/v1/cumplimiento/politicas/venta", json=cfg, headers=h_admin)
    f = client.post(
        "/api/v1/festivos", json={"fecha": "2026-12-31", "nombre": "Cívico"}, headers=h_admin
    )
    client.patch(f"/api/v1/festivos/{f.json()['id']}", json={"activo": False}, headers=h_admin)
    client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)

    esperadas = {
        "auth.login_ok", "auth.login_fallido", "usuario.crear", "campana.crear", "campana.estado",
        "importacion.crear", "exclusion.crear", "exclusion.eliminar", "exclusion.importar",
        "politica.actualizar", "festivo.crear", "festivo.actualizar", "festivos.generar",
    }  # fmt: skip
    registradas = {a.accion for a in db.query(Auditoria)}
    assert esperadas <= registradas, esperadas - registradas
    # las acciones con actor tienen usuario_id y entidad
    for a in db.query(Auditoria).filter(Auditoria.accion.in_(esperadas - {"auth.login_fallido"})):
        assert a.usuario_id is not None, a.accion
        assert a.detalle is not None and isinstance(a.detalle, dict)
    # cada acción de mutación crea exactamente una fila por operación
    assert db.query(Auditoria).filter_by(accion="importacion.crear").count() == 1
    assert db.query(Auditoria).filter_by(accion="campana.crear").count() == 1


def test_eliminar_campana_deja_auditoria(client, h_admin, db):
    cid = _campana(client, h_admin)
    client.delete(f"/api/v1/campanas/{cid}", headers=h_admin)
    assert (
        db.query(Auditoria).filter_by(accion="campana.eliminar", entidad_id=str(cid)).count() == 1
    )


def test_operaciones_fallidas_no_dejan_auditoria_de_exito(client, h_admin, db):
    cid = _campana(client, h_admin)
    antes = db.query(Auditoria).count()
    assert (
        client.patch(
            f"/api/v1/campanas/{cid}", json={"estado": "activa"}, headers=h_admin
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/exclusiones", json={"telefono": "123", "motivo": "rne"}, headers=h_admin
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/festivos", json={"fecha": "2026-13-01", "nombre": "x"}, headers=h_admin
        ).status_code
        == 422
    )
    db.expire_all()
    assert db.query(Auditoria).count() == antes


# ----------------------------------------------------------------------------------------
# Cumplimiento: robustez de /evaluar y /politicas
# ----------------------------------------------------------------------------------------


def test_evaluar_festivos_no_generados_no_bloquean_segun_contrato(client, h_agente):
    """§4.8: usa los festivos ACTIVOS DE LA TABLA; con la tabla vacía no hay festivos."""
    r = client.post(
        "/api/v1/cumplimiento/evaluar",
        json={"tipo_campana": "venta", "momento": "2026-11-02T10:00:00-05:00"},
        headers=h_agente,
    )
    assert r.status_code == 200 and r.json()["permitido"] is True


@pytest.mark.parametrize(
    "momento",
    ["0001-01-01T00:00:00+00:00", "0001-01-01T00:00:00+14:00", "9999-12-31T23:00:00-05:00"],
)
def test_evaluar_con_fechas_extremas_no_devuelve_500(client, h_agente, momento):
    """Una fecha en el límite del calendario debe dar 200 o 422, nunca 500."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(
            "/api/v1/cumplimiento/evaluar",
            json={"tipo_campana": "venta", "momento": momento},
            headers=h_agente,
        )
    assert r.status_code in (200, 422), f"{r.status_code} {r.text}"


def test_ids_fuera_de_rango_entero_no_devuelven_500(client, h_admin):
    """Un id mayor que el máximo entero de BD debe ser 404/422, no 500."""
    from fastapi.testclient import TestClient

    from app.main import app

    enorme = 10**25
    with TestClient(app, raise_server_exceptions=False) as c:
        for ruta in (
            f"/campanas/{enorme}",
            f"/importaciones/{enorme}",
            f"/campanas/{enorme}/clientes",
        ):
            r = c.get(f"/api/v1{ruta}", headers=h_admin)
            assert r.status_code in (404, 422), f"{ruta}: {r.status_code} {r.text}"


def test_put_politica_con_zona_invalida_y_extra_indica_el_campo(client, h_admin):
    import copy

    from app.modulos.cumplimiento.politica import politica_por_defecto

    cfg = copy.deepcopy(politica_por_defecto())
    cfg["zona_horaria"] = "Mars/Olympus"
    r = client.put("/api/v1/cumplimiento/politicas/venta", json=cfg, headers=h_admin)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == "configuracion.zona_horaria"
    cfg = copy.deepcopy(politica_por_defecto()) | {"extra": 1}
    r = client.put("/api/v1/cumplimiento/politicas/venta", json=cfg, headers=h_admin)
    assert r.status_code == 422
    assert any(d["campo"] == "configuracion.extra" for d in r.json()["error"]["detalles"])
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["lunes"] = [
        {"inicio": "07:00", "fin": "12:00"},
        {"inicio": "11:00", "fin": "13:00"},
    ]
    r = client.put("/api/v1/cumplimiento/politicas/venta", json=cfg, headers=h_admin)
    assert r.status_code == 422
    # ninguna versión nueva se creó
    vs = client.get("/api/v1/cumplimiento/politicas/venta/versiones", headers=h_admin).json()
    assert [v["version"] for v in vs] == [1]


def test_put_dos_veces_incrementa_versiones_y_deja_una_sola_activa(client, h_admin):
    import copy

    from app.modulos.cumplimiento.politica import politica_por_defecto

    for i in range(3):
        cfg = copy.deepcopy(politica_por_defecto())
        cfg["frecuencia"]["max_contactos_dia"] = 2 + i
        assert (
            client.put(
                "/api/v1/cumplimiento/politicas/cobranza", json=cfg, headers=h_admin
            ).status_code
            == 201
        )
    vs = client.get("/api/v1/cumplimiento/politicas/cobranza/versiones", headers=h_admin).json()
    assert [(v["version"], v["activa"]) for v in vs] == [
        (4, True),
        (3, False),
        (2, False),
        (1, False),
    ]
    # la política de venta no se tocó
    v = client.get("/api/v1/cumplimiento/politicas/venta/versiones", headers=h_admin).json()
    assert [(x["version"], x["activa"]) for x in v] == [(1, True)]
    # evaluar usa la versión activa
    r = client.post(
        "/api/v1/cumplimiento/evaluar", json={"tipo_campana": "cobranza"}, headers=h_admin
    )
    assert r.json()["politica_version"] == 4


def test_evaluar_usa_politica_del_tipo_correcto(client, h_admin):
    import copy

    from app.modulos.cumplimiento.politica import politica_por_defecto

    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["viernes"] = [{"inicio": "09:00", "fin": "10:00"}]
    client.put("/api/v1/cumplimiento/politicas/venta", json=cfg, headers=h_admin)
    m = "2026-10-23T15:00:00-05:00"
    venta = client.post(
        "/api/v1/cumplimiento/evaluar",
        json={"tipo_campana": "venta", "momento": m},
        headers=h_admin,
    ).json()
    cobr = client.post(
        "/api/v1/cumplimiento/evaluar",
        json={"tipo_campana": "cobranza", "momento": m},
        headers=h_admin,
    ).json()
    assert venta["permitido"] is False and cobr["permitido"] is True
