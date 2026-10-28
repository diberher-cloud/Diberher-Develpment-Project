"""Plantillas: sincronización, mapeo, activación y campos de campaña (T1-T8, §4.9)."""

from dataclasses import replace

import pytest
from escenario import cab
from sqlalchemy import select

from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.whatsapp.modelos import PlantillaWhatsApp

API = "/api/v1/whatsapp/plantillas"
MAPEO_1 = {"1": "primer_nombre", "2": "empresa"}


def sincronizar(client, h):
    return client.post(f"{API}/sincronizar", headers=h)


def por_sid(db):
    db.expire_all()
    return {p.content_sid: p for p in db.scalars(select(PlantillaWhatsApp))}


def test_t1_sincronizar_con_el_falso_crea_cuatro_inactivas(client, h_admin, db):
    r = sincronizar(client, h_admin)
    assert r.status_code == 200 and r.json() == {"creadas": 4, "actualizadas": 0, "desactivadas": 0}
    filas = por_sid(db)
    assert sorted(filas) == ["HXfalso0001", "HXfalso0002", "HXfalso0003", "HXfalso0004"]
    p = filas["HXfalso0002"]
    assert (p.nombre, p.categoria, p.estado_aprobacion, p.variables) == (
        "oferta_venta", "marketing", "aprobada", ["1", "2", "3"],
    )  # fmt: skip
    assert p.tiene_boton_baja is True and p.botones == [
        {"tipo": "respuesta_rapida", "texto": "Darme de baja", "payload": "BAJA"}
    ]
    assert filas["HXfalso0004"].tiene_boton_baja is False
    assert all(
        not x.activa and x.finalidad is None and x.mapeo_variables == {} for x in filas.values()
    )
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.plantillas_sincronizar"))
    assert aud.detalle == {"creadas": 4, "actualizadas": 0, "desactivadas": 0}


def test_t2_resincronizar_sin_cambios_es_cero(client, h_admin):
    sincronizar(client, h_admin)
    assert sincronizar(client, h_admin).json() == {
        "creadas": 0,
        "actualizadas": 0,
        "desactivadas": 0,
    }


def activar(client, h, pid, finalidad="cobranza", mapeo=None):
    return client.put(
        f"{API}/{pid}",
        json={"finalidad": finalidad, "mapeo_variables": mapeo or MAPEO_1, "activa": True},
        headers=h,
    )


def test_t3_cambio_de_cuerpo_remoto_vacia_el_mapeo_y_desactiva(
    client, h_admin, db, proveedor_whatsapp
):
    sincronizar(client, h_admin)
    p1 = por_sid(db)["HXfalso0001"]
    assert activar(client, h_admin, p1.id).status_code == 200
    proveedor_whatsapp.plantillas[0] = replace(
        proveedor_whatsapp.plantillas[0], cuerpo="Hola {{1}}, cuerpo nuevo de {{2}}."
    )
    assert sincronizar(client, h_admin).json() == {
        "creadas": 0,
        "actualizadas": 1,
        "desactivadas": 1,
    }
    p = por_sid(db)["HXfalso0001"]
    assert (
        p.cuerpo.startswith("Hola {{1}}, cuerpo nuevo")
        and p.mapeo_variables == {}
        and p.activa is False
    )
    assert p.finalidad == "cobranza"  # la finalidad se conserva


def test_t3b_cambio_de_variables_remotas_tambien_vacia_el_mapeo(
    client, h_admin, db, proveedor_whatsapp
):
    sincronizar(client, h_admin)
    p1 = por_sid(db)["HXfalso0001"]
    activar(client, h_admin, p1.id)
    proveedor_whatsapp.plantillas[0] = replace(
        proveedor_whatsapp.plantillas[0], variables=("1", "2", "3")
    )
    sincronizar(client, h_admin)
    assert por_sid(db)["HXfalso0001"].mapeo_variables == {}


def test_t4_desaparece_en_remoto_pasa_a_eliminada(client, h_admin, db, proveedor_whatsapp):
    sincronizar(client, h_admin)
    activar(client, h_admin, por_sid(db)["HXfalso0001"].id)
    proveedor_whatsapp.plantillas.pop(0)
    assert sincronizar(client, h_admin).json() == {
        "creadas": 0,
        "actualizadas": 1,
        "desactivadas": 1,
    }
    p = por_sid(db)["HXfalso0001"]
    assert (p.estado_aprobacion, p.activa) == ("eliminada", False)
    assert sincronizar(client, h_admin).json() == {
        "creadas": 0,
        "actualizadas": 0,
        "desactivadas": 0,
    }


def test_deja_de_estar_aprobada_se_desactiva(client, h_admin, db, proveedor_whatsapp):
    sincronizar(client, h_admin)
    activar(client, h_admin, por_sid(db)["HXfalso0001"].id)
    proveedor_whatsapp.plantillas[0] = replace(
        proveedor_whatsapp.plantillas[0], estado_aprobacion="pausada"
    )
    assert sincronizar(client, h_admin).json()["desactivadas"] == 1
    p = por_sid(db)["HXfalso0001"]
    assert (p.estado_aprobacion, p.activa) == ("pausada", False)


def test_error_del_proveedor_502(client, h_admin, proveedor_whatsapp):
    proveedor_whatsapp.fallo_listado = ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", True)
    r = sincronizar(client, h_admin)
    assert r.status_code == 502 and r.json()["error"]["codigo"] == "PROVEEDOR_NO_DISPONIBLE"


def test_t5_mapeo_fuera_de_la_lista_blanca_422(client, h_admin, db):
    sincronizar(client, h_admin)
    pid = por_sid(db)["HXfalso0001"].id
    r = client.put(
        f"{API}/{pid}",
        json={"mapeo_variables": {"1": "saldo_mora", "2": "empresa"}},
        headers=h_admin,
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_MAPEO_INVALIDO"
    assert r.json()["error"]["detalles"][0]["campo"] == "mapeo_variables.1"
    r = client.put(
        f"{API}/{pid}", json={"mapeo_variables": {"1": "primer_nombre"}}, headers=h_admin
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "mapeo_variables.2"
    r = client.put(
        f"{API}/{pid}", json={"mapeo_variables": {**MAPEO_1, "9": "empresa"}}, headers=h_admin
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "mapeo_variables.9"
    assert por_sid(db)["HXfalso0001"].mapeo_variables == {}


def test_t6_activar_una_pendiente_o_incompleta_422(client, h_admin, db):
    sincronizar(client, h_admin)
    filas = por_sid(db)
    r = activar(client, h_admin, filas["HXfalso0003"].id, mapeo={"1": "primer_nombre"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_NO_DISPONIBLE"
    # Aprobada pero sin finalidad ni mapeo.
    r = client.put(f"{API}/{filas['HXfalso0001'].id}", json={"activa": True}, headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_NO_DISPONIBLE"
    assert not any(p.activa for p in por_sid(db).values())


def test_t7_marketing_sin_boton_de_baja_422(client, h_admin, db):
    sincronizar(client, h_admin)
    filas = por_sid(db)
    r = activar(client, h_admin, filas["HXfalso0004"].id, mapeo={"1": "primer_nombre"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_SIN_BAJA"
    r = activar(
        client,
        h_admin,
        filas["HXfalso0002"].id,
        mapeo={"1": "primer_nombre", "2": "empresa", "3": "producto"},
    )
    assert r.status_code == 200 and r.json()["activa"] is True and r.json()["enviable"] is True


def test_put_campos_opcionales_y_extras_prohibidos(client, h_admin, h_supervisor, h_agente, db):
    sincronizar(client, h_admin)
    pid = por_sid(db)["HXfalso0001"].id
    assert client.put(f"{API}/{pid}", json={"cuerpo": "hack"}, headers=h_admin).status_code == 422
    r = client.put(f"{API}/{pid}", json={"finalidad": "venta"}, headers=h_supervisor)
    assert r.status_code == 200 and r.json()["finalidad"] == "venta" and r.json()["activa"] is False
    assert (
        client.put(f"{API}/{pid}", json={"finalidad": "otra"}, headers=h_admin).status_code == 422
    )
    assert (
        client.put(f"{API}/{pid}", json={"finalidad": "venta"}, headers=h_agente).status_code == 403
    )
    assert client.put(f"{API}/9999", json={}, headers=h_admin).status_code == 404
    r = activar(client, h_admin, pid)
    r = client.put(f"{API}/{pid}", json={"activa": False}, headers=h_admin)
    assert r.json()["activa"] is False and r.json()["enviable"] is False
    aud = db.scalars(
        select(Auditoria).where(Auditoria.accion == "whatsapp.plantilla_actualizar")
    ).all()
    assert aud and set(aud[0].detalle) == {"plantilla_id", "campos"}


def test_solo_el_administrador_sincroniza(client, h_supervisor, h_agente):
    assert sincronizar(client, h_supervisor).status_code == 403
    assert sincronizar(client, h_agente).status_code == 403
    assert client.post(f"{API}/sincronizar").status_code == 401


def test_t8_el_agente_solo_ve_enviables_de_la_finalidad_de_su_campana(
    client, h_admin, db, esc, crear_usuario
):
    sincronizar(client, h_admin)
    filas = por_sid(db)
    activar(client, h_admin, filas["HXfalso0001"].id, finalidad="cobranza")
    activar(
        client,
        h_admin,
        filas["HXfalso0002"].id,
        finalidad="venta",
        mapeo={"1": "primer_nombre", "2": "empresa", "3": "producto"},
    )
    agente = crear_usuario("agente")
    cobranza = esc.campana(tipo="cobranza", whatsapp_habilitado=True)
    venta = esc.campana(tipo="venta", whatsapp_habilitado=True)
    esc.asignar(cobranza, agente)
    lista = client.get(f"{API}?campana_id={cobranza.id}", headers=cab(agente))
    assert [p["content_sid"] for p in lista.json()] == ["HXfalso0001"]
    assert lista.json()[0]["enviable"] is True
    # Sin campana_id o con una campaña no asignada: 422 / 403.
    assert client.get(API, headers=cab(agente)).status_code == 422
    r = client.get(f"{API}?campana_id={venta.id}", headers=cab(agente))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"


def test_el_administrador_ve_todas_y_filtra(client, h_admin, h_supervisor, db, esc):
    sincronizar(client, h_admin)
    filas = por_sid(db)
    activar(client, h_admin, filas["HXfalso0001"].id)
    todas = client.get(API, headers=h_supervisor).json()
    assert len(todas) == 4
    assert {p["content_sid"] for p in todas if p["enviable"]} == {"HXfalso0001"}
    solo = client.get(f"{API}?enviables=true", headers=h_admin).json()
    assert [p["content_sid"] for p in solo] == ["HXfalso0001"]
    venta = esc.campana(tipo="venta")
    assert client.get(f"{API}?enviables=true&campana_id={venta.id}", headers=h_admin).json() == []
    assert client.get(f"{API}?campana_id=99999", headers=h_admin).status_code == 404
    p = todas[0]
    assert set(p) >= {
        "id", "content_sid", "nombre", "idioma", "categoria", "estado_aprobacion",
        "motivo_rechazo", "cuerpo", "variables", "botones", "tiene_boton_baja",
        "mapeo_variables", "finalidad", "activa", "enviable", "sincronizada_en",
    }  # fmt: skip


# ---- Campos de campaña -----------------------------------------------------------------------
def test_campana_acepta_whatsapp_habilitado_y_plantilla_inicial(client, h_admin, db):
    sincronizar(client, h_admin)
    filas = por_sid(db)
    activar(client, h_admin, filas["HXfalso0001"].id, finalidad="cobranza")
    pid = filas["HXfalso0001"].id
    base = {"nombre": "Camp WA", "tipo": "cobranza"}
    r = client.post("/api/v1/campanas", json=base, headers=h_admin)
    assert r.status_code == 201 and r.json()["whatsapp_habilitado"] is False
    assert r.json()["plantilla_inicial_id"] is None
    r = client.post(
        "/api/v1/campanas",
        json={
            **base,
            "nombre": "Camp WA 2",
            "whatsapp_habilitado": True,
            "plantilla_inicial_id": pid,
        },
        headers=h_admin,
    )
    assert r.status_code == 201, r.text
    assert (r.json()["whatsapp_habilitado"], r.json()["plantilla_inicial_id"]) == (True, pid)
    cid = r.json()["id"]
    # Plantilla de otra finalidad, inexistente o inactiva: 422 en `plantilla_inicial_id`.
    for mala in (filas["HXfalso0003"].id, 99999):
        r = client.patch(
            f"/api/v1/campanas/{cid}", json={"plantilla_inicial_id": mala}, headers=h_admin
        )
        assert (
            r.status_code == 422
            and r.json()["error"]["detalles"][0]["campo"] == "plantilla_inicial_id"
        )
    r = client.post(
        "/api/v1/campanas",
        json={"nombre": "Venta", "tipo": "venta", "plantilla_inicial_id": pid},
        headers=h_admin,
    )
    assert r.status_code == 422
    r = client.patch(
        f"/api/v1/campanas/{cid}",
        json={"whatsapp_habilitado": False, "plantilla_inicial_id": None},
        headers=h_admin,
    )
    assert (
        r.status_code == 200
        and r.json()["whatsapp_habilitado"] is False
        and r.json()["plantilla_inicial_id"] is None
    )
    # Un null explícito en `whatsapp_habilitado` se ignora.
    r = client.patch(f"/api/v1/campanas/{cid}", json={"whatsapp_habilitado": None}, headers=h_admin)
    assert r.status_code == 200 and r.json()["whatsapp_habilitado"] is False
    assert (
        client.get(f"/api/v1/campanas/{cid}", headers=h_admin).json()["whatsapp_habilitado"]
        is False
    )


@pytest.mark.parametrize("campo", ["whatsapp_habilitado", "plantilla_inicial_id"])
def test_el_agente_no_modifica_campos_de_whatsapp_de_la_campana(client, h_agente, campo):
    r = client.patch("/api/v1/campanas/1", json={campo: None}, headers=h_agente)
    assert r.status_code == 403
