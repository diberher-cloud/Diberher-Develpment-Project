"""Envío de texto libre en la ventana de 24 h y trabajo `whatsapp.enviar_mensaje` (V1-V8)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, clave, contexto, crear_conv

from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto, PoliticaCumplimiento
from app.modulos.exclusiones.modelos import Exclusion
from app.trabajos.modelos import Trabajo

API = "/api/v1/conversaciones"


BOG = ZoneInfo("America/Bogota")


def utc(dia, h, m=0, s=0):
    """Hora de Bogotá (UTC-5) del 2026-10-<dia>."""
    return datetime(2026, 10, dia, h, m, s, tzinfo=BOG).astimezone(UTC)


VIE_10 = utc(23, 10)


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def conv_propia(db, ctx, ahora, **kw):
    return crear_conv(db, ahora, cc=ctx.cc, dueno=Humano(ctx.agente.id), **kw)


def enviar(client, ctx, conv, texto="Buenos días, le ayudo.", idem=None, usuario=None):
    return client.post(
        f"{API}/{conv.id}/mensajes",
        json={"texto": texto, "idempotencia_clave": idem or clave()},
        headers=cab(usuario or ctx.agente),
    )


def politica_responder(db, valor: bool, tipo="cobranza"):
    fila = db.scalar(select(PoliticaCumplimiento).where(PoliticaCumplimiento.tipo_campana == tipo))
    cfg = dict(fila.configuracion)
    cfg["entrantes"] = {**cfg["entrantes"], "responder_fuera_de_franja": valor}
    fila.configuracion = cfg
    db.commit()


def test_v1_dentro_de_la_ventana_202_y_el_worker_lo_envia(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    conv = conv_propia(db, ctx, VIE_10)
    reloj.fijar(utc(24, 9, 58))  # margen de 60 s: aún cabe
    r = enviar(client, ctx, conv, "Hola ñandú")
    assert r.status_code == 202, r.text
    m = r.json()
    assert (m["estado"], m["autor"], m["tipo"], m["cuerpo"]) == (
        "pendiente",
        "agente",
        "texto",
        "Hola ñandú",
    )
    assert m["usuario"]["id"] == ctx.agente.id and m["direccion"] == "saliente"
    t = db.scalar(select(Trabajo))
    assert (t.tipo, t.payload, t.clave_unica) == (
        "whatsapp.enviar_mensaje", {"mensaje_id": m["id"]}, f"enviar:{m['id']}",
    )  # fmt: skip
    assert correr_trabajos() == 1
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (
        fila.estado == "enviado"
        and fila.proveedor_id.startswith("SMfalso")
        and fila.enviado_en == reloj()
    )
    assert proveedor_whatsapp.enviados == [
        {"tipo": "texto", "destino": NUMERO, "texto": "Hola ñandú"}
    ]
    # No crea intentos de contacto ni consume frecuencia (ADR-0012 §3).
    assert db.scalar(select(IntentoContacto.id)) is None
    assert db.get(Conversacion, conv.id).ultimo_mensaje_en == reloj()


def test_v2_a_30_segundos_de_expirar_409_ventana_cerrada(client, db, ctx, reloj):
    conv = conv_propia(db, ctx, VIE_10)
    reloj.fijar(utc(24, 9, 59, 30))
    r = enviar(client, ctx, conv)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "VENTANA_CERRADA"
    reloj.fijar(utc(24, 10, 0))
    assert enviar(client, ctx, conv).status_code == 409
    assert db.scalar(select(Mensaje.id)) is None


def test_v3_conversacion_abierta_por_plantilla_sin_respuesta(client, db, ctx, reloj):
    conv = conv_propia(db, ctx, VIE_10, iniciada_por="empresa", ventana=False)
    assert conv.ventana_expira_en is None
    r = enviar(client, ctx, conv)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "VENTANA_CERRADA"


def test_v4_fuera_de_franja_se_retiene_hasta_la_proxima_franja_y_avisa_una_sola_vez(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    politica_responder(db, False)
    conv = conv_propia(db, ctx, utc(23, 19, 20))
    reloj.fijar(utc(23, 19, 30))
    r1 = enviar(client, ctx, conv, "primera")
    r2 = enviar(client, ctx, conv, "segunda")
    assert r1.status_code == r2.status_code == 202
    for r in (r1, r2):
        assert r.json()["estado"] == "retenido"
        assert r.json()["programado_para"] == "2026-10-24T13:00:00Z"  # sáb 08:00 -05:00
    # V6: el aviso de fuera de franja sale una sola vez; las respuestas retenidas no.
    correr_trabajos()
    textos = [e["texto"] for e in proveedor_whatsapp.enviados]
    assert len(textos) == 1 and "horario de atención" in textos[0]
    db.expire_all()
    assert db.get(Conversacion, conv.id).aviso_fuera_franja_enviado_en == reloj()
    assert correr_trabajos(utc(24, 7, 59)) == 0  # el trabajo no se ejecuta antes
    reloj.fijar(utc(24, 8, 0))
    assert correr_trabajos() == 2
    assert [e["texto"] for e in proveedor_whatsapp.enviados][1:] == ["primera", "segunda"]
    db.expire_all()
    assert {m.estado for m in db.scalars(select(Mensaje).where(Mensaje.autor == "agente"))} == {
        "enviado"
    }


def test_v5_la_proxima_franja_cae_despues_de_la_ventana_409(client, db, ctx, reloj):
    politica_responder(db, False)
    conv = conv_propia(db, ctx, utc(24, 15, 20))  # sáb 15:20; la ventana cierra dom 15:20
    reloj.fijar(utc(24, 15, 30))
    r = enviar(client, ctx, conv)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "RESPUESTA_FUERA_DE_FRANJA"
    detalle = r.json()["error"]["detalles"][0]
    assert detalle["campo"] == "texto" and "2026-10-26T07:00:00-05:00" in detalle["mensaje"]
    assert "Use una plantilla" in detalle["mensaje"]
    assert db.scalar(select(Mensaje.id)) is None


def test_v7_responder_fuera_de_franja_permitido_domingo_22h(client, db, ctx, reloj):
    conv = conv_propia(db, ctx, utc(25, 21, 30))
    reloj.fijar(utc(25, 22, 0))
    r = enviar(client, ctx, conv)
    assert r.status_code == 202 and r.json()["estado"] == "pendiente"


def test_v8_sin_campana_manda_la_politica_mas_restrictiva(client, db, ctx, reloj, crear_usuario):
    politica_responder(db, True, "venta")
    politica_responder(db, False, "cobranza")
    sup = crear_usuario("supervisor")
    conv = crear_conv(db, utc(23, 19, 20), numero="+573119998877", dueno=Humano(sup.id))
    reloj.fijar(utc(23, 19, 30))
    r = client.post(
        f"{API}/{conv.id}/mensajes",
        json={"texto": "hola", "idempotencia_clave": clave()},
        headers=cab(sup),
    )
    assert r.status_code == 202 and r.json()["estado"] == "retenido"


def test_validaciones_en_orden(client, db, ctx, reloj, crear_usuario):
    conv = conv_propia(db, ctx, VIE_10)
    assert enviar(client, ctx, type("C", (), {"id": 999})()).status_code == 404
    ajeno = crear_usuario("agente")
    r = enviar(client, ctx, conv, usuario=ajeno)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"
    for texto in ("", "   ", "x" * 4097):
        r = enviar(client, ctx, conv, texto)
        assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "texto"
    r = client.post(f"{API}/{conv.id}/mensajes", json={"texto": "hola"}, headers=cab(ctx.agente))
    assert r.status_code == 422
    r = client.post(
        f"{API}/{conv.id}/mensajes",
        json={"texto": "hola", "idempotencia_clave": "no-es-uuid"},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 422
    assert enviar(client, ctx, conv, "x" * 4096).status_code == 202  # el máximo exacto
    # El supervisor también debe ser el dueño para escribir.
    sup = crear_usuario("supervisor")
    assert enviar(client, ctx, conv, usuario=sup).status_code == 403


def test_conversacion_cerrada_409(client, db, ctx, reloj):
    from app.modulos.conversaciones import servicio

    conv = conv_propia(db, ctx, VIE_10)
    servicio.cerrar(db, conv, "agente", None, reloj())
    db.commit()
    r = enviar(client, ctx, conv)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_CERRADA"


def test_e12_idempotencia_misma_clave_un_solo_mensaje(client, db, ctx, reloj, crear_usuario):
    conv = conv_propia(db, ctx, VIE_10)
    k = clave()
    r1 = enviar(client, ctx, conv, "uno", idem=k)
    r2 = enviar(client, ctx, conv, "uno", idem=k)
    assert (r1.status_code, r2.status_code) == (202, 200)
    assert r1.json()["id"] == r2.json()["id"]
    assert (
        len(db.scalars(select(Mensaje)).all()) == 1 and len(db.scalars(select(Trabajo)).all()) == 1
    )
    # Otro usuario con la misma clave: conflicto.
    otro = crear_usuario("supervisor")
    r3 = client.post(
        f"{API}/{conv.id}/mensajes",
        json={"texto": "uno", "idempotencia_clave": k},
        headers=cab(otro),
    )
    assert r3.status_code in (403, 409)
    # Otra conversación con la misma clave: 409 IDEMPOTENCIA_CONFLICTO.
    otra = crear_conv(db, VIE_10, numero="+573115550001", cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r4 = enviar(client, ctx, otra, "uno", idem=k)
    assert r4.status_code == 409 and r4.json()["error"]["codigo"] == "IDEMPOTENCIA_CONFLICTO"


def test_cliente_opt_out_posterior_al_ultimo_mensaje_409(client, db, ctx, reloj, admin):
    conv = conv_propia(db, ctx, VIE_10)
    db.add(
        Exclusion(
            numero_e164=NUMERO, motivo="solicitud_titular", aplica_a="todas", canal="whatsapp",
            creado_por=admin.id, creado_en=VIE_10 + timedelta(minutes=1),
        )
    )  # fmt: skip
    db.commit()
    r = enviar(client, ctx, conv)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CLIENTE_OPT_OUT"


def test_exclusion_anterior_al_ultimo_mensaje_no_impide_responder(client, db, ctx, reloj, admin):
    """Si el cliente escribió DESPUÉS del opt-out, puede recibir respuesta (S-B3)."""
    conv = conv_propia(db, ctx, VIE_10)
    db.add(
        Exclusion(
            numero_e164=NUMERO, motivo="solicitud_titular", aplica_a="todas", canal="whatsapp",
            creado_por=admin.id, creado_en=VIE_10 - timedelta(days=2),
        )
    )  # fmt: skip
    db.commit()
    assert enviar(client, ctx, conv).status_code == 202


def test_exclusion_rne_alerta_pero_no_bloquea_la_respuesta(client, db, ctx, reloj, admin):
    conv = conv_propia(db, ctx, VIE_10)
    db.add(Exclusion(numero_e164=NUMERO, motivo="rne", aplica_a="todas", creado_por=admin.id))
    db.commit()
    assert enviar(client, ctx, conv).status_code == 202
    detalle = client.get(f"{API}/{conv.id}", headers=cab(ctx.agente)).json()
    assert "EXCLUIDO_WHATSAPP" in [a["codigo"] for a in detalle["alertas"]]


# ---- Trabajo: revalidaciones y errores -----------------------------------------------------------
def test_el_trabajo_falla_si_la_ventana_se_cerro_antes_de_enviar(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    conv = conv_propia(db, ctx, VIE_10)
    reloj.fijar(utc(24, 9, 50))
    m = enviar(client, ctx, conv).json()
    assert correr_trabajos(utc(24, 9, 59, 30)) == 1
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo) == ("fallido", "VENTANA_CERRADA")
    assert proveedor_whatsapp.enviados == []


def test_el_trabajo_falla_si_hubo_opt_out_despues_de_encolar(
    client, db, ctx, reloj, correr_trabajos, admin
):
    conv = conv_propia(db, ctx, VIE_10)
    m = enviar(client, ctx, conv).json()
    db.add(
        Exclusion(
            numero_e164=NUMERO, motivo="solicitud_titular", aplica_a="todas", canal="todos",
            creado_por=admin.id, creado_en=reloj() + timedelta(seconds=1),
        )
    )  # fmt: skip
    db.commit()
    correr_trabajos(reloj() + timedelta(seconds=5))
    db.expire_all()
    assert (db.get(Mensaje, m["id"]).estado, db.get(Mensaje, m["id"]).error_codigo) == (
        "fallido",
        "CLIENTE_OPT_OUT",
    )


def test_el_trabajo_cancela_si_la_conversacion_se_cerro(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    from app.modulos.conversaciones import servicio

    conv = conv_propia(db, ctx, VIE_10)
    m = enviar(client, ctx, conv).json()
    # Cierre que no pasa por `servicio.cerrar` (no cancela): el trabajo lo detecta.
    c = db.get(Conversacion, conv.id)
    c.estado, c.clave_abierta, c.cerrada_en, c.motivo_cierre = "cerrada", None, reloj(), "agente"
    db.commit()
    assert servicio  # módulo importado: la ruta normal cancela los pendientes
    correr_trabajos()
    db.expire_all()
    assert db.get(Mensaje, m["id"]).estado == "cancelado"
    assert proveedor_whatsapp.enviados == []


def test_e10_error_permanente_63003_sin_reintentos(client, db, ctx, reloj, correr_trabajos, esc):
    cc = esc.registro(ctx.campana, numeros=("+573110000000",))
    conv = crear_conv(db, VIE_10, numero="+573110000000", cc=cc, dueno=Humano(ctx.agente.id))
    m = enviar(client, ctx, conv).json()
    assert correr_trabajos() == 1
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo, fila.proveedor_id) == ("fallido", "63003", None)
    t = db.scalar(select(Trabajo))
    assert (t.estado, t.intentos) == ("completado", 1)
    assert correr_trabajos(reloj() + timedelta(days=1)) == 0
    detalle = client.get(f"{API}/{conv.id}/mensajes", headers=cab(ctx.agente)).json()["items"][0]
    assert detalle["error"] == {
        "codigo": "63003",
        "mensaje": "El número no está disponible en WhatsApp.",
    }


def test_e10_error_transitorio_429_reintenta_con_backoff_y_falla_tras_5(
    client, db, ctx, reloj, correr_trabajos, esc
):
    cc = esc.registro(ctx.campana, numeros=("+573119999999",))
    conv = crear_conv(db, VIE_10, numero="+573119999999", cc=cc, dueno=Humano(ctx.agente.id))
    m = enviar(client, ctx, conv).json()
    ahora = reloj()
    esperas = [5, 10, 20, 40]
    for espera in esperas:
        assert correr_trabajos(ahora) == 1
        db.expire_all()
        t = db.scalar(select(Trabajo))
        assert t.estado == "pendiente" and t.disponible_desde == ahora + timedelta(seconds=espera)
        assert db.get(Mensaje, m["id"]).estado == "pendiente"
        ahora = t.disponible_desde
    assert correr_trabajos(ahora) == 1
    db.expire_all()
    t = db.scalar(select(Trabajo))
    assert (t.estado, t.intentos, t.ultimo_error) == ("fallido", 5, "ErrorTrabajo:429")
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo) == ("fallido", "429")


def test_e11_mensaje_en_enviando_se_marca_envio_incierto_sin_llamar_al_proveedor(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    conv = conv_propia(db, ctx, VIE_10)
    m = enviar(client, ctx, conv).json()
    fila = db.get(Mensaje, m["id"])
    fila.estado = "enviando"  # un intento anterior murió a mitad
    db.commit()
    correr_trabajos()
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo) == ("fallido", "ENVIO_INCIERTO")
    assert proveedor_whatsapp.enviados == []
    assert (
        "revise antes de reenviar"
        in client.get(f"{API}/{conv.id}/mensajes", headers=cab(ctx.agente)).json()["items"][0][
            "error"
        ]["mensaje"]
    )
