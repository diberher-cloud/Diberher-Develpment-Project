import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import pytest
from escenario import telefono_de
from voz import RUTA_SALIENTE as RUTA
from voz import contexto, llamar, params_saliente

from app.config import get_settings
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.consola.modelos import EstadoAgente
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.telefonia.modelos import Llamada

B = "https://pruebas.example.com"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


def params(ctx, db, sid="CA0001", **kw):
    return params_saliente(ctx, db, sid, **kw)


def bloqueada(r, codigo):
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    raiz = ET.fromstring(r.text)
    assert raiz.find("Hangup") is not None and raiz.find("Say") is not None
    return codigo


def test_permitida_xml_literal_y_efectos(client, firmar_twilio, ctx, db, reloj):
    tel = telefono_de(db, ctx.cc)
    r = llamar(client, firmar_twilio, params(ctx, db))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    ll = db.query(Llamada).one()
    esperado = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+576015550000" answerOnBridge="true" timeout="30" timeLimit="3600"
        record="record-from-answer-dual"
        recordingStatusCallback="{B}/api/v1/telefonia/webhooks/grabacion?llamada_id={ll.id}"
        recordingStatusCallbackEvent="completed"
        action="{B}/api/v1/telefonia/twiml/dial-terminado?llamada_id={ll.id}" method="POST">
    <Number url="{B}/api/v1/telefonia/twiml/aviso-grabacion?llamada_id={ll.id}" method="POST"
            statusCallback="{B}/api/v1/telefonia/webhooks/estado?llamada_id={ll.id}"
            statusCallbackEvent="initiated ringing answered completed"
            statusCallbackMethod="POST">{tel.numero_e164}</Number>
  </Dial>
</Response>"""
    assert ET.canonicalize(r.text, strip_text=True) == ET.canonicalize(esperado, strip_text=True)
    assert (ll.estado, ll.usuario_id, ll.call_sid, ll.motivos_bloqueo) == (
        "iniciando", ctx.agente.id, "CA0001", [],
    )  # fmt: skip
    intento = db.query(IntentoContacto).one()
    assert (intento.canal, intento.iniciado_por, intento.contacto_directo) == (
        "voz",
        "empresa",
        False,
    )
    assert intento.politica_version == 1 and intento.tipo_campana == "cobranza"
    assert intento.cliente_id == ctx.cc.cliente_id and ll.intento_contacto_id == intento.id
    estado = db.get(EstadoAgente, ctx.agente.id)
    assert (estado.estado, estado.llamada_id) == ("en_llamada", ll.id)
    db.refresh(ctx.cc)
    assert ctx.cc.reservado_hasta == datetime(2026, 10, 23, 15, 30, tzinfo=UTC)
    assert db.query(Auditoria).filter_by(accion="llamada.iniciada").one().detalle == {
        "llamada_id": ll.id
    }


def test_sin_grabar_omite_record_y_url(client, firmar_twilio, ctx, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "telefonia_grabar", False)
    r = llamar(client, firmar_twilio, params(ctx, db))
    dial = ET.fromstring(r.text).find("Dial")
    assert "record" not in dial.attrib and "recordingStatusCallback" not in dial.attrib
    numero = dial.find("Number")
    assert "url" not in numero.attrib and "method" not in numero.attrib


def test_idempotencia_por_callsid(client, firmar_twilio, ctx, db):
    a = llamar(client, firmar_twilio, params(ctx, db))
    b = llamar(client, firmar_twilio, params(ctx, db))
    assert a.text == b.text
    assert db.query(Llamada).count() == 1 and db.query(IntentoContacto).count() == 1


def test_idempotencia_de_bloqueada(client, firmar_twilio, ctx, db, esc, reloj):
    esc.estado(ctx.agente, "pausa", reloj())
    a = llamar(client, firmar_twilio, params(ctx, db))
    esc.estado(ctx.agente, "disponible", reloj())
    b = llamar(client, firmar_twilio, params(ctx, db))
    assert a.text == b.text and "<Hangup" in b.text
    assert db.query(Llamada).count() == 1


def test_destino_nunca_viene_de_la_peticion(client, firmar_twilio, ctx, db):
    p = params(ctx, db, To="+573999999999", Called="+573888888888", numero="+573777777777")
    r = llamar(client, firmar_twilio, p)
    assert "+573001234567" in r.text
    assert "999999999" not in r.text and "888888888" not in r.text and "777777777" not in r.text


def test_parametros_invalidos_no_dejan_fila(client, firmar_twilio, ctx, db, esc):
    otro = esc.registro(ctx.campana, numeros=("+573115550000",))
    tel_ajeno = telefono_de(db, otro)
    for p in (
        params(ctx, db, telefono_id=str(tel_ajeno.id)),  # de otro cliente
        params(ctx, db, telefono_id="abc"),
        params(ctx, db, telefono_id="99999999"),
        params(ctx, db, campana_cliente_id="x"),
        params(ctx, db, campana_cliente_id=None),
        params(ctx, db, campana_cliente_id="99999999"),
    ):
        r = llamar(client, firmar_twilio, p)
        bloqueada(r, "PARAMETROS_INVALIDOS")
    assert db.query(Llamada).count() == 0


def test_agente_invalido_no_deja_fila(client, firmar_twilio, ctx, db, crear_usuario):
    sup = crear_usuario("supervisor")
    inactivo = crear_usuario("agente", activo=False)
    for origen in ("client:agente_99999", f"client:agente_{sup.id}", f"client:agente_{inactivo.id}",
                   "client:otro", "+573001234567", ""):  # fmt: skip
        bloqueada(llamar(client, firmar_twilio, params(ctx, db, From=origen)), "AGENTE_INVALIDO")
    assert db.query(Llamada).count() == 0 and db.query(IntentoContacto).count() == 0


def test_account_sid_solo_se_verifica_con_twilio(client, firmar_twilio, ctx, db, monkeypatch):
    from app.integraciones.telefonia.fabrica import obtener_proveedor, reiniciar_proveedor
    from app.integraciones.telefonia.twilio import ProveedorTwilio
    from app.main import app

    s = get_settings()
    monkeypatch.setattr(s, "twilio_account_sid", "ACreal")
    app.dependency_overrides[obtener_proveedor] = lambda: ProveedorTwilio(s)
    try:
        bloqueada(
            llamar(client, firmar_twilio, params(ctx, db, AccountSid="ACajeno")), "AGENTE_INVALIDO"
        )
        assert db.query(Llamada).count() == 0
        ok = llamar(client, firmar_twilio, params(ctx, db, AccountSid="ACreal", sid="CA0002"))
        assert "<Dial" in ok.text
    finally:
        app.dependency_overrides.pop(obtener_proveedor, None)
        reiniciar_proveedor()


def codigos_de(db):
    ll = db.query(Llamada).order_by(Llamada.id.desc()).first()
    return [m["codigo"] for m in ll.motivos_bloqueo], ll


def test_tipificacion_pendiente(client, firmar_twilio, ctx, db, esc, reloj):
    previa = Llamada(
        campana_cliente_id=ctx.cc.id,
        telefono_id=telefono_de(db, ctx.cc).id,
        usuario_id=ctx.agente.id,
        call_sid="CAprev",
        estado="completada",
        iniciada_en=reloj(),
    )
    db.add(previa)
    db.commit()
    r = llamar(client, firmar_twilio, params(ctx, db))
    bloqueada(r, "TIPIFICACION_PENDIENTE")
    assert codigos_de(db)[0] == ["TIPIFICACION_PENDIENTE"]


@pytest.mark.parametrize("estado", ["pausa", "desconectado", "tipificando", "en_llamada"])
def test_agente_no_disponible(client, firmar_twilio, ctx, db, esc, reloj, estado):
    esc.estado(ctx.agente, estado, reloj())
    llamar(client, firmar_twilio, params(ctx, db))
    codigos, ll = codigos_de(db)
    assert codigos == ["AGENTE_NO_DISPONIBLE"]
    assert ll.estado == "bloqueada"
    assert db.query(IntentoContacto).count() == 0
    assert db.get(EstadoAgente, ctx.agente.id).estado == estado
    aud = db.query(Auditoria).filter_by(accion="llamada.bloqueada").one()
    assert aud.detalle == {"llamada_id": ll.id, "codigos": ["AGENTE_NO_DISPONIBLE"]}


def test_campana_no_activa_y_no_asignada(client, firmar_twilio, ctx, db):
    ctx.campana.estado = "pausada"
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["CAMPANA_NO_ACTIVA"]
    ctx.campana.estado = "activa"
    db.query(__import__("app.modulos.campanas.modelos", fromlist=["x"]).CampanaAgente).delete()
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db, sid="CA0002"))
    assert codigos_de(db)[0] == ["CAMPANA_NO_ASIGNADA"]


def test_registro_no_reservado_y_orden_con_franja(client, firmar_twilio, ctx, db, reloj):
    ctx.cc.reservado_por = None
    ctx.cc.reservado_hasta = None
    db.commit()
    reloj.fijar(datetime(2026, 10, 25, 15, 0, tzinfo=UTC))  # domingo: también fuera de franja
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["REGISTRO_NO_RESERVADO"]  # el primero que falla decide


def test_reserva_de_otro_agente(client, firmar_twilio, ctx, db, crear_usuario, reloj):
    otro = crear_usuario("agente")
    ctx.cc.reservado_por = otro.id
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["REGISTRO_NO_RESERVADO"]


def test_reserva_caducada(client, firmar_twilio, ctx, db, reloj):
    reloj.avanzar(minutes=16)
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["REGISTRO_NO_RESERVADO"]


def test_intentos_agotados(client, firmar_twilio, ctx, db):
    ctx.cc.intentos = 3
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["INTENTOS_AGOTADOS"]


def test_excluido_para_el_tipo_pero_no_para_el_otro(client, firmar_twilio, ctx, db):
    db.add(Exclusion(numero_e164="+573001234567", motivo="manual", aplica_a="venta", creado_por=1))
    db.commit()
    assert "<Dial" in llamar(client, firmar_twilio, params(ctx, db)).text  # cobranza: permitida


def test_excluido_bloquea(client, firmar_twilio, ctx, db):
    db.add(Exclusion(numero_e164="+573001234567", motivo="rne", aplica_a="todas", creado_por=1))
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["EXCLUIDO"]


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (datetime(2026, 10, 25, 15, 0, tzinfo=UTC), ["DIA_SIN_FRANJA"]),
        (datetime(2026, 10, 23, 11, 59, tzinfo=UTC), ["FUERA_DE_FRANJA"]),  # vie 06:59
        (datetime(2026, 10, 24, 20, 0, tzinfo=UTC), ["FUERA_DE_FRANJA"]),  # sáb 15:00
        (datetime(2026, 10, 24, 5, 0, tzinfo=UTC), ["FUERA_DE_FRANJA"]),  # sáb 00:00
    ],
)
def test_horario(client, firmar_twilio, ctx, db, reloj, esc, momento, esperado):
    reloj.fijar(momento)
    esc.reservar(ctx.cc, ctx.agente, momento)
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == esperado


def test_festivo(client, firmar_twilio, ctx, db, reloj, esc):
    reloj.fijar(datetime(2026, 11, 2, 15, 0, tzinfo=UTC))  # lunes 2 nov 2026 (Todos los Santos)
    esc.reservar(ctx.cc, ctx.agente, reloj())
    llamar(client, firmar_twilio, params(ctx, db))
    assert codigos_de(db)[0] == ["FESTIVO"]


def test_frecuencia_devuelve_todos_los_motivos(client, firmar_twilio, ctx, db, reloj, esc):
    from app.modulos.cumplimiento.modelos import IntentoContacto as IC

    reloj.fijar(datetime(2026, 10, 24, 1, 0, tzinfo=UTC))  # vie 20:00 Bogotá (fuera de franja)
    esc.reservar(ctx.cc, ctx.agente, reloj())
    db.add(IC(cliente_id=ctx.cc.cliente_id, tipo_campana="cobranza", canal="voz",
              iniciado_por="empresa", momento=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
              contacto_directo=True))  # fmt: skip
    db.commit()
    llamar(client, firmar_twilio, params(ctx, db))
    codigos, ll = codigos_de(db)
    assert codigos == ["FUERA_DE_FRANJA", "FRECUENCIA_DIA"]
    assert db.query(IC).count() == 1  # el bloqueo no crea intento de contacto


def test_frecuencia_por_tipo_de_campana(client, firmar_twilio, ctx, db, esc, reloj):
    """Un contacto directo en una campaña de venta no bloquea la de cobranza (F12)."""
    from app.modulos.cumplimiento.modelos import IntentoContacto as IC

    db.add(IC(cliente_id=ctx.cc.cliente_id, tipo_campana="venta", canal="voz",
              iniciado_por="empresa", momento=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
              contacto_directo=True))  # fmt: skip
    db.commit()
    assert "<Dial" in llamar(client, firmar_twilio, params(ctx, db)).text
    # y uno en otra campaña de cobranza sí bloquea
    esc.estado(ctx.agente, "disponible", reloj())
    otra = esc.campana()
    esc.asignar(otra, ctx.agente)
    cc2 = esc.registro(otra)
    db.add(IC(cliente_id=cc2.cliente_id, tipo_campana="cobranza", canal="voz",
              iniciado_por="empresa", momento=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
              contacto_directo=True))  # fmt: skip
    db.commit()
    esc.reservar(cc2, ctx.agente, reloj())
    ctx2 = type("C", (), {"agente": ctx.agente, "cc": cc2})
    llamar(client, firmar_twilio, params(ctx2, db, sid="CA0009"))
    assert codigos_de(db)[0] == ["FRECUENCIA_DIA"]


def test_firma_invalida_403_sin_efectos(client, ctx, db, firmar_twilio):
    p = params(ctx, db)
    for kw in ({"data": p, "headers": {}},
               {"data": p, "headers": {"X-Twilio-Signature": "mala"}},
               firmar_twilio(RUTA, p, token="otro-token")):  # fmt: skip
        r = client.post(RUTA, **kw)
        assert r.status_code == 403
        assert r.json() == {
            "error": {"codigo": "FIRMA_INVALIDA", "mensaje": "Firma inválida.", "detalles": []}
        }
    firmada = firmar_twilio(RUTA, p)
    firmada["data"] = {**p, "telefono_id": "999"}  # parámetro alterado tras firmar
    assert client.post(RUTA, **firmada).status_code == 403
    assert db.query(Llamada).count() == 0


def test_firma_exige_url_exacta(client, ctx, db, firmar_twilio):
    p = params(ctx, db)
    kw = firmar_twilio(RUTA, p, consulta="a=1")  # firmada con query que no se envía
    assert client.post(RUTA, **kw).status_code == 403
    assert client.post(RUTA + "?a=1", **kw).status_code == 200
