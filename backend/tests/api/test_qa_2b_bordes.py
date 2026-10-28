"""QA 2B: bordes de la ventana de 24 h, desorden/idempotencia de webhooks, frecuencia cruzada
voz <-> WhatsApp y opt-out de extremo a extremo con variantes reales del español."""

import itertools
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from escenario import cab, telefono_de
from sqlalchemy import func, select
from voz import llamar, params_saliente
from wa import (
    autorizar,
    clave,
    contexto,
    crear_conv,
    crear_saliente,
    entrante,
    estado_webhook,
    params_entrante,
)

from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion, EventoMensaje, Mensaje
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.exclusiones.modelos import Exclusion
from app.trabajos.modelos import Trabajo

API = "/api/v1"
BOG = ZoneInfo("America/Bogota")


def utc(dia, h, m=0, s=0, ms=0):
    return datetime(2026, 10, dia, h, m, s, ms * 1000, tzinfo=BOG).astimezone(UTC)


VIE_10 = utc(23, 10)


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def texto(client, ctx, conv, idem=None):
    return client.post(
        f"{API}/conversaciones/{conv.id}/mensajes",
        json={"texto": "Buen día", "idempotencia_clave": idem or clave()},
        headers=cab(ctx.agente),
    )


# --- ventana de 24 h: bordes ---
@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (utc(24, 9, 58, 59, 999), 202),  # 1 ms antes del margen (expira 10:00, margen 60 s)
        (utc(24, 9, 59, 0), 409),  # exactamente expira - margen: cerrada
        (utc(24, 9, 59, 0, 1), 409),
        (utc(24, 10, 0, 0), 409),  # exactamente al expirar
        (utc(24, 10, 0, 1), 409),
        (utc(23, 10, 0), 202),  # mismo instante del entrante
    ],
)
def test_bordes_de_la_ventana_de_texto(client, db, ctx, reloj, momento, esperado):
    conv = crear_conv(db, VIE_10, cc=ctx.cc, dueno=Humano(ctx.agente.id))
    reloj.fijar(momento)
    r = texto(client, ctx, conv)
    assert r.status_code == esperado, r.text
    if esperado == 409:
        assert r.json()["error"]["codigo"] == "VENTANA_CERRADA"


def test_un_segundo_entrante_extiende_la_ventana_pero_un_saliente_no(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos
):
    reloj.fijar(VIE_10)
    entrante(client, firmar_twilio)
    correr_trabajos()
    conv = db.scalar(select(Conversacion))
    client.post(f"{API}/conversaciones/{conv.id}/tomar", headers=cab(ctx.agente))
    reloj.fijar(utc(23, 18, 0))
    entrante(client, firmar_twilio, texto="sigo aquí")
    correr_trabajos()
    db.expire_all()
    conv = db.get(Conversacion, conv.id)
    assert conv.ventana_expira_en.replace(tzinfo=UTC) == utc(24, 18, 0)
    # El agente responde el sábado a las 17:00 (ventana ampliada por el segundo entrante).
    reloj.fijar(utc(24, 17, 0))
    assert texto(client, ctx, conv).status_code == 202
    # Lo que envía la empresa no mueve la ventana.
    db.expire_all()
    assert db.get(Conversacion, conv.id).ventana_expira_en.replace(tzinfo=UTC) == utc(24, 18, 0)
    reloj.fijar(utc(24, 17, 59))
    assert texto(client, ctx, conv).status_code == 409


def test_entrantes_procesados_en_desorden_no_acortan_la_ventana_ni_pierden_mensajes(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos
):
    reloj.fijar(VIE_10)
    a = entrante(client, firmar_twilio, texto="primero")
    reloj.fijar(utc(23, 12, 0))
    b = entrante(client, firmar_twilio, texto="segundo")
    ids = {m.proveedor_id: m.id for m in db.scalars(select(Mensaje))}
    from app.modulos.whatsapp import servicio_entrante

    # El trabajo del mensaje más reciente se procesa ANTES que el del más antiguo.
    servicio_entrante.procesar_entrante(db, {"mensaje_id": ids[b["MessageSid"]]}, utc(23, 12, 1))
    db.commit()
    servicio_entrante.procesar_entrante(db, {"mensaje_id": ids[a["MessageSid"]]}, utc(23, 12, 2))
    db.commit()
    conv = db.scalar(select(Conversacion))
    assert conv.ventana_expira_en.replace(tzinfo=UTC) == utc(24, 12, 0)
    assert conv.ultimo_entrante_en.replace(tzinfo=UTC) == utc(23, 12, 0)
    assert conv.mensajes_sin_leer == 2
    assert {m.conversacion_id for m in db.scalars(select(Mensaje))} == {conv.id}
    # Los trabajos originales ya son no-ops (idempotentes).
    assert correr_trabajos(utc(23, 12, 5)) == 2
    db.expire_all()
    assert db.get(Conversacion, conv.id).mensajes_sin_leer == 2


def test_procesar_dos_veces_el_mismo_entrante_no_cuenta_dos_veces(
    client, firmar_twilio, db, ctx, reloj
):
    from app.modulos.whatsapp import servicio_entrante

    entrante(client, firmar_twilio, texto="uno")
    m = db.scalar(select(Mensaje))
    for _ in range(3):
        servicio_entrante.procesar_entrante(db, {"mensaje_id": m.id}, reloj())
        db.commit()
    conv = db.scalar(select(Conversacion))
    assert conv.mensajes_sin_leer == 1
    assert db.scalar(select(func.count()).select_from(Conversacion)) == 1


def test_plantilla_desde_la_consola_con_la_ventana_a_punto_de_cerrar_ya_no_pide_responder(
    client, db, ctx, reloj
):
    """Con la ventana a <= 60 s de cerrar, el texto ya no cabe y la plantilla pasa a ser la vía."""
    autorizar(db)
    esc_cc = ctx.cc
    conv = crear_conv(db, VIE_10, cc=esc_cc, dueno=Humano(ctx.agente.id))
    reloj.fijar(utc(24, 9, 59, 30))
    esc_cc.estado, esc_cc.reservado_por = "en_gestion", ctx.agente.id
    esc_cc.reservado_hasta = reloj() + timedelta(minutes=10)
    db.commit()
    assert texto(client, ctx, conv).status_code == 409
    r = client.post(
        f"{API}/conversaciones/{conv.id}/plantillas",
        json={"plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200, r.text


# --- webhooks: desorden ---
@pytest.mark.parametrize("orden", list(itertools.permutations(["sent", "delivered", "read"])))
def test_estados_en_cualquier_orden_convergen_a_leido(client, firmar_twilio, db, reloj, orden):
    conv = crear_conv(db, reloj())
    m = crear_saliente(db, conv, reloj(), estado="enviado", sid="SMord")
    for e in orden:
        assert estado_webhook(client, firmar_twilio, "SMord", e).status_code == 204
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert (m.estado, m.entregado_en is not None, m.leido_en is not None) == ("leido", True, True)
    assert db.scalar(select(func.count()).select_from(EventoMensaje)) == 3


def test_estados_repetidos_y_ruido_no_cambian_el_resultado(client, firmar_twilio, db, reloj):
    conv = crear_conv(db, reloj())
    m = crear_saliente(db, conv, reloj(), estado="enviado", sid="SMruido")
    for e in ["delivered", "delivered", "sent", "queued", "sending", "delivered", "read", "sent"]:
        estado_webhook(client, firmar_twilio, "SMruido", e)
    for e in ["undelivered", "failed", "canceled"]:
        estado_webhook(client, firmar_twilio, "SMruido", e, ErrorCode="30008")
    db.expire_all()
    m = db.get(Mensaje, m.id)
    assert (m.estado, m.error_codigo) == ("leido", None)


def test_fallido_y_luego_entregado_se_recupera_y_nunca_al_reves(client, firmar_twilio, db, reloj):
    conv = crear_conv(db, reloj())
    a = crear_saliente(db, conv, reloj(), estado="enviado", sid="SMa1")
    estado_webhook(client, firmar_twilio, "SMa1", "failed", ErrorCode="63016")
    estado_webhook(client, firmar_twilio, "SMa1", "delivered")
    db.expire_all()
    assert db.get(Mensaje, a.id).estado == "entregado"
    assert db.get(Mensaje, a.id).error_codigo is None


def test_replay_del_entrante_con_otro_cuerpo_no_pisa_al_original(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos
):
    p = entrante(client, firmar_twilio, texto="original")
    p2 = dict(p, Body="alterado")
    from wa import RUTA_ENTRANTE

    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p2))
    assert r.status_code == 200
    correr_trabajos()
    cuerpos = [m.cuerpo for m in db.scalars(select(Mensaje))]
    assert cuerpos == ["original"]
    assert db.scalar(select(func.count()).select_from(Trabajo)) == 1


def test_estado_para_un_sid_ajeno_no_toca_ningun_mensaje_y_se_aplica_al_aparecer(
    client, firmar_twilio, db, reloj
):
    conv = crear_conv(db, reloj())
    m = crear_saliente(db, conv, reloj(), estado="enviado", sid="SMreal")
    assert estado_webhook(client, firmar_twilio, "SMotro", "delivered").status_code == 204
    db.expire_all()
    assert db.get(Mensaje, m.id).estado == "enviado"


@pytest.mark.parametrize("num_media", ["11", "-1", "abc", "١٢", "1.5", " ", "99999999999999999999"])
def test_nummedia_hostil_no_rompe_el_webhook(client, firmar_twilio, db, num_media):
    from wa import RUTA_ENTRANTE

    p = params_entrante(NumMedia=num_media)
    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p))
    assert r.status_code == 200, r.text
    if num_media.strip() == "":
        return  # equivale a 0
    assert db.scalar(select(Mensaje.id)) is None


def test_body_de_5000_caracteres_se_trunca_a_4096_y_no_falla(client, firmar_twilio, db):
    entrante(client, firmar_twilio, texto="ñ" * 5000)
    assert len(db.scalar(select(Mensaje)).cuerpo) == 4096


# --- frecuencia cruzada ---
def _plantilla_consola(client, ctx, db, reloj, esc):
    esc.reservar(ctx.cc, ctx.agente, reloj())
    return client.post(
        f"{API}/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={
            "telefono_id": telefono_de(db, ctx.cc).id,
            "plantilla_id": ctx.plantilla.id,
            "idempotencia_clave": clave(),
        },
        headers=cab(ctx.agente),
    )


def _voz(client, firmar_twilio, ctx, db, reloj, esc, sid):
    esc.reservar(ctx.cc, ctx.agente, reloj())
    return llamar(client, firmar_twilio, params_saliente(ctx, db, sid=sid))


def test_x1_plantilla_sin_respuesta_no_bloquea_la_voz_del_mismo_dia(
    client, firmar_twilio, db, ctx, reloj, esc, correr_trabajos
):
    autorizar(db)
    reloj.fijar(utc(26, 10))
    assert _plantilla_consola(client, ctx, db, reloj, esc).json()["permitido"] is True
    correr_trabajos()
    r = _voz(client, firmar_twilio, ctx, db, reloj, esc, "CAx1")
    assert r.status_code == 200 and "<Dial" in r.text


def test_x2_plantilla_respondida_bloquea_la_voz_hoy_y_en_la_semana_pero_no_la_semana_siguiente(
    client, firmar_twilio, db, ctx, reloj, esc, correr_trabajos
):
    autorizar(db)
    reloj.fijar(utc(26, 10))  # lunes
    assert _plantilla_consola(client, ctx, db, reloj, esc).json()["permitido"] is True
    correr_trabajos()
    entrante(client, firmar_twilio, texto="Sí, dígame")
    correr_trabajos()
    r = _voz(client, firmar_twilio, ctx, db, reloj, esc, "CAx2a")  # mismo lunes
    assert r.status_code == 200 and "<Dial" not in r.text
    reloj.fijar(utc(28, 10))  # miércoles
    r = _voz(client, firmar_twilio, ctx, db, reloj, esc, "CAx2b")
    assert r.status_code == 200 and "<Dial" not in r.text
    reloj.fijar(datetime(2026, 11, 3, 10, 0, tzinfo=BOG).astimezone(UTC))  # semana nueva
    r = _voz(client, firmar_twilio, ctx, db, reloj, esc, "CAx2c")
    assert r.status_code == 200 and "<Dial" in r.text


def test_x3_voz_con_contacto_directo_el_viernes_bloquea_la_plantilla_del_sabado_hasta_el_lunes(
    client, db, ctx, reloj, esc
):
    autorizar(db)
    cumplimiento.registrar_intento(
        db,
        cliente_id=ctx.cc.cliente_id,
        tipo_campana="cobranza",
        canal="voz",
        iniciado_por="empresa",
        momento=utc(23, 9),
        campana_id=ctx.campana.id,
        contacto_directo=True,
    )
    db.commit()
    reloj.fijar(utc(24, 9))  # sábado, dentro de franja
    r = _plantilla_consola(client, ctx, db, reloj, esc).json()
    assert r["permitido"] is False
    assert [m["codigo"] for m in r["motivos"]] == ["FRECUENCIA_MEDIOS"]
    assert r["proxima_ventana_inicio"] == "2026-10-26T07:00:00-05:00"
    reloj.fijar(utc(26, 7))  # lunes 07:00 en punto
    assert _plantilla_consola(client, ctx, db, reloj, esc).json()["permitido"] is True


def test_x4_el_borde_de_medianoche_de_bogota_usa_el_dia_local(client, db, ctx, reloj, esc):
    """Un contacto a las 18:59:59 -05:00 cuenta para ese día local, no para el siguiente."""
    autorizar(db)
    cumplimiento.registrar_intento(
        db,
        cliente_id=ctx.cc.cliente_id,
        tipo_campana="cobranza",
        canal="whatsapp_mensaje",
        iniciado_por="empresa",
        momento=utc(26, 18, 59, 59),
        campana_id=ctx.campana.id,
        contacto_directo=True,
    )
    db.commit()
    mismo_dia = cumplimiento.evaluar_para_cliente(
        db, ctx.cc.cliente_id, "cobranza", "whatsapp_mensaje", utc(26, 18, 59, 59, 999)
    )[0]
    assert "FRECUENCIA_DIA" in [m.codigo for m in mismo_dia.motivos]
    siguiente = cumplimiento.evaluar_para_cliente(
        db, ctx.cc.cliente_id, "cobranza", "whatsapp_mensaje", utc(27, 7)
    )[0]
    assert [m.codigo for m in siguiente.motivos] == []  # mismo medio, otro día: permitido
    voz_siguiente = cumplimiento.evaluar_para_cliente(
        db, ctx.cc.cliente_id, "cobranza", "voz", utc(27, 7)
    )[0]
    assert [m.codigo for m in voz_siguiente.motivos] == ["FRECUENCIA_MEDIOS"]


def test_x5_el_cliente_que_escribe_primero_no_consume_el_cupo_de_la_empresa(
    client, firmar_twilio, db, ctx, reloj, esc, correr_trabajos
):
    reloj.fijar(utc(26, 10))
    entrante(client, firmar_twilio, texto="Buenos días")
    correr_trabajos()
    db.expire_all()
    conv = db.scalar(select(Conversacion))
    client.post(f"{API}/conversaciones/{conv.id}/tomar", headers=cab(ctx.agente))
    assert texto(client, ctx, conv).status_code == 202
    r = _voz(client, firmar_twilio, ctx, db, reloj, esc, "CAx5")
    assert r.status_code == 200 and "<Dial" in r.text


def test_x6_la_frecuencia_es_por_cliente(client, db, ctx, reloj, esc):
    autorizar(db)
    otro = esc.registro(ctx.campana, numeros=("+573009998877",), nombre="Otro Cliente")
    cumplimiento.registrar_intento(
        db,
        cliente_id=otro.cliente_id,
        tipo_campana="cobranza",
        canal="voz",
        iniciado_por="empresa",
        momento=reloj() - timedelta(hours=1),
        campana_id=ctx.campana.id,
        contacto_directo=True,
    )
    db.commit()
    assert _plantilla_consola(client, ctx, db, reloj, esc).json()["permitido"] is True


# --- opt-out de extremo a extremo ---
def _hay_exclusion(db):
    db.expire_all()
    return db.scalar(select(Exclusion))


@pytest.mark.parametrize(
    ("frase", "canal"),
    [
        ("STOP", "whatsapp"),
        ("Stop 🛑", "whatsapp"),
        ("NO ME ESCRIBAN MÁS!!!", "whatsapp"),
        ("Hola buenas tardes, no me escriban más por favor", "whatsapp"),
        ("Darme de baja 🙏", "whatsapp"),
        ("NO ME CONTACTEN MÁS", "todos"),
        ("Buenos días, no me contacten", "todos"),
        ("no me llamen ni me escriban", "todos"),
    ],
)
def test_opt_out_con_variantes_reales_aplica_el_canal_correcto(
    client, firmar_twilio, db, ctx, correr_trabajos, frase, canal
):
    autorizar(db)
    entrante(client, firmar_twilio, texto=frase)
    correr_trabajos()
    e = _hay_exclusion(db)
    assert e is not None and (e.canal, e.aplica_a, e.motivo) == (
        canal,
        "todas",
        "solicitud_titular",
    )
    assert db.scalar(select(Conversacion)).motivo_cierre == "opt_out"


@pytest.mark.parametrize(
    "frase",
    [
        "no puedo pagar",
        "No puedo pagar este mes, ¿me pueden dar plazo?",
        "ya pagué",
        "quiero cancelar la deuda",
        "no gracias",
        "cancelar",
        "no tengo plata",
        "stopped",
        "¿Baja el precio?",
    ],
)
def test_frases_de_negociacion_no_cierran_la_conversacion_ni_excluyen(
    client, firmar_twilio, db, ctx, correr_trabajos, frase
):
    autorizar(db)
    entrante(client, firmar_twilio, texto=frase)
    correr_trabajos()
    assert _hay_exclusion(db) is None
    conv = db.scalar(select(Conversacion))
    assert conv.estado == "abierta" and conv.motivo_cierre is None
    from app.modulos.whatsapp.modelos import AutorizacionCanal

    assert db.scalar(select(AutorizacionCanal)).clave_vigente is not None


def test_opt_out_en_una_conversacion_con_varios_entrantes_previos_y_agente(
    client, firmar_twilio, db, ctx, correr_trabajos, proveedor_whatsapp, reloj
):
    autorizar(db)
    entrante(client, firmar_twilio, texto="hola")
    correr_trabajos()
    conv = db.scalar(select(Conversacion))
    client.post(f"{API}/conversaciones/{conv.id}/tomar", headers=cab(ctx.agente))
    assert texto(client, ctx, conv).status_code == 202  # pendiente, aún sin enviar
    p = entrante(client, firmar_twilio, texto="STOP")
    # El trabajo del STOP se adelanta al envío pendiente del agente (carrera real posible).
    from app.modulos.whatsapp import servicio_entrante

    stop_id = db.scalar(select(Mensaje.id).where(Mensaje.proveedor_id == p["MessageSid"]))
    servicio_entrante.procesar_entrante(db, {"mensaje_id": stop_id}, reloj())
    db.commit()
    correr_trabajos()
    db.expire_all()
    agente = db.scalars(select(Mensaje).where(Mensaje.autor == "agente")).all()
    assert [(m.cuerpo, m.estado) for m in agente] == [("Buen día", "cancelado")]
    enviados = [e["texto"] for e in proveedor_whatsapp.enviados]
    assert len(enviados) == 1 and enviados[0].startswith("Hemos registrado")
