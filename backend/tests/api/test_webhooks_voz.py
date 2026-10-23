from datetime import timedelta

import pytest
from voz import contexto, llamar, params_saliente, webhook

from app.modulos.consola.modelos import EstadoAgente
from app.modulos.telefonia.modelos import EventoLlamada, Grabacion, Llamada


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


@pytest.fixture()
def llamada(client, firmar_twilio, ctx, db):
    """Llamada permitida en estado `iniciando`; devuelve el objeto y su pierna del cliente."""
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    ll = db.query(Llamada).one()
    return ll


def estado(client, firmar_twilio, ll, status, seq="1", sid="CAcli", **extra):
    p = {"CallSid": sid, "CallStatus": status, "SequenceNumber": seq, **extra}
    return webhook(client, firmar_twilio, "/webhooks/estado", p, f"llamada_id={ll.id}")


def dial_terminado(client, firmar_twilio, ll, status, **extra):
    p = {"CallSid": ll.call_sid, "DialCallStatus": status, "DialCallSid": "CAcli", **extra}
    return webhook(client, firmar_twilio, "/twiml/dial-terminado", p, f"llamada_id={ll.id}")


def test_secuencia_completa_deja_completada(client, firmar_twilio, llamada, db, reloj, ctx):
    ll = llamada
    assert estado(client, firmar_twilio, ll, "initiated", "0").status_code == 204
    reloj.avanzar(seconds=3)
    assert estado(client, firmar_twilio, ll, "ringing", "1").status_code == 204
    db.refresh(ll)
    assert ll.estado == "sonando" and ll.call_sid_cliente == "CAcli"
    reloj.avanzar(seconds=9)
    estado(client, firmar_twilio, ll, "in-progress", "2")
    db.refresh(ll)
    assert ll.estado == "en_curso" and ll.contestada_en == reloj()
    reloj.avanzar(seconds=60)
    estado(client, firmar_twilio, ll, "completed", "3", CallDuration="60")
    db.refresh(ll)
    assert (ll.estado, ll.duracion_segundos, ll.finalizada_en) == ("completada", 60, reloj())
    ag = db.get(EstadoAgente, ctx.agente.id)
    assert (ag.estado, ag.llamada_id) == ("tipificando", ll.id)
    assert db.query(EventoLlamada).count() == 4


def test_no_answer_deja_no_contesta(client, firmar_twilio, llamada, db):
    estado(client, firmar_twilio, llamada, "ringing")
    estado(client, firmar_twilio, llamada, "no-answer", "2", CallDuration="0")
    db.refresh(llamada)
    assert llamada.estado == "no_contesta" and llamada.contestada_en is None


@pytest.mark.parametrize(
    ("status", "esperado"),
    [("busy", "ocupado"), ("failed", "fallida"), ("canceled", "cancelada")],
)
def test_otros_terminales(client, firmar_twilio, llamada, db, status, esperado):
    estado(client, firmar_twilio, llamada, status)
    db.refresh(llamada)
    assert llamada.estado == esperado


def test_completed_sin_haber_contestado_es_no_contesta(client, firmar_twilio, llamada, db):
    estado(client, firmar_twilio, llamada, "completed")
    db.refresh(llamada)
    assert llamada.estado == "no_contesta"


def test_duplicados_no_duplican_eventos_ni_efectos(client, firmar_twilio, llamada, db, ctx):
    for _ in range(3):
        assert estado(client, firmar_twilio, llamada, "in-progress", "5").status_code == 204
    assert db.query(EventoLlamada).count() == 1
    estado(client, firmar_twilio, llamada, "completed", "6", CallDuration="10")
    estado(client, firmar_twilio, llamada, "completed", "6", CallDuration="99")
    db.refresh(llamada)
    assert llamada.duracion_segundos == 10 and db.query(EventoLlamada).count() == 2
    from app.modulos.consola.modelos import HistorialEstadoAgente

    tip = db.query(HistorialEstadoAgente).filter_by(estado="tipificando").count()
    assert tip == 1


def test_estado_terminal_no_retrocede(client, firmar_twilio, llamada, db):
    estado(client, firmar_twilio, llamada, "completed", "9")
    estado(client, firmar_twilio, llamada, "ringing", "10")
    estado(client, firmar_twilio, llamada, "in-progress", "11")
    db.refresh(llamada)
    assert llamada.estado == "no_contesta"


def test_dial_terminado_y_estado_en_cualquier_orden_finalizan_una_vez(
    client, firmar_twilio, esc, crear_usuario, reloj, db
):
    for orden in ("dial_primero", "estado_primero"):
        ctx = contexto(esc, crear_usuario, reloj)
        llamar(client, firmar_twilio, params_saliente(ctx, db, sid=f"CA-{orden}"))
        ll = db.query(Llamada).filter_by(call_sid=f"CA-{orden}").one()
        sid = f"CAcli-{orden}"
        estado(client, firmar_twilio, ll, "in-progress", "1", sid=sid)
        reloj.avanzar(seconds=30)
        pasos = [
            lambda ll=ll: dial_terminado(
                client, firmar_twilio, ll, "completed", DialCallDuration="30"
            ),
            lambda ll=ll, sid=sid: estado(
                client, firmar_twilio, ll, "completed", "2", sid=sid, CallDuration="31"
            ),
        ]
        if orden == "estado_primero":
            pasos.reverse()
        for paso in pasos:
            paso()
        db.refresh(ll)
        assert ll.estado == "completada"
        assert ll.duracion_segundos == (30 if orden == "dial_primero" else 31)  # gana la primera
        from app.modulos.consola.modelos import HistorialEstadoAgente

        assert (
            db.query(HistorialEstadoAgente)
            .filter_by(usuario_id=ctx.agente.id, estado="tipificando")
            .count()
            == 1
        )
        reloj.avanzar(minutes=1)


def test_dial_terminado_responde_hangup(client, firmar_twilio, llamada, db):
    r = dial_terminado(client, firmar_twilio, llamada, "busy")
    assert r.status_code == 200 and "<Hangup" in r.text
    assert r.headers["content-type"].startswith("application/xml")
    db.refresh(llamada)
    assert llamada.estado == "ocupado"
    again = dial_terminado(client, firmar_twilio, llamada, "busy")  # duplicado: igual respuesta
    assert again.status_code == 200 and again.text == r.text
    assert db.query(EventoLlamada).filter_by(estado_proveedor="dial-terminado").count() == 1


def test_estado_por_pierna_del_agente(client, firmar_twilio, llamada, db):
    p = {"CallSid": llamada.call_sid, "CallStatus": "in-progress", "SequenceNumber": "1"}
    assert webhook(client, firmar_twilio, "/webhooks/estado", p).status_code == 204
    db.refresh(llamada)
    assert llamada.estado == "en_curso" and llamada.call_sid_cliente is None
    p = {"CallSid": llamada.call_sid, "CallStatus": "completed", "CallDuration": "5"}
    webhook(client, firmar_twilio, "/webhooks/estado", p)
    db.refresh(llamada)
    assert llamada.estado == "completada"


def test_eventos_no_guardan_numeros(client, firmar_twilio, llamada, db):
    estado(
        client, firmar_twilio, llamada, "completed",
        To="+573001234567", From="+576015550000", CallDuration="3", SipResponseCode="200",
    )  # fmt: skip
    ev = db.query(EventoLlamada).one()
    assert ev.datos == {"CallDuration": "3", "SipResponseCode": "200"}


def test_llamada_desconocida_204_sin_efectos(client, firmar_twilio, db, ctx):
    p = {"CallSid": "CAdesconocida", "CallStatus": "completed"}
    assert webhook(client, firmar_twilio, "/webhooks/estado", p).status_code == 204
    assert (
        webhook(client, firmar_twilio, "/webhooks/estado", p, "llamada_id=999").status_code == 204
    )
    assert (
        webhook(client, firmar_twilio, "/webhooks/estado", p, "llamada_id=abc").status_code == 204
    )
    assert webhook(client, firmar_twilio, "/webhooks/estado", {}).status_code == 204
    assert db.query(EventoLlamada).count() == 0
    r = webhook(
        client,
        firmar_twilio,
        "/twiml/dial-terminado",
        {"CallSid": "CAx", "DialCallStatus": "completed"},
    )
    assert r.status_code == 200 and "<Hangup" in r.text


def test_grabacion_upsert(client, firmar_twilio, llamada, db):
    p = {
        "RecordingSid": "RE1",
        "RecordingUrl": "https://api.twilio.com/rec/RE1",
        "RecordingStatus": "completed",
        "RecordingDuration": "42",
        "RecordingChannels": "2",
    }
    consulta = f"llamada_id={llamada.id}"
    assert webhook(client, firmar_twilio, "/webhooks/grabacion", p, consulta).status_code == 204
    g = db.query(Grabacion).one()
    assert (g.llamada_id, g.duracion_segundos, g.canales, g.estado) == (
        llamada.id,
        42,
        2,
        "completed",
    )
    webhook(
        client, firmar_twilio, "/webhooks/grabacion", {**p, "RecordingDuration": "44"}, consulta
    )
    db.expire_all()
    assert db.query(Grabacion).count() == 1 and db.query(Grabacion).one().duracion_segundos == 44
    webhook(
        client, firmar_twilio, "/webhooks/grabacion", p, "llamada_id=999"
    )  # llamada desconocida
    assert db.query(Grabacion).count() == 1


def test_aviso_de_grabacion(client, firmar_twilio, llamada):
    r = webhook(
        client,
        firmar_twilio,
        "/twiml/aviso-grabacion",
        {"CallSid": "CAcli"},
        f"llamada_id={llamada.id}",
    )
    assert (
        r.status_code == 200 and "grabada y monitoreada" in r.text and 'language="es-MX"' in r.text
    )


@pytest.mark.parametrize(
    "ruta",
    [
        "/api/v1/telefonia/twiml/saliente",
        "/api/v1/telefonia/twiml/aviso-grabacion?llamada_id=1",
        "/api/v1/telefonia/twiml/dial-terminado?llamada_id=1",
        "/api/v1/telefonia/webhooks/estado",
        "/api/v1/telefonia/webhooks/grabacion?llamada_id=1",
    ],
)
def test_firma_invalida_403_en_todos_los_endpoints_de_twilio(client, db, ruta):
    for headers in ({}, {"X-Twilio-Signature": "firma-mala"}):
        r = client.post(ruta, data={"CallSid": "CA1"}, headers=headers)
        assert r.status_code == 403
        assert r.json()["error"] == {
            "codigo": "FIRMA_INVALIDA",
            "mensaje": "Firma inválida.",
            "detalles": [],
        }
    assert db.query(EventoLlamada).count() == 0


def test_tiempo_de_ahora_se_toma_del_reloj(client, firmar_twilio, llamada, db, reloj):
    reloj.avanzar(minutes=5)
    estado(client, firmar_twilio, llamada, "in-progress")
    db.refresh(llamada)
    assert llamada.contestada_en - llamada.iniciada_en == timedelta(minutes=5)
