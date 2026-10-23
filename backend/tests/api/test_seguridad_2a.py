"""Seguridad específica de 2A: IDOR entre agentes, fuga del teléfono y firmas de Twilio."""

import json
import logging
import re

import pytest
from conftest import BASE_URL, firma_independiente
from escenario import cab, telefono_de
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect  # noqa: F401
from voz import contexto, llamar, params_saliente

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.consola.modelos import EstadoAgente, Tipificacion
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.telefonia.modelos import EventoLlamada, Llamada
from app.seguridad import crear_token

K = "/api/v1/consola"
S = "/api/v1/telefonia/simulacion"
NUMERO = "+573001234567"
NACIONAL = "3001234567"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


@pytest.fixture()
def otro(crear_usuario):
    return crear_usuario("agente")


def _llamada(client, ctx, db):
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200 and r.json()["permitida"], r.text
    return r.json()["llamada_id"]


def _terminar(client, ctx, lid):
    h = cab(ctx.agente)
    client.post(f"{S}/llamadas/{lid}/eventos", json={"evento": "contestada"}, headers=h)
    client.post(
        f"{S}/llamadas/{lid}/eventos",
        json={"evento": "finalizada", "resultado": "completed", "duracion_segundos": 5},
        headers=h,
    )


# ---- IDOR ------------------------------------------------------------------------------------
def test_agente_no_asignado_no_toma_ni_lista_ni_ve_registros_de_otra_campana(
    client, ctx, otro, esc, db
):
    h = cab(otro)
    esc.asignar(esc.campana(), otro)  # asignado a OTRA campaña
    assert client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=h).status_code == 403
    r = client.get(f"{K}/registros?campana_id={ctx.campana.id}", headers=h)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"
    assert all(
        i["campana_id"] != ctx.campana.id
        for i in client.get(f"{K}/registros", headers=h).json()["items"]
    )
    assert client.get(f"{K}/registros/{ctx.cc.id}", headers=h).status_code == 409
    assert client.post(f"{K}/registros/{ctx.cc.id}/soltar", headers=h).status_code == 409
    db.expire_all()
    assert db.get(type(ctx.cc), ctx.cc.id).reservado_por == ctx.agente.id  # sin cambios


def test_otro_agente_no_puede_tipificar_ni_consultar_ni_simular_la_llamada_ajena(
    client, ctx, otro, esc, db
):
    esc.asignar(ctx.campana, otro)  # incluso asignado a la misma campaña
    lid = _llamada(client, ctx, db)
    _terminar(client, ctx, lid)
    h = cab(otro)
    r = client.post(
        f"{K}/tipificaciones", json={"llamada_id": lid, "resultado": "rechazo"}, headers=h
    )
    assert r.status_code == 404
    assert client.get(f"{K}/llamadas/{lid}", headers=h).status_code == 404
    ev = {"evento": "finalizada", "resultado": "failed"}
    assert client.post(f"{S}/llamadas/{lid}/eventos", json=ev, headers=h).status_code == 404
    assert db.query(Tipificacion).count() == 0
    db.expire_all()
    assert db.get(EstadoAgente, ctx.agente.id).estado == "tipificando"  # intacto
    assert db.get(Llamada, lid).estado == "completada"


def test_agente_no_asignado_no_puede_llamar_un_registro_ajeno_ni_cambia_estados(
    client, ctx, otro, esc, db, reloj
):
    esc.estado(otro, "disponible", reloj())
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(otro),
    )
    assert r.status_code == 200 and r.json()["permitida"] is False
    assert r.json()["motivos"][0]["codigo"] == "CAMPANA_NO_ASIGNADA"
    assert db.query(IntentoContacto).count() == 0
    db.expire_all()
    assert db.get(EstadoAgente, otro.id).estado == "disponible"


def test_asignado_pero_sin_reserva_no_puede_llamar_el_registro_de_un_companero(
    client, ctx, otro, esc, db, reloj
):
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(otro),
    )
    assert r.json()["permitida"] is False
    assert r.json()["motivos"][0]["codigo"] == "REGISTRO_NO_RESERVADO"


def test_telefono_de_otro_cliente_no_se_marca_aunque_el_registro_sea_propio(
    client, firmar_twilio, ctx, esc, db
):
    ajeno = esc.registro(ctx.campana, numeros=("+573115559999",))
    p = params_saliente(ctx, db, telefono_id=str(telefono_de(db, ajeno).id))
    r = llamar(client, firmar_twilio, p)
    assert "573115559999" not in r.text and "<Dial" not in r.text
    assert db.query(Llamada).count() == 0


def test_call_sid_de_otro_agente_no_devuelve_su_twiml(client, firmar_twilio, ctx, esc, db, otro):
    p = params_saliente(ctx, db, sid="CA-IDOR")
    assert "<Dial" in llamar(client, firmar_twilio, p).text
    p2 = dict(p, From=f"client:agente_{otro.id}")
    r = llamar(client, firmar_twilio, p2)
    assert "<Dial" not in r.text and "573001234567" not in r.text


def test_supervisor_y_admin_no_usan_endpoints_de_agente(client, ctx, h_supervisor, h_admin, db):
    for h in (h_supervisor, h_admin):
        assert client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=h).status_code == 403
        assert client.post(f"{S}/llamadas", json={}, headers=h).status_code == 403


# ---- El teléfono completo no llega al agente ---------------------------------------------------
PATRON = re.compile(r"\+?57?3001234567|3001234567|573001234567")


def _sin_numero(texto: str, donde: str) -> None:
    assert not PATRON.search(texto), f"número completo en {donde}: {texto[:300]}"


def test_el_numero_completo_nunca_llega_al_agente_por_rest_ni_websocket(
    client, ctx, db, esc, reloj, caplog
):
    from test_websocket import recibir, url

    caplog.set_level(logging.DEBUG)
    h = cab(ctx.agente)
    cuerpos: list[tuple[str, str]] = []

    def anotar(nombre, r):
        cuerpos.append((nombre, r.text))
        return r

    otro_cc = esc.registro(ctx.campana, numeros=("+576015550123",))
    with client.websocket_connect(url(ctx.agente)) as ws:
        recibir(ws, "conexion.lista")
        anotar("campanas", client.get(f"{K}/campanas", headers=h))
        anotar("registros", client.get(f"{K}/registros", headers=h))
        anotar("ficha", client.get(f"{K}/registros/{ctx.cc.id}", headers=h))
        anotar("tomar-otro", client.post(f"{K}/registros/{otro_cc.id}/tomar", headers=h))
        anotar("tomar", client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=h))
        anotar("estado", client.get(f"{K}/estado", headers=h))
        lid = _llamada(client, ctx, db)
        _terminar(client, ctx, lid)
        anotar("llamada", client.get(f"{K}/llamadas/{lid}", headers=h))
        anotar("estado2", client.get(f"{K}/estado", headers=h))
        anotar("llamada-ajena", client.get(f"{K}/llamadas/99999", headers=h))
        r = anotar(
            "tipificar",
            client.post(
                f"{K}/tipificaciones",
                json={"llamada_id": lid, "resultado": "numero_errado", "observacion": "no existe"},
                headers=h,
            ),
        )
        assert r.status_code == 201, r.text
        anotar("registros2", client.get(f"{K}/registros", headers=h))
        # Eventos del socket del agente (el servidor ya emitió todo antes de este punto).
        eventos = []
        ws.send_json({"tipo": "ping"})
        for _ in range(60):
            ev = ws.receive_json()
            if ev["tipo"] == "pong":
                break
            eventos.append(json.dumps(ev, ensure_ascii=False))
    for nombre, texto in cuerpos:
        _sin_numero(texto, nombre)
    for e in eventos:
        _sin_numero(e, "websocket")
    assert any('"tipo": "llamada.estado"' in e for e in eventos)
    # Ni en logs ni en la auditoría.
    _sin_numero("\n".join(r.getMessage() for r in caplog.records), "logs")
    for a in db.query(Auditoria).all():
        _sin_numero(json.dumps(a.detalle or {}), f"auditoria {a.accion}")
    for ev in db.query(EventoLlamada).all():
        _sin_numero(json.dumps(ev.datos), "eventos_llamada")


def test_ficha_enmascara_todos_los_telefonos(client, ctx, esc, db):
    cc = esc.registro(ctx.campana, numeros=("+573001234568", "+576015550123", "+573229876543"))
    esc.reservar(
        cc,
        ctx.agente,
        __import__("datetime").datetime(2026, 10, 23, 15, 15, tzinfo=__import__("datetime").UTC),
    )
    r = client.get(f"{K}/registros/{cc.id}", headers=cab(ctx.agente))
    assert r.status_code == 200
    for t in r.json()["telefonos"]:
        assert re.fullmatch(r"\+\d{2,3}\d{0,3}\*\*\*\*\d{3}", t["numero_mascara"]), t
        assert "numero_e164" not in t and "numero" not in t
    assert not re.search(r"\+?57\d{8,10}", r.text)


# ---- Firmas de Twilio ------------------------------------------------------------------------
RUTAS_FIRMA = [
    ("/api/v1/telefonia/twiml/saliente", ""),
    ("/api/v1/telefonia/twiml/aviso-grabacion", "llamada_id=1"),
    ("/api/v1/telefonia/twiml/dial-terminado", "llamada_id=1"),
    ("/api/v1/telefonia/webhooks/estado", ""),
    ("/api/v1/telefonia/webhooks/grabacion", "llamada_id=1"),
]


@pytest.mark.parametrize(("ruta", "consulta"), RUTAS_FIRMA)
def test_firma_de_otra_url_otro_token_o_parametros_alterados_es_403(client, db, ruta, consulta):
    params = {"CallSid": "CA1", "CallStatus": "completed"}
    completa = ruta + (f"?{consulta}" if consulta else "")
    bueno = firma_independiente(BASE_URL + completa, params)
    casos = {
        "otra ruta": firma_independiente(BASE_URL + "/api/v1/telefonia/webhooks/otra", params),
        "otro host": firma_independiente("https://evil.example.com" + completa, params),
        "http": firma_independiente("http://pruebas.example.com" + completa, params),
        "otro token": firma_independiente(BASE_URL + completa, params, token="otro-token"),
        "sin query": firma_independiente(BASE_URL + ruta, params) if consulta else None,
        "param extra": firma_independiente(BASE_URL + completa, {**params, "X": "1"}),
        "base64 truncado": bueno[:-4],
        "vacía": "",
        "espacios": " " + bueno,
        "minúsculas": bueno.lower() if bueno.lower() != bueno else "zz",
    }
    for nombre, firma in casos.items():
        if firma is None:
            continue
        r = client.post(completa, data=params, headers={"X-Twilio-Signature": firma})
        assert r.status_code == 403, (nombre, r.status_code)
        assert r.json()["error"]["codigo"] == "FIRMA_INVALIDA"
    # Parámetro alterado tras firmar.
    r = client.post(
        completa, data={**params, "CallStatus": "failed"}, headers={"X-Twilio-Signature": bueno}
    )
    assert r.status_code == 403
    # Control positivo: la firma buena sí pasa (no es 403).
    assert (
        client.post(completa, data=params, headers={"X-Twilio-Signature": bueno}).status_code != 403
    )
    assert db.query(Llamada).count() == 0


@pytest.mark.parametrize(("ruta", "consulta"), RUTAS_FIRMA)
def test_cuerpos_no_formulario_con_firma_de_otro_tipo_no_dan_500(client, db, ruta, consulta):
    completa = ruta + (f"?{consulta}" if consulta else "")
    for kw in (
        {"json": {"CallSid": "CA1"}},
        {
            "content": b"\xff\xfe\x00garbage",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        },
        {
            "content": b"CallSid=%ZZ&a",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        },
        {"content": b"", "headers": {"Content-Type": "multipart/form-data; boundary=x"}},
    ):
        r = client.post(completa, **kw)
        assert r.status_code in (403, 400, 422), (kw, r.status_code)


def test_firma_con_parametros_repetidos_y_unicode(client, db, ctx, firmar_twilio):
    """El orden y los duplicados no deben permitir falsificar: la firma cubre todos los valores."""
    params = {"CallSid": "CAu", "CallStatus": "ringing", "SequenceNumber": "0"}
    ruta = "/api/v1/telefonia/webhooks/estado"
    firma = firma_independiente(BASE_URL + ruta, params)
    r = client.post(
        ruta,
        content="CallSid=CAu&CallStatus=ringing&SequenceNumber=0&CallStatus=completed",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": firma,
        },
    )
    assert r.status_code == 403  # un valor extra de CallStatus invalida la firma


def test_simulacion_no_aparece_en_openapi_ni_responde_en_produccion_ni_con_twilio():
    from app.config import Settings
    from app.main import create_app

    casos = [
        dict(entorno="produccion", twilio_auth_token="token-real", public_base_url="https://x.co",
             jwt_secreto="x" * 32),
        dict(entorno="produccion", twilio_auth_token="token-real", public_base_url="https://x.co",
             jwt_secreto="x" * 32, telefonia_proveedor="falso"),
        dict(entorno="desarrollo", jwt_secreto="x" * 32, telefonia_proveedor="twilio",
             twilio_account_sid="AC1", twilio_auth_token="t", twilio_api_key_sid="SK1",
             twilio_api_key_secret="s", twilio_twiml_app_sid="AP1",
             twilio_numero_saliente="+576015550000", public_base_url="https://x.co"),
    ]  # fmt: skip
    for kw in casos:
        app = create_app(Settings(_env_file=None, **kw))
        with TestClient(app) as c:
            rutas = c.get("/openapi.json").json()["paths"]
            assert not [p for p in rutas if "simulacion" in p], kw
            h = {"Authorization": "Bearer " + crear_token(1, "agente")[0]}
            assert (
                c.post(
                    f"{S}/llamadas", json={"campana_cliente_id": 1, "telefono_id": 1}, headers=h
                ).status_code
                == 404
            )
            assert (
                c.post(
                    f"{S}/llamadas/1/eventos", json={"evento": "contestada"}, headers=h
                ).status_code
                == 404
            )


def test_produccion_con_secreto_de_ejemplo_o_token_de_twilio_de_ejemplo_no_arranca():
    from app.config import SECRETO_EJEMPLO, TOKEN_TWILIO_EJEMPLO, Settings

    base = dict(entorno="produccion", public_base_url="https://x.co", jwt_secreto="x" * 40)
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{**base, "twilio_auth_token": TOKEN_TWILIO_EJEMPLO})
    with pytest.raises(ValueError):
        Settings(
            _env_file=None, **{**base, "jwt_secreto": SECRETO_EJEMPLO, "twilio_auth_token": "real"}
        )
