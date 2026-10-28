"""Opt-out determinista (entrante) y manual, con sus efectos (§4.10)."""

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, autorizar, clave, contexto, crear_conv, entrante

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal

API = "/api/v1/conversaciones"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    c = contexto(esc, crear_usuario, reloj, db)
    autorizar(db)
    return c


def stop(client, firmar_twilio, correr_trabajos, texto="STOP", **kw):
    entrante(client, firmar_twilio, texto=texto, **kw)
    correr_trabajos()


def test_stop_entrante_aplica_todos_los_efectos(
    client, firmar_twilio, correr_trabajos, db, ctx, proveedor_whatsapp
):
    stop(client, firmar_twilio, correr_trabajos)
    db.expire_all()
    e = db.scalar(select(Exclusion))
    conv = db.scalar(select(Conversacion))
    assert (e.numero_e164, e.motivo, e.aplica_a, e.canal, e.origen, e.creado_por) == (
        NUMERO, "solicitud_titular", "todas", "whatsapp", "sistema", None,
    )  # fmt: skip
    assert e.conversacion_id == conv.id
    a = db.scalar(select(AutorizacionCanal))
    assert (a.clave_vigente, a.motivo_revocacion, a.revocada_en is not None) == (
        None,
        "opt_out",
        True,
    )
    assert (conv.estado, conv.motivo_cierre, conv.clave_abierta) == ("cerrada", "opt_out", None)
    # La confirmación sí se envía aunque la conversación esté cerrada.
    assert [x["texto"] for x in proveedor_whatsapp.enviados] == [
        "Hemos registrado su solicitud. No le enviaremos más mensajes por WhatsApp."
    ]
    conf = db.scalar(select(Mensaje).where(Mensaje.direccion == "saliente"))
    assert (conf.autor, conf.estado) == ("sistema", "enviado")
    assert all(f.estado == "cerrada" for f in db.scalars(select(ColaAtencion)))
    assert db.scalar(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")) is None
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.opt_out"))
    assert aud.detalle == {
        "conversacion_id": conv.id,
        "alcance": "whatsapp",
        "origen": "determinista",
    }
    assert NUMERO not in str(aud.detalle)


def test_segundo_stop_en_una_conversacion_nueva_no_duplica_la_exclusion(
    client, firmar_twilio, correr_trabajos, db, ctx
):
    stop(client, firmar_twilio, correr_trabajos)
    stop(client, firmar_twilio, correr_trabajos, texto="stop")
    db.expire_all()
    assert len(db.scalars(select(Exclusion)).all()) == 1
    assert len(db.scalars(select(Conversacion)).all()) == 2


def test_no_me_contacten_mas_aplica_a_todos_los_canales_y_bloquea_la_voz(
    client, firmar_twilio, correr_trabajos, db, ctx, proveedor_whatsapp, esc, crear_usuario, reloj
):
    from voz import llamar, params_saliente

    stop(client, firmar_twilio, correr_trabajos, texto="No me contacten más")
    db.expire_all()
    e = db.scalar(select(Exclusion))
    assert (e.canal, e.aplica_a, e.origen) == ("todos", "todas", "sistema")
    assert "ningún medio" in proveedor_whatsapp.enviados[0]["texto"]
    # La voz queda bloqueada: la llamada se rechaza por EXCLUIDO.
    ctx.cc.reservado_por, ctx.cc.estado = ctx.agente.id, "en_gestion"
    from datetime import timedelta

    ctx.cc.reservado_hasta = reloj() + timedelta(minutes=10)
    db.commit()
    r = llamar(client, firmar_twilio, params_saliente(ctx, db, sid="CAopt"))
    assert r.status_code == 200 and "<Dial" not in r.text


def test_boton_de_baja_es_opt_out_de_whatsapp(client, firmar_twilio, correr_trabajos, db, ctx):
    entrante(
        client,
        firmar_twilio,
        texto="Darme de baja",
        ButtonPayload="BAJA",
        ButtonText="Darme de baja",
    )
    correr_trabajos()
    db.expire_all()
    assert db.scalar(select(Exclusion)).canal == "whatsapp"
    assert db.scalar(select(Conversacion)).motivo_cierre == "opt_out"


def test_texto_normal_no_dispara_opt_out(client, firmar_twilio, correr_trabajos, db, ctx):
    stop(client, firmar_twilio, correr_trabajos, texto="quiero cancelar la deuda")
    db.expire_all()
    assert db.scalar(select(Exclusion.id)) is None
    assert db.scalar(select(Conversacion)).estado == "abierta"


def test_tras_el_opt_out_el_cliente_escribe_hola_el_agente_responde_pero_no_hay_plantillas(
    client, firmar_twilio, correr_trabajos, db, ctx, esc, reloj
):
    stop(client, firmar_twilio, correr_trabajos)
    entrante(client, firmar_twilio, texto="hola")
    correr_trabajos()
    db.expire_all()
    nueva = db.scalars(select(Conversacion).order_by(Conversacion.id.desc())).first()
    assert nueva.estado == "abierta"
    r = client.post(f"{API}/{nueva.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 200
    # La exclusión es anterior al nuevo entrante: puede responder.
    r = client.post(
        f"{API}/{nueva.id}/mensajes",
        json={"texto": "Con gusto", "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 202, r.text
    detalle = client.get(f"{API}/{nueva.id}", headers=cab(ctx.agente)).json()
    assert detalle["puede_responder"] is True
    assert "EXCLUIDO_WHATSAPP" in [a["codigo"] for a in detalle["alertas"]]
    # Pero la plantilla sigue bloqueada (exclusión vigente y autorización revocada).
    r = client.post(
        f"{API}/{nueva.id}/cerrar",
        json={"tipificacion": {"resultado": "contactado"}},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200, r.text
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
    assert r.status_code == 200 and r.json()["permitido"] is False
    assert [m["codigo"] for m in r.json()["motivos"]][:2] == ["EXCLUIDO", "SIN_AUTORIZACION"]


def test_opt_out_manual_por_el_dueno(client, db, ctx, reloj, proveedor_whatsapp, correr_trabajos):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.post(f"{API}/{conv.id}/opt-out", json={"alcance": "todos"}, headers=cab(ctx.agente))
    assert r.status_code == 200, r.text
    assert (r.json()["estado"], r.json()["motivo_cierre"]) == ("cerrada", "opt_out")
    db.expire_all()
    e = db.scalar(select(Exclusion))
    assert (e.canal, e.origen, e.creado_por, e.conversacion_id) == (
        "todos",
        "usuario",
        ctx.agente.id,
        conv.id,
    )
    correr_trabajos()
    assert len(proveedor_whatsapp.enviados) == 1
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.opt_out"))
    assert aud.detalle["origen"] == "agente" and aud.detalle["alcance"] == "todos"
    # Ya cerrada: 409.
    assert (
        client.post(
            f"{API}/{conv.id}/opt-out", json={"alcance": "todos"}, headers=cab(ctx.agente)
        ).status_code
        == 409
    )


def test_opt_out_manual_exige_ser_el_dueno_y_alcance_valido(client, db, ctx, reloj, crear_usuario):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    ajeno = crear_usuario("agente")
    assert (
        client.post(
            f"{API}/{conv.id}/opt-out", json={"alcance": "whatsapp"}, headers=cab(ajeno)
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/{conv.id}/opt-out", json={"alcance": "sms"}, headers=cab(ctx.agente)
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/999/opt-out", json={"alcance": "whatsapp"}, headers=cab(ctx.agente)
        ).status_code
        == 404
    )


def test_opt_out_cancela_los_salientes_pendientes_y_con_equivalente_mas_amplia_no_duplica(
    client, db, ctx, reloj, admin
):
    from wa import crear_saliente

    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="manual",
            aplica_a="todas",
            canal="todos",
            creado_por=admin.id,
        )
    )
    db.commit()
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    pendiente = crear_saliente(db, conv, reloj(), estado="pendiente")
    retenido = crear_saliente(db, conv, reloj(), estado="retenido")
    client.post(f"{API}/{conv.id}/opt-out", json={"alcance": "whatsapp"}, headers=cab(ctx.agente))
    db.expire_all()
    assert len(db.scalars(select(Exclusion)).all()) == 1  # ya existía una más amplia (todos)
    assert db.get(Mensaje, pendiente.id).estado == "cancelado"
    assert db.get(Mensaje, retenido.id).estado == "cancelado"


def test_opt_out_con_confirmacion_vacia_no_envia_nada(
    client, firmar_twilio, correr_trabajos, db, ctx, proveedor_whatsapp, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "whatsapp_mensaje_opt_out", "")
    stop(client, firmar_twilio, correr_trabajos)
    assert proveedor_whatsapp.enviados == []
    db.expire_all()
    assert db.scalar(select(Conversacion)).estado == "cerrada"
