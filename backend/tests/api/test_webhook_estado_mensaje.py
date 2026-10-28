"""Webhook de estado de entrega (W8-W12): idempotente y monótono (§4.4)."""

from datetime import timedelta

from sqlalchemy import select
from wa import RUTA_ESTADO, crear_conv, crear_saliente, estado_webhook

from app.modulos.conversaciones.modelos import EventoMensaje, Mensaje


def preparar(db, reloj, estado="enviado", sid="SMa"):
    conv = crear_conv(db, reloj())
    return crear_saliente(db, conv, reloj(), estado=estado, sid=sid)


def test_firma_invalida_403(client, db, reloj):
    preparar(db, reloj)
    r = client.post(RUTA_ESTADO, data={"MessageSid": "SMa", "MessageStatus": "delivered"})
    assert r.status_code == 403 and db.scalar(select(EventoMensaje.id)) is None


def test_w8_delivered_pasa_a_entregado(client, firmar_twilio, db, reloj):
    m = preparar(db, reloj)
    assert estado_webhook(client, firmar_twilio, "SMa", "delivered").status_code == 204
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert m.estado == "entregado" and m.entregado_en == reloj()
    ev = db.scalar(select(EventoMensaje))
    assert (ev.proveedor_id, ev.estado_proveedor, ev.mensaje_id) == ("SMa", "delivered", m.id)


def test_w9_read_y_luego_delivered_queda_leido_con_dos_eventos(client, firmar_twilio, db, reloj):
    m = preparar(db, reloj)
    estado_webhook(client, firmar_twilio, "SMa", "read")
    estado_webhook(client, firmar_twilio, "SMa", "delivered")
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert m.estado == "leido" and m.leido_en is not None
    assert len(db.scalars(select(EventoMensaje)).all()) == 2


def test_w10_failed_tras_delivered_se_ignora(client, firmar_twilio, db, reloj):
    m = preparar(db, reloj)
    estado_webhook(client, firmar_twilio, "SMa", "delivered")
    estado_webhook(client, firmar_twilio, "SMa", "failed", ErrorCode="63016")
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert m.estado == "entregado" and m.error_codigo is None
    assert len(db.scalars(select(EventoMensaje)).all()) == 2


def test_failed_antes_de_entregar_guarda_el_codigo(client, firmar_twilio, db, reloj):
    m = preparar(db, reloj)
    estado_webhook(client, firmar_twilio, "SMa", "undelivered", ErrorCode="63016")
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert (m.estado, m.error_codigo) == ("fallido", "63016")


def test_w12_estado_duplicado_un_solo_evento(client, firmar_twilio, db, reloj):
    preparar(db, reloj)
    for _ in range(3):
        assert estado_webhook(client, firmar_twilio, "SMa", "delivered").status_code == 204
    assert len(db.scalars(select(EventoMensaje)).all()) == 1


def test_estados_intermedios_o_desconocidos_no_cambian_nada(client, firmar_twilio, db, reloj):
    m = preparar(db, reloj, estado="enviado")
    for estado in ("queued", "sent", "receiving", "rarisimo"):
        assert estado_webhook(client, firmar_twilio, "SMa", estado).status_code == 204
    db.expire_all()
    assert db.get(Mensaje, m.id).estado == "enviado"
    estados = {e.estado_proveedor for e in db.scalars(select(EventoMensaje))}
    assert estados == {"queued", "sent"}  # "receiving" y los desconocidos se ignoran


def test_estado_de_sid_desconocido_queda_pendiente_sin_mensaje(client, firmar_twilio, db):
    assert estado_webhook(client, firmar_twilio, "SMdesconocido", "delivered").status_code == 204
    ev = db.scalar(select(EventoMensaje))
    assert ev.mensaje_id is None and ev.proveedor_id == "SMdesconocido"


def test_estado_sin_parametros_validos_204(client, firmar_twilio):
    p = {"MessageStatus": "delivered"}
    r = client.post(RUTA_ESTADO, **firmar_twilio(RUTA_ESTADO, p))
    assert r.status_code == 204


def test_w11_estado_antes_de_que_el_worker_guarde_el_sid(
    client,
    firmar_twilio,
    db,
    reloj,
    correr_trabajos,
    proveedor_whatsapp,
    monkeypatch,
    crear_usuario,
):
    """El `delivered` llega mientras el mensaje está `enviando`: se aplica al guardar el SID."""
    from app.modulos.conversaciones import servicio as conversaciones
    from app.modulos.conversaciones.dueno import Humano
    from app.modulos.whatsapp import servicio_envio

    agente = crear_usuario("agente")
    conv = crear_conv(db, reloj())
    conversaciones.cambiar_dueno(db, conv, Humano(agente.id), None, agente.id, reloj())
    m = crear_saliente(db, conv, reloj(), estado="pendiente", autor="agente", usuario_id=agente.id)
    servicio_envio.encolar_envio(db, m, reloj())
    db.commit()

    enviar = proveedor_whatsapp.enviar_texto

    def enviar_y_recibir_estado(**kw):
        resultado = enviar(**kw)
        # Mientras el proveedor responde, el webhook ya recibió `delivered` (SID aún sin guardar).
        r = estado_webhook(client, firmar_twilio, resultado.proveedor_id, "delivered")
        assert r.status_code == 204
        return resultado

    monkeypatch.setattr(proveedor_whatsapp, "enviar_texto", enviar_y_recibir_estado)
    assert correr_trabajos() == 1
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert m.estado == "entregado" and m.proveedor_id.startswith("SMfalso")
    assert db.scalar(select(EventoMensaje)).mensaje_id == m.id
    assert m.enviado_en is not None and m.entregado_en is not None
    assert abs(m.entregado_en - reloj()) <= timedelta(seconds=1)
