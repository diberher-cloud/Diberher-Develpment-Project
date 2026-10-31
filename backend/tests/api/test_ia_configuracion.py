"""Configuración IA por campaña, ofertas, global y activación (casos C)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ia import REGLAS_COBRANZA, REGLAS_VENTA
from sqlalchemy import select

from app.modulos.agente_ia.configuracion import huella_evaluacion
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, EvaluacionIA
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.campanas.modelos import CampanaAgente

API = "/api/v1"


def cuerpo(version_esperada=0, reglas=None, **kw):
    d = {
        "version_esperada": version_esperada, "modelo": "claude-opus-5-5", "esfuerzo": "medium",
        "prompt_version": 1, "tratamiento": "usted", "instrucciones": "Sea amable.",
        "verificacion": {"factores": ["numero_documento"], "max_intentos": 3},
        "reglas": reglas or REGLAS_COBRANZA, "presupuesto_usd_mensual": "200.00",
        "max_costo_conversacion_usd": "0.80", "max_turnos_conversacion": 30,
    }  # fmt: skip
    d.update(kw)
    return d


def evaluacion_offline(db, aprobada=True, patron=None, version=1):
    e = EvaluacionIA(
        modo="offline", canal="chat", prompt_version=version, huella=huella_evaluacion(version),
        patron_casos=patron, estado="completada", aprobada=aprobada, resumen={}, casos=[],
        creado_en=datetime(2026, 10, 22, tzinfo=UTC),
    )  # fmt: skip
    db.add(e)
    db.commit()
    return e


@pytest.fixture()
def camp(esc, crear_usuario, db):
    c = esc.campana(tipo="cobranza", whatsapp_habilitado=True)
    return c, crear_usuario("agente")


def test_c1_get_sin_fila(client, h_admin, camp):
    r = client.get(f"{API}/campanas/{camp[0].id}/ia", headers=h_admin)
    j = r.json()
    assert (
        r.status_code == 200
        and j["configurada"] is False
        and j["version"] == 0
        and j["reglas"] is None
    )
    assert j["modelo"] == "claude-opus-5-5" and j["max_costo_conversacion_usd"] == "0.5000"
    assert j["requisitos"]["cumple"] is False
    assert client.get(f"{API}/campanas/9999/ia", headers=h_admin).status_code == 404


def test_c2_put_valido(client, h_admin, camp, db):
    r = client.put(f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(), headers=h_admin)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == 1 and j["configurada"] and j["activa"] is False
    assert j["reglas"]["descuento_max_pct"] == "20.00"
    a = db.scalar(select(Auditoria).where(Auditoria.accion == "ia.configuracion_actualizar"))
    assert a.detalle["version"] == 1 and "reglas" in a.detalle["campos"]
    assert "Sea amable" not in str(a.detalle)


def test_c3_conflicto_de_version(client, h_admin, camp):
    client.put(f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(), headers=h_admin)
    r = client.put(
        f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(version_esperada=0), headers=h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_VERSION_CONFLICTO"
    assert (
        client.put(
            f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(version_esperada=1), headers=h_admin
        ).json()["version"]
        == 2
    )


def test_c4_c5_validacion(client, h_admin, camp):
    mal = dict(REGLAS_COBRANZA, descuento_max_pct_por_cuotas=[
        {"max_cuotas": 3, "descuento_max_pct": "10.00"}, {"max_cuotas": 2, "descuento_max_pct": "30.00"}],
        plazo_max_dias_total=3)  # fmt: skip
    r = client.put(f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(reglas=mal), headers=h_admin)
    campos = {d["campo"] for d in r.json()["error"]["detalles"]}
    assert (
        r.status_code == 422
        and {"reglas.descuento_max_pct_por_cuotas.1.max_cuotas", "reglas.plazo_max_dias_total"}
        <= campos
    )
    r = client.put(f"{API}/campanas/{camp[0].id}/ia", json=cuerpo(modelo="gpt-4"), headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "modelo"
    r = client.put(
        f"{API}/campanas/{camp[0].id}/ia",
        json=cuerpo(verificacion={"factores": ["numero_documento"], "max_intentos": 9}),
        headers=h_admin,
    )
    assert r.status_code == 422


def test_c6_c7_activar(client, h_admin, camp, db):
    c, agente = camp
    client.put(f"{API}/campanas/{c.id}/ia", json=cuerpo(), headers=h_admin)
    r = client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_REQUISITOS_ACTIVACION"
    texto = " ".join(d["mensaje"] for d in r.json()["error"]["detalles"])
    assert "SIN_AGENTES_ASIGNADOS" in texto and "EVALUACION_OFFLINE_PENDIENTE" in texto
    db.add(CampanaAgente(campana_id=c.id, usuario_id=agente.id))
    evaluacion_offline(db)
    db.commit()
    r = client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin)
    assert r.status_code == 200 and r.json()["activa"] is True and r.json()["requisitos"]["cumple"]
    assert (
        client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin).status_code
        == 200
    )  # idempotente


def test_c8_put_activa_sin_evaluacion_del_prompt(client, h_admin, camp, db):
    c, agente = camp
    db.add(CampanaAgente(campana_id=c.id, usuario_id=agente.id))
    evaluacion_offline(db)
    client.put(f"{API}/campanas/{c.id}/ia", json=cuerpo(), headers=h_admin)
    client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin)
    # presupuesto 0 en una configuración activa: requisitos incumplidos, no se guarda
    r = client.put(
        f"{API}/campanas/{c.id}/ia",
        json=cuerpo(version_esperada=1, presupuesto_usd_mensual="0"),
        headers=h_admin,
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_REQUISITOS_ACTIVACION"
    assert db.get(ConfiguracionIACampana, c.id).presupuesto_usd_mensual == Decimal("200.00")


def test_e6_evaluacion_con_patron_o_obsoleta_no_cuenta(client, h_admin, camp, db):
    c, agente = camp
    db.add(CampanaAgente(campana_id=c.id, usuario_id=agente.id))
    client.put(f"{API}/campanas/{c.id}/ia", json=cuerpo(), headers=h_admin)
    evaluacion_offline(db, patron="cobranza_*")
    e = evaluacion_offline(db)
    assert (
        client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin).status_code
        == 200
    )
    client.post(f"{API}/campanas/{c.id}/ia/desactivar", json={}, headers=h_admin)
    e.huella = "0" * 64  # un cambio del prompt/herramientas la invalida
    db.commit()
    r = client.post(f"{API}/campanas/{c.id}/ia/activar", json={}, headers=h_admin)
    assert r.status_code == 409


def test_c9_ofertas(client, h_admin, esc, db):
    venta = esc.campana(tipo="venta", whatsapp_habilitado=True)
    cobranza = esc.campana(tipo="cobranza")
    base = {"codigo": "seg-hogar", "nombre": "Seguro hogar", "precio": "89900.00",
            "descuento_max_pct": "10.00", "max_unidades": 1}  # fmt: skip
    r = client.post(f"{API}/campanas/{venta.id}/ofertas", json=base, headers=h_admin)
    assert (
        r.status_code == 201
        and r.json()["codigo"] == "SEG-HOGAR"
        and r.json()["precio"] == "89900.00"
    )
    assert (
        client.post(f"{API}/campanas/{venta.id}/ofertas", json=base, headers=h_admin).json()[
            "error"
        ]["codigo"]
        == "OFERTA_DUPLICADA"
    )
    assert (
        client.post(f"{API}/campanas/{cobranza.id}/ofertas", json=base, headers=h_admin).status_code
        == 422
    )
    oid = r.json()["id"]
    r = client.patch(
        f"{API}/campanas/{venta.id}/ofertas/{oid}", json={"precio": "99900.00"}, headers=h_admin
    )
    assert r.status_code == 200 and r.json()["precio"] == "99900.00"
    assert (
        client.get(f"{API}/campanas/{venta.id}/ofertas?activas=true", headers=h_admin).json()[0][
            "id"
        ]
        == oid
    )
    # IA activa de venta: no se puede desactivar la última oferta
    from ia import crear_config

    crear_config(db, venta, 1)
    r = client.patch(
        f"{API}/campanas/{venta.id}/ofertas/{oid}", json={"activa": False}, headers=h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_REQUISITOS_ACTIVACION"
    assert (
        client.patch(f"{API}/campanas/{venta.id}/ofertas/999", json={}, headers=h_admin).status_code
        == 404
    )


def _tipificar_promesa(client, ctx, db, reloj, monto):
    from escenario import cab, telefono_de

    S = "/api/v1/telefonia/simulacion"
    h = cab(ctx.agente)
    r = client.post(f"{S}/llamadas", json={"campana_cliente_id": ctx.cc.id,
                                           "telefono_id": telefono_de(db, ctx.cc).id}, headers=h)  # fmt: skip
    lid = r.json()["llamada_id"]
    client.post(f"{S}/llamadas/{lid}/eventos", json={"evento": "contestada"}, headers=h)
    client.post(f"{S}/llamadas/{lid}/eventos", json={"evento": "finalizada", "resultado": "completed",
                                                      "duracion_segundos": 30}, headers=h)  # fmt: skip
    return client.post("/api/v1/consola/tipificaciones", json={
        "llamada_id": lid, "resultado": "promesa_pago",
        "promesa": {"monto": monto, "fecha_pago": "2026-10-30"}}, headers=h)  # fmt: skip


@pytest.mark.parametrize("con_ia", [True, False])
def test_c10_promesa_humana_con_limites(client, esc, crear_usuario, reloj, db, con_ia):
    from ia import crear_config
    from voz import contexto

    ctx = contexto(esc, crear_usuario, reloj)
    ctx.cc.saldo_mora = Decimal("300000.00")
    db.commit()
    if con_ia:
        crear_config(db, ctx.campana, ctx.agente.id)
    r = _tipificar_promesa(client, ctx, db, reloj, "200000.00")
    if con_ia:
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "FUERA_DE_LIMITES"
        assert r.json()["error"]["detalles"][0] == {
            "campo": "promesa.monto", "mensaje": "Con 1 cuota el monto mínimo es $ 240.000."}  # fmt: skip
    else:
        assert r.status_code == 201  # sin configuración IA: como 2A


def test_global_solo_admin(client, h_supervisor, h_agente, h_admin):
    assert client.get(f"{API}/configuracion/ia", headers=h_supervisor).status_code == 200
    assert (
        client.put(
            f"{API}/configuracion/ia", json={"ia_activa": False}, headers=h_supervisor
        ).status_code
        == 403
    )
    assert client.get(f"{API}/configuracion/ia", headers=h_agente).status_code == 403
    j = client.get(f"{API}/configuracion/ia", headers=h_admin).json()
    assert (
        j["proveedor"] == "falso"
        and j["prompts"] == {"chat": [1]}
        and "claude-haiku-5-5" in j["modelos_permitidos"]
    )
    assert "api_key" not in str(j).lower()


def test_ofertas_venta_reglas_y_config_venta(client, h_admin, esc):
    venta = esc.campana(tipo="venta", whatsapp_habilitado=True)
    r = client.put(
        f"{API}/campanas/{venta.id}/ia", json=cuerpo(reglas=REGLAS_VENTA), headers=h_admin
    )
    assert r.status_code == 200 and r.json()["reglas"] == REGLAS_VENTA
    r = client.put(
        f"{API}/campanas/{venta.id}/ia",
        json=cuerpo(version_esperada=1, reglas=REGLAS_COBRANZA),
        headers=h_admin,
    )
    assert r.status_code == 422
