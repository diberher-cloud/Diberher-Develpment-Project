"""Opt-in: alta, duplicada, revocación idempotente y alta desde la conversación (§4.10)."""

from datetime import timedelta

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, contexto, crear_conv

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.whatsapp.modelos import AutorizacionCanal

API = "/api/v1/autorizaciones"
CUERPO = {
    "telefono": "3001234567",
    "finalidad": "cobranza",
    "evidencia": "Formulario firmado F-123",
}


def test_alta_devuelve_201_con_el_objeto_del_contrato(client, h_supervisor, db, reloj):
    r = client.post(API, json=CUERPO, headers=h_supervisor)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["numero_e164"] == NUMERO and a["numero_mascara"] == "+57300****567"
    assert (a["canal"], a["finalidad"], a["origen"], a["vigente"]) == (
        "whatsapp",
        "cobranza",
        "agente",
        True,
    )
    assert (
        a["evidencia"] == "Formulario firmado F-123" and a["otorgada_en"] == "2026-10-23T15:15:00Z"
    )
    assert a["revocada_en"] is None and a["motivo_revocacion"] is None
    assert a["registrada_por"]["id"] and a["registrada_por"]["nombre"]
    fila = db.scalar(select(AutorizacionCanal))
    assert fila.clave_vigente == f"{NUMERO}|whatsapp|cobranza"
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "autorizacion.crear"))
    assert aud.detalle == {"autorizacion_id": fila.id, "finalidad": "cobranza", "origen": "agente"}
    assert NUMERO not in str(aud.detalle) and "Formulario" not in str(aud.detalle)


def test_otorgada_en_opcional_no_futura(client, h_admin, reloj):
    r = client.post(
        API, json={**CUERPO, "otorgada_en": "2026-10-20T10:00:00-05:00"}, headers=h_admin
    )
    assert r.status_code == 201 and r.json()["otorgada_en"] == "2026-10-20T15:00:00Z"
    futura = (reloj() + timedelta(minutes=1)).isoformat()
    r = client.post(
        API, json={**CUERPO, "telefono": "3109998888", "otorgada_en": futura}, headers=h_admin
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "otorgada_en"
    r = client.post(
        API,
        json={**CUERPO, "telefono": "3109998888", "otorgada_en": "2026-10-20T10:00:00"},
        headers=h_admin,
    )
    assert r.status_code == 422  # sin zona horaria


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"evidencia": "abc"}, "evidencia"),
        ({"evidencia": "   "}, "evidencia"),
        ({"evidencia": "x" * 501}, "evidencia"),
        ({"finalidad": "otra"}, "finalidad"),
        ({"telefono": "123"}, "telefono"),
        ({"telefono": "+12025550123"}, "telefono"),
    ],
)
def test_validaciones_de_entrada(client, h_admin, cambios, campo):
    r = client.post(API, json={**CUERPO, **cambios}, headers=h_admin)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == campo


def test_telefono_fijo_422(client, h_admin):
    r = client.post(API, json={**CUERPO, "telefono": "6012345678"}, headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "TELEFONO_NO_VALIDO"


def test_evidencia_se_recorta(client, h_admin):
    r = client.post(API, json={**CUERPO, "evidencia": "   Documento firmado   "}, headers=h_admin)
    assert r.json()["evidencia"] == "Documento firmado"


def test_duplicada_vigente_409_y_nueva_tras_revocar(client, h_admin, h_supervisor, db):
    a = client.post(API, json=CUERPO, headers=h_admin).json()
    r = client.post(API, json=CUERPO, headers=h_supervisor)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "AUTORIZACION_DUPLICADA"
    # Otra finalidad para el mismo número sí se permite.
    assert (
        client.post(API, json={**CUERPO, "finalidad": "venta"}, headers=h_admin).status_code == 201
    )
    # Revocación idempotente.
    assert client.delete(f"{API}/{a['id']}", headers=h_supervisor).status_code == 204
    assert client.delete(f"{API}/{a['id']}", headers=h_supervisor).status_code == 204
    db.expire_all()
    fila = db.get(AutorizacionCanal, a["id"])
    assert fila.clave_vigente is None and fila.motivo_revocacion == "manual" and fila.revocada_por
    assert (
        len(db.scalars(select(Auditoria).where(Auditoria.accion == "autorizacion.revocar")).all())
        == 1
    )
    # Tras revocar se puede crear una nueva.
    assert client.post(API, json=CUERPO, headers=h_admin).status_code == 201
    assert client.delete(f"{API}/99999", headers=h_admin).status_code == 404


def test_listado_filtros_y_orden(client, h_admin, h_supervisor):
    a1 = client.post(API, json=CUERPO, headers=h_admin).json()
    a2 = client.post(
        API, json={**CUERPO, "telefono": "3109998888", "finalidad": "venta"}, headers=h_admin
    ).json()
    client.delete(f"{API}/{a1['id']}", headers=h_admin)
    todas = client.get(API, headers=h_supervisor).json()
    assert [x["id"] for x in todas["items"]] == [a2["id"], a1["id"]] and todas["total"] == 2
    assert [
        x["id"] for x in client.get(f"{API}?vigentes=true", headers=h_admin).json()["items"]
    ] == [a2["id"]]
    assert [
        x["id"] for x in client.get(f"{API}?vigentes=false", headers=h_admin).json()["items"]
    ] == [a1["id"]]
    assert [
        x["id"] for x in client.get(f"{API}?finalidad=venta", headers=h_admin).json()["items"]
    ] == [a2["id"]]
    assert [
        x["id"]
        for x in client.get(f"{API}?numero=310%20999%208888", headers=h_admin).json()["items"]
    ] == [a2["id"]]
    assert client.get(f"{API}?numero=basura", headers=h_admin).json()["items"] == []
    revocada = client.get(f"{API}?vigentes=false", headers=h_admin).json()["items"][0]
    assert revocada["vigente"] is False and revocada["motivo_revocacion"] == "manual"


def test_el_agente_no_accede(client, h_agente):
    assert client.get(API, headers=h_agente).status_code == 403
    assert client.post(API, json=CUERPO, headers=h_agente).status_code == 403
    assert client.delete(f"{API}/1", headers=h_agente).status_code == 403
    assert client.get(API).status_code == 401


# ---- Desde la conversación (origen=cliente) ---------------------------------------------------
def test_alta_desde_la_conversacion_por_el_dueno(client, db, esc, crear_usuario, reloj):
    ctx = contexto(esc, crear_usuario, reloj, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    cuerpo = {
        "finalidad": "cobranza",
        "evidencia": "Cliente escribe en el chat que acepta mensajes",
    }
    url = f"/api/v1/conversaciones/{conv.id}/autorizacion"
    r = client.post(url, json=cuerpo, headers=cab(ctx.agente))
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["origen"], a["finalidad"], a["numero_e164"]) == (
        "cliente",
        "cobranza",
        None,
    )  # el agente no ve el E.164
    assert a["registrada_por"]["id"] == ctx.agente.id
    fila = db.scalar(select(AutorizacionCanal))
    assert fila.numero_e164 == NUMERO and fila.conversacion_id == conv.id
    assert client.post(url, json=cuerpo, headers=cab(ctx.agente)).status_code == 409
    ajeno = crear_usuario("agente")
    assert (
        client.post(url, json={**cuerpo, "finalidad": "venta"}, headers=cab(ajeno)).status_code
        == 403
    )
    assert (
        client.post(
            url.replace(str(conv.id), "999"), json=cuerpo, headers=cab(ctx.agente)
        ).status_code
        == 404
    )
