"""Cambios de diseño post-QA (D-1, D-2) y asignación atómica (F-3)."""

from datetime import timedelta

import pytest
from escenario import cab
from test_tipificaciones import K, llamada_terminada, tipificar
from voz import contexto, llamar, params_saliente, webhook

from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.telefonia.modelos import Llamada


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


def tomar(client, agente, cc):
    return client.post(f"{K}/registros/{cc.id}/tomar", headers=cab(agente))


def test_d1_llamada_activa_impide_el_robo_aunque_venza_la_reserva(
    client, firmar_twilio, ctx, esc, crear_usuario, db, reloj
):
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    reloj.avanzar(minutes=40)  # la reserva venció, pero la llamada sigue activa
    r = tomar(client, otro, ctx.cc)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_RESERVADO"
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_por == ctx.agente.id


def test_d1_el_webhook_de_estado_renueva_la_reserva(client, firmar_twilio, ctx, db, reloj):
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    ll = db.query(Llamada).one()
    reloj.avanzar(minutes=10)
    p = {"CallSid": "CAcli", "CallStatus": "ringing", "SequenceNumber": "1"}
    webhook(client, firmar_twilio, "/webhooks/estado", p, f"llamada_id={ll.id}")
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_hasta == reloj() + timedelta(minutes=15)
    # Una vez terminada la llamada ya no se renueva.
    reloj.avanzar(minutes=1)
    p = {"CallSid": "CAcli", "CallStatus": "completed", "SequenceNumber": "2"}
    webhook(client, firmar_twilio, "/webhooks/estado", p, f"llamada_id={ll.id}")
    hasta = ctx.cc.reservado_hasta
    reloj.avanzar(minutes=5)
    p = {"CallSid": "CAcli", "CallStatus": "completed", "SequenceNumber": "3"}
    webhook(client, firmar_twilio, "/webhooks/estado", p, f"llamada_id={ll.id}")
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_hasta <= hasta + timedelta(minutes=1)


def test_d1_quitar_asignacion_con_tipificacion_pendiente_conserva_la_reserva(
    client, ctx, db, h_admin
):
    lid = llamada_terminada(client, ctx, db)
    r = client.put(
        f"/api/v1/campanas/{ctx.campana.id}/agentes", json={"usuario_ids": []}, headers=h_admin
    )
    assert r.status_code == 200
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_por == ctx.agente.id and ctx.cc.estado == "en_gestion"
    # Puede cerrar la gestión en curso...
    assert tipificar(client, ctx, lid, "rechazo").status_code == 201
    db.refresh(ctx.cc)
    assert ctx.cc.estado == "gestionado" and ctx.cc.reservado_por is None


def test_d1_desasignado_no_puede_tomar_nuevos(client, ctx, esc, db, h_admin):
    otro_registro = esc.registro(ctx.campana)
    client.put(
        f"/api/v1/campanas/{ctx.campana.id}/agentes", json={"usuario_ids": []}, headers=h_admin
    )
    r = tomar(client, ctx.agente, otro_registro)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"


def test_d1_quitar_asignacion_sin_llamada_sigue_liberando(client, ctx, db, h_admin):
    client.put(
        f"/api/v1/campanas/{ctx.campana.id}/agentes", json={"usuario_ids": []}, headers=h_admin
    )
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_por is None and ctx.cc.estado == "pendiente"


def test_f3_reserva_atomica_exige_asignacion(db, esc, ctx, reloj, crear_usuario):
    from app.modulos.consola.servicio import _reservar_atomico

    sin_asignar = crear_usuario("agente")
    otro = esc.registro(ctx.campana)
    ahora = reloj()
    assert not _reservar_atomico(db, otro.id, sin_asignar.id, ahora, ahora + timedelta(minutes=5))
    db.refresh(otro)
    assert otro.reservado_por is None


@pytest.mark.parametrize("intentos_previos", [0])
def test_d2_numero_errado_con_max_intentos_uno_queda_terminal(
    client, esc, crear_usuario, reloj, db, intentos_previos
):
    c = contexto(esc, crear_usuario, reloj, numeros=("+573001234567", "+573109876543"))
    c.campana.max_intentos = 1
    db.commit()
    lid = llamada_terminada(client, c, db, resultado="failed", contestar=False)
    r = tipificar(client, c, lid, "numero_errado")
    assert r.status_code == 201, r.text
    # queda otro teléfono utilizable, pero ya no hay intentos: mismo estado que no_contesta agotado
    assert r.json()["registro"] == {
        "estado": "gestionado",
        "intentos": 1,
        "proximo_intento_en": None,
    }
    # y no reaparece en la lista de trabajo
    items = client.get(f"{K}/registros", headers=cab(c.agente)).json()["items"]
    assert all(i["id"] != c.cc.id for i in items)


def test_d2_no_contesta_con_max_uno_es_igual(client, esc, crear_usuario, reloj, db):
    c = contexto(esc, crear_usuario, reloj)
    c.campana.max_intentos = 1
    db.commit()
    lid = llamada_terminada(client, c, db, resultado="no-answer", contestar=False)
    assert tipificar(client, c, lid, "no_contesta").json()["registro"]["estado"] == "gestionado"
    db.expire_all()
    assert db.get(CampanaCliente, c.cc.id).estado == "gestionado"
