"""Revisión 2 de la subfase 2A: B1, B2, B4, S1, S2, S6, S7."""

from datetime import timedelta

import pytest
from conftest import firma_independiente  # noqa: F401
from escenario import cab, telefono_de
from twilio.request_validator import RequestValidator
from voz import contexto, llamar, params_saliente, webhook

from app.config import Settings
from app.integraciones.twilio_firma import firma_twilio
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import EstadoAgente, Tipificacion
from app.modulos.telefonia import servicio
from app.modulos.telefonia.modelos import Llamada

S = "/api/v1/telefonia/simulacion"
K = "/api/v1/consola"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


def iniciar(client, ctx, db):
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(ctx.agente),
    )
    return r.json()["llamada_id"]


def evento(client, ctx, lid, **cuerpo):
    return client.post(f"{S}/llamadas/{lid}/eventos", json=cuerpo, headers=cab(ctx.agente))


# ---- B1 ----------------------------------------------------------------------------------------
def test_b1_ringing_tardio_no_resucita_una_llamada_terminada_instantanea_obsoleta(
    client, ctx, db, session_factory, reloj
):
    """Reproducción del revisor: R carga la llamada antes de que D (busy) confirme."""
    lid = iniciar(client, ctx, db)
    sr = session_factory()
    llamada_r = sr.get(Llamada, lid)
    assert llamada_r.estado == "iniciando"
    sd = session_factory()
    servicio.procesar_dial_terminado(
        sd, {"CallSid": llamada_r.call_sid, "DialCallStatus": "busy"}, str(lid), reloj()
    )
    sd.close()
    servicio._guardar_evento(sr, llamada_r, "CAcli", "ringing", 1, {}, reloj())
    servicio.aplicar_estado(sr, llamada_r, "ringing", None, reloj())
    sr.commit()
    sr.close()
    h = cab(ctx.agente)
    assert client.get(f"{K}/llamadas/{lid}", headers=h).json()["estado"] == "ocupado"
    t = client.post(
        f"{K}/tipificaciones", json={"llamada_id": lid, "resultado": "no_contesta"}, headers=h
    )
    assert t.status_code == 201, t.text
    assert client.get(f"{K}/estado", headers=h).json()["estado"] == "disponible"


@pytest.mark.parametrize("tardio", ["ringing", "in-progress", "answered"])
@pytest.mark.parametrize("terminal", ["busy", "no-answer", "failed", "canceled", "completed"])
def test_b1_webhooks_tardios_por_api_no_cambian_una_llamada_terminal(
    client, firmar_twilio, ctx, db, terminal, tardio
):
    lid = iniciar(client, ctx, db)
    ll = db.get(Llamada, lid)
    p = {"CallSid": ll.call_sid, "DialCallStatus": terminal, "DialCallSid": "CAcli"}
    webhook(client, firmar_twilio, "/twiml/dial-terminado", p, f"llamada_id={lid}")
    db.expire_all()
    final = db.get(Llamada, lid)
    antes = (final.estado, final.contestada_en, final.finalizada_en)
    assert final.estado in ("ocupado", "no_contesta", "fallida", "cancelada")
    p = {"CallSid": "CAcli", "CallStatus": tardio, "SequenceNumber": "9"}
    r = webhook(client, firmar_twilio, "/webhooks/estado", p, f"llamada_id={lid}")
    assert r.status_code == 204
    db.expire_all()
    despues = db.get(Llamada, lid)
    assert (despues.estado, despues.contestada_en, despues.finalizada_en) == antes
    assert db.get(EstadoAgente, ctx.agente.id).estado == "tipificando"


def test_b1_transiciones_solo_hacia_adelante(client, firmar_twilio, ctx, db):
    lid = iniciar(client, ctx, db)
    est = lambda s, q: webhook(  # noqa: E731
        client, firmar_twilio, "/webhooks/estado",
        {"CallSid": "CAcli", "CallStatus": s, "SequenceNumber": q}, f"llamada_id={lid}",
    )  # fmt: skip
    est("in-progress", "1")
    est("ringing", "2")  # no retrocede de en_curso a sonando
    db.expire_all()
    assert db.get(Llamada, lid).estado == "en_curso"


# ---- B2 ----------------------------------------------------------------------------------------
def terminar_contestada(client, ctx, lid, reloj, minutos=20):
    evento(client, ctx, lid, evento="contestada")
    reloj.avanzar(minutes=minutos)
    evento(client, ctx, lid, evento="finalizada", resultado="completed")


def test_b2_otro_agente_no_puede_tomar_un_registro_pendiente_de_tipificar(
    client, ctx, db, esc, crear_usuario, reloj
):
    lid = iniciar(client, ctx, db)
    terminar_contestada(client, ctx, lid, reloj)  # llamada de 20 min: la reserva original venció
    reloj.avanzar(minutes=10)
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    r = client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=cab(otro))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_RESERVADO"
    # Al tipificar A, el registro queda libre (o gestionado) y B ya puede tomarlo si procede.
    t = client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": "volver_a_llamar", "contacto_directo": False,
              "volver_a_llamar_en": "2026-10-26T10:00:00-05:00"},
        headers=cab(ctx.agente),
    )  # fmt: skip
    assert t.status_code == 201, t.text
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert cc.reservado_por is None


def test_b2_finalizar_renueva_la_reserva(client, ctx, db, reloj):
    lid = iniciar(client, ctx, db)
    evento(client, ctx, lid, evento="contestada")
    reloj.avanzar(minutes=40)  # sin webhooks intermedios
    evento(client, ctx, lid, evento="finalizada", resultado="completed")
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert cc.reservado_por == ctx.agente.id
    assert cc.reservado_hasta == reloj() + timedelta(minutes=15)


def test_b2_tipificar_no_toca_la_reserva_de_otro_agente(client, ctx, db, esc, crear_usuario, reloj):
    lid = iniciar(client, ctx, db)
    terminar_contestada(client, ctx, lid, reloj, minutos=1)
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    # Caso excepcional: la reserva pasó a otro agente (p. ej. datos previos a este control).
    cc = db.get(CampanaCliente, ctx.cc.id)
    cc.reservado_por = otro.id
    cc.estado = "en_gestion"
    db.commit()
    t = client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": "rechazo"},
        headers=cab(ctx.agente),
    )
    assert t.status_code == 201, t.text
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    # La reserva y el estado del registro son de B; los contadores y la tipificación sí se anotan.
    assert (cc.reservado_por, cc.estado) == (otro.id, "en_gestion")
    assert (cc.intentos, cc.ultimo_resultado) == (1, "rechazo")
    assert db.query(Tipificacion).one().usuario_id == ctx.agente.id
    assert db.get(EstadoAgente, ctx.agente.id).estado == "disponible"
    assert db.get(EstadoAgente, otro.id).estado == "disponible"


def test_b2_soltar_con_llamada_activa_o_sin_tipificar(client, ctx, db, reloj):
    lid = iniciar(client, ctx, db)
    h = cab(ctx.agente)
    r = client.post(f"{K}/registros/{ctx.cc.id}/soltar", headers=h)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "AGENTE_EN_LLAMADA"
    evento(client, ctx, lid, evento="contestada")
    evento(client, ctx, lid, evento="finalizada", resultado="completed")
    r = client.post(f"{K}/registros/{ctx.cc.id}/soltar", headers=h)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "TIPIFICACION_PENDIENTE"


# ---- S1 ----------------------------------------------------------------------------------------
def test_s1_ver_ficha_exige_asignacion_salvo_gestion_en_curso(client, ctx, db, h_admin):
    h = cab(ctx.agente)
    assert client.get(f"{K}/registros/{ctx.cc.id}", headers=h).status_code == 200
    client.put(
        f"/api/v1/campanas/{ctx.campana.id}/agentes", json={"usuario_ids": []}, headers=h_admin
    )
    # Sin llamada pendiente la reserva se liberó al desasignar -> REGISTRO_NO_RESERVADO.
    assert client.get(f"{K}/registros/{ctx.cc.id}", headers=h).status_code == 409


def test_s1_desasignado_con_llamada_pendiente_conserva_acceso_a_su_ficha(client, ctx, db, h_admin):
    lid = iniciar(client, ctx, db)
    h = cab(ctx.agente)
    client.put(
        f"/api/v1/campanas/{ctx.campana.id}/agentes", json={"usuario_ids": []}, headers=h_admin
    )
    assert client.get(f"{K}/registros/{ctx.cc.id}", headers=h).status_code == 200
    evento(client, ctx, lid, evento="finalizada", resultado="busy")
    assert client.get(f"{K}/registros/{ctx.cc.id}", headers=h).status_code == 200
    client.post(
        f"{K}/tipificaciones", json={"llamada_id": lid, "resultado": "no_contesta"}, headers=h
    )


def test_s1_ficha_de_agente_desasignado_sin_reserva_activa_da_403(client, ctx, db):
    from app.modulos.campanas.modelos import CampanaAgente

    db.query(CampanaAgente).delete()  # desasignado sin liberar la reserva (dato heredado)
    db.commit()
    r = client.get(f"{K}/registros/{ctx.cc.id}", headers=cab(ctx.agente))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"


# ---- S2 ----------------------------------------------------------------------------------------
def test_s2_dial_completed_con_duracion_cuenta_como_contestada(
    client, firmar_twilio, ctx, db, reloj
):
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    ll = db.query(Llamada).one()
    reloj.avanzar(seconds=45)
    p = {"CallSid": ll.call_sid, "DialCallStatus": "completed", "DialCallDuration": "40"}
    webhook(client, firmar_twilio, "/twiml/dial-terminado", p, f"llamada_id={ll.id}")
    db.refresh(ll)
    assert ll.estado == "completada" and ll.duracion_segundos == 40
    assert ll.contestada_en is not None


@pytest.mark.parametrize("extra", [{}, {"DialCallDuration": "0"}])
def test_s2_completed_sin_duracion_sigue_siendo_no_contesta(client, firmar_twilio, ctx, db, extra):
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    ll = db.query(Llamada).one()
    p = {"CallSid": ll.call_sid, "DialCallStatus": "completed", **extra}
    webhook(client, firmar_twilio, "/twiml/dial-terminado", p, f"llamada_id={ll.id}")
    db.refresh(ll)
    assert ll.estado == "no_contesta"


def test_s2_la_duracion_de_la_pierna_del_agente_no_se_usa(client, firmar_twilio, ctx, db, reloj):
    llamar(client, firmar_twilio, params_saliente(ctx, db))
    ll = db.query(Llamada).one()
    webhook(
        client, firmar_twilio, "/webhooks/estado",
        {"CallSid": ll.call_sid, "CallStatus": "in-progress", "SequenceNumber": "1"},
    )  # fmt: skip
    reloj.avanzar(seconds=30)
    webhook(
        client, firmar_twilio, "/webhooks/estado",
        {"CallSid": ll.call_sid, "CallStatus": "completed", "CallDuration": "999"},
    )  # fmt: skip
    db.refresh(ll)
    assert ll.estado == "completada" and ll.duracion_segundos == 30


# ---- S6 / S7 -----------------------------------------------------------------------------------
@pytest.mark.parametrize("entorno", ["produccion"])
def test_s6_proveedor_falso_exige_token_propio_fuera_de_test_y_desarrollo(entorno):
    from app.config import TOKEN_TWILIO_EJEMPLO

    base = {"_env_file": None, "entorno": entorno, "jwt_secreto": "x" * 32,
            "telefonia_proveedor": "falso",
            "public_base_url": "https://app.empresa.co"}  # fmt: skip
    for token in (TOKEN_TWILIO_EJEMPLO, ""):
        with pytest.raises(ValueError):
            Settings(**base, twilio_auth_token=token)
    assert Settings(**base, twilio_auth_token="token-real")
    for libre in ("desarrollo", "test"):
        assert Settings(_env_file=None, entorno=libre, jwt_secreto="x" * 32)


@pytest.mark.parametrize(
    "params",
    [
        {"a": ["1", "1"], "b": "x"},  # valor repetido idéntico: cuenta una vez
        {"a": ["2", "1", "2"]},
        {"z": ["b", "a"], "y": "1"},
        {"a": "1"},
        {},
    ],
)
def test_s7_firma_igual_que_la_libreria_de_twilio(params):
    url = "https://pruebas.example.com/api/v1/telefonia/webhooks/estado?llamada_id=1"
    esperada = RequestValidator("tok").compute_signature(url, MultiDict(params))
    assert firma_twilio(url, params, "tok") == esperada


class MultiDict:
    """Imita el MultiDict de Flask/Starlette que usa `RequestValidator` (getlist)."""

    def __init__(self, datos):
        self._d = {k: ([v] if isinstance(v, str) else list(v)) for k, v in datos.items()}

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __bool__(self):
        return bool(self._d)

    def getlist(self, k):
        return self._d[k]
