"""Cierre de conversaciones con tipificación `canal=whatsapp_mensaje` (K1-K8, §4.8)."""

from datetime import UTC, datetime, timedelta

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, autorizar, clave, contexto, crear_conv, crear_saliente, entrante

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion

API = "/api/v1/conversaciones"
VOLVER = {"resultado": "volver_a_llamar", "contacto_directo": True}


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


@pytest.fixture()
def con_entrante(client, firmar_twilio, correr_trabajos, db, ctx):
    """Conversación del cliente (con un entrante) tomada por el agente."""
    entrante(client, firmar_twilio, texto="Hola, quiero pagar")
    correr_trabajos()
    conv = db.scalar(select(Conversacion))
    assert client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente)).status_code == 200
    return conv


def cerrar(client, usuario, conv, tip=None):
    return client.post(f"{API}/{conv.id}/cerrar", json={"tipificacion": tip}, headers=cab(usuario))


def test_k1_promesa_crea_tipificacion_de_whatsapp_y_gestiona_el_registro(
    client, db, ctx, con_entrante, reloj
):
    r = cerrar(
        client,
        ctx.agente,
        con_entrante,
        {
            "resultado": "promesa_pago",
            "observacion": "Paga el viernes",
            "promesa": {"monto": "250000.50", "fecha_pago": "2026-10-30"},
        },
    )
    assert r.status_code == 200, r.text
    t, c = r.json()["tipificacion"], r.json()["conversacion"]
    assert (t["canal"], t["origen"], t["usuario_id"]) == (
        "whatsapp_mensaje",
        "agente",
        ctx.agente.id,
    )
    assert t["conversacion_id"] == con_entrante.id and t["llamada_id"] is None
    assert t["contacto_directo"] is True and t["promesa"]["monto"] == "250000.50"
    assert t["registro"] == {"estado": "gestionado", "intentos": 1, "proximo_intento_en": None}
    assert (c["estado"], c["motivo_cierre"], c["tipificada"], c["atendida_por"]) == (
        "cerrada",
        "agente",
        True,
        "humano",
    )
    assert c["puede_responder"] is False
    assert {m["codigo"] for m in c["motivos_no_responder"]} >= {"CONVERSACION_CERRADA"}
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert (cc.estado, cc.intentos, cc.ultimo_resultado, cc.reservado_por) == (
        "gestionado",
        1,
        "promesa_pago",
        None,
    )
    conv = db.get(Conversacion, con_entrante.id)
    assert (conv.estado, conv.cerrada_por, conv.clave_abierta, conv.usuario_asignado_id) == (
        "cerrada",
        ctx.agente.id,
        None,
        ctx.agente.id,
    )
    intento = db.get(IntentoContacto, conv.intento_contacto_id)
    assert (intento.resultado, intento.contacto_directo) == ("promesa_pago", True)
    assert db.scalar(select(PromesaPago)).tipificacion_id == t["id"]
    assert all(
        f.estado == "cerrada" and f.clave_activa is None for f in db.scalars(select(ColaAtencion))
    )
    acciones = {a.accion for a in db.scalars(select(Auditoria))}
    assert {"conversacion.cerrar", "tipificacion.crear"} <= acciones
    # El historial de la ficha muestra el canal.
    ficha = client.get(f"/api/v1/conversaciones/{conv.id}/ficha", headers=cab(ctx.agente)).json()
    assert ficha["historial"][0]["canal"] == "whatsapp_mensaje"


def test_k2_sin_entrantes_solo_no_contesta(client, db, ctx, reloj):
    conv = crear_conv(
        db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id), iniciada_por="empresa", ventana=False
    )
    r = cerrar(client, ctx.agente, conv, {"resultado": "contactado"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_INCOHERENTE"
    r = cerrar(client, ctx.agente, conv, {"resultado": "no_contesta"})
    assert r.status_code == 200, r.text
    assert r.json()["tipificacion"]["registro"]["estado"] == "pendiente"
    assert r.json()["tipificacion"]["contacto_directo"] is False
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert cc.intentos == 1 and cc.proximo_intento_en is not None


def test_k3_con_entrantes_no_contesta_422(client, ctx, con_entrante, db):
    r = cerrar(client, ctx.agente, con_entrante, {"resultado": "no_contesta"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_INCOHERENTE"
    db.expire_all()
    assert db.get(Conversacion, con_entrante.id).estado == "abierta"


def test_k4_la_tipificacion_es_obligatoria_con_registro_y_prohibida_sin_el(
    client, db, ctx, con_entrante, reloj, crear_usuario
):
    r = cerrar(client, ctx.agente, con_entrante, None)
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "tipificacion"
    sup = crear_usuario("supervisor")
    sin = crear_conv(db, reloj(), numero="+573119998877", dueno=Humano(sup.id))
    r = cerrar(client, sup, sin, {"resultado": "contactado"})
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "tipificacion"
    r = cerrar(client, sup, sin, None)
    assert r.status_code == 200
    assert r.json()["tipificacion"] is None
    assert (r.json()["conversacion"]["estado"], r.json()["conversacion"]["motivo_cierre"]) == (
        "cerrada",
        "supervisor",
    )
    assert client.post(f"{API}/{sin.id}/cerrar", json={}, headers=cab(sup)).status_code == 409


def test_k5_numero_errado_crea_la_exclusion_para_todos_los_canales(client, db, ctx, con_entrante):
    r = cerrar(client, ctx.agente, con_entrante, {"resultado": "numero_errado"})
    assert r.status_code == 200, r.text
    db.expire_all()
    e = db.scalar(select(Exclusion))
    assert (e.numero_e164, e.motivo, e.aplica_a, e.canal, e.creado_por) == (
        NUMERO,
        "numero_errado",
        "todas",
        "todos",
        ctx.agente.id,
    )
    assert db.get(CampanaCliente, ctx.cc.id).estado == "descartado"


def test_k6_registro_reservado_por_otro_agente_no_se_toca(
    client, db, ctx, con_entrante, esc, crear_usuario, reloj
):
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.reservar(ctx.cc, otro, reloj())
    r = cerrar(client, ctx.agente, con_entrante, {"resultado": "contactado"})
    assert r.status_code == 200, r.text
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert (cc.estado, cc.reservado_por) == (
        "en_gestion",
        otro.id,
    )  # su reserva y su estado intactos
    assert cc.intentos == 1 and cc.ultimo_resultado == "contactado"  # pero la gestión queda anotada
    assert db.scalar(select(Tipificacion.id).where(Tipificacion.conversacion_id == con_entrante.id))


def test_k7_cerrar_dos_veces_409(client, ctx, con_entrante):
    assert cerrar(client, ctx.agente, con_entrante, {"resultado": "contactado"}).status_code == 200
    r = cerrar(client, ctx.agente, con_entrante, {"resultado": "contactado"})
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_CERRADA"


def test_k8_volver_a_llamar_fuera_de_franja_422_con_proxima_ventana(
    client, ctx, con_entrante, reloj
):
    domingo = datetime(2026, 10, 25, 10, 0, tzinfo=UTC) + timedelta(hours=5)
    r = cerrar(
        client,
        ctx.agente,
        con_entrante,
        {**VOLVER, "volver_a_llamar_en": domingo.isoformat()},
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VOLVER_A_LLAMAR_FUERA_DE_FRANJA"
    assert "2026-10-26T07:00:00-05:00" in r.json()["error"]["detalles"][0]["mensaje"]
    lunes = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    r = cerrar(
        client,
        ctx.agente,
        con_entrante,
        {**VOLVER, "volver_a_llamar_en": lunes.isoformat()},
    )
    assert r.status_code == 200
    assert r.json()["tipificacion"]["registro"]["proximo_intento_en"] == "2026-10-26T15:00:00Z"


def test_validaciones_de_tipificacion_de_2a_aplican(client, ctx, con_entrante):
    casos = [
        ({"resultado": "promesa_pago"}, "promesa"),
        ({"resultado": "venta", "venta": {"producto": "X", "valor": "10"}}, None),
        (
            {"resultado": "contactado", "promesa": {"monto": "1", "fecha_pago": "2026-10-30"}},
            "promesa",
        ),
    ]
    r = cerrar(client, ctx.agente, con_entrante, casos[0][0])
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "promesa"
    r = cerrar(client, ctx.agente, con_entrante, casos[1][0])
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_NO_PERMITIDO"
    r = cerrar(client, ctx.agente, con_entrante, casos[2][0])
    assert r.status_code == 422
    r = cerrar(
        client,
        ctx.agente,
        con_entrante,
        {"resultado": "promesa_pago", "promesa": {"monto": "99999999", "fecha_pago": "2026-10-30"}},
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "promesa.monto"


def test_el_agente_no_dueno_no_puede_cerrar_pero_el_supervisor_si(
    client, db, ctx, con_entrante, crear_usuario, h_supervisor
):
    ajeno = crear_usuario("agente")
    r = cerrar(client, ajeno, con_entrante, {"resultado": "contactado"})
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"
    r = client.post(
        f"{API}/{con_entrante.id}/cerrar",
        json={"tipificacion": {"resultado": "contactado"}},
        headers=h_supervisor,
    )
    assert r.status_code == 200 and r.json()["conversacion"]["motivo_cierre"] == "supervisor"
    assert client.post(f"{API}/999/cerrar", json={}, headers=h_supervisor).status_code == 404


def test_cierre_cancela_los_mensajes_pendientes_y_retenidos(client, db, ctx, con_entrante, reloj):
    p = crear_saliente(db, con_entrante, reloj(), estado="pendiente")
    t = crear_saliente(db, con_entrante, reloj(), estado="retenido")
    e = crear_saliente(db, con_entrante, reloj(), estado="enviado", sid="SMx")
    cerrar(client, ctx.agente, con_entrante, {"resultado": "contactado"})
    db.expire_all()
    assert [db.get(Mensaje, m.id).estado for m in (p, t, e)] == [
        "cancelado",
        "cancelado",
        "enviado",
    ]


def test_tras_el_cierre_el_cliente_que_escribe_abre_otra_conversacion(
    client, firmar_twilio, correr_trabajos, db, ctx, con_entrante
):
    cerrar(client, ctx.agente, con_entrante, {"resultado": "contactado"})
    entrante(client, firmar_twilio, texto="una cosa más")
    correr_trabajos()
    db.expire_all()
    convs = db.scalars(select(Conversacion).order_by(Conversacion.id)).all()
    assert [c.estado for c in convs] == ["cerrada", "abierta"]
    # La nueva se vincula al mismo registro aunque ya esté gestionado.
    assert convs[1].campana_cliente_id == ctx.cc.id


def test_conversacion_iniciada_por_plantilla_y_cerrada_conserva_la_reserva_del_agente(
    client, db, ctx, esc, reloj, correr_trabajos
):
    autorizar(db)
    esc.reservar(ctx.cc, ctx.agente, reloj())
    from escenario import telefono_de

    r = client.post(
        f"/api/v1/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={
            "telefono_id": telefono_de(db, ctx.cc).id,
            "plantilla_id": ctx.plantilla.id,
            "idempotencia_clave": clave(),
        },
        headers=cab(ctx.agente),
    )
    cid = r.json()["conversacion_id"]
    correr_trabajos()
    r = client.post(
        f"{API}/{cid}/cerrar",
        json={"tipificacion": {"resultado": "no_contesta"}},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert (cc.estado, cc.reservado_por, cc.intentos) == ("pendiente", None, 1)
