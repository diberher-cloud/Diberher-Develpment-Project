"""Eventos de tiempo real de 2B: reparto por rol y ausencia de texto o números (§4.14)."""

import json
import time

import pytest
from escenario import cab
from sqlalchemy import select
from test_websocket import recibir, url
from wa import (
    NUMERO,
    clave,
    contexto,
    crear_conv,
    crear_saliente,
    entrante,
    estado_webhook,
)

from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion
from app.tiempo_real import bus
from app.tiempo_real.conexiones import Conexion, debe_recibir

API = "/api/v1/conversaciones"


def ev(tipo, **datos):
    return {"tipo": tipo, "datos": datos}


# ---- Reparto (unitario) --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("rol", "evento", "esperado"),
    [
        ("administrador", ev("conversacion.mensaje", usuario_asignado_id=9), True),
        (
            "supervisor",
            ev("conversacion.estado", usuario_asignado_id=None, usuario_anterior_id=9),
            True,
        ),
        ("administrador", ev("trabajo.fallido", trabajo_id=1), True),
        ("supervisor", ev("atencion.cola", cola_id=1), True),
        ("agente", ev("conversacion.mensaje", usuario_asignado_id=5), True),
        ("agente", ev("conversacion.mensaje", usuario_asignado_id=6), False),
        ("agente", ev("conversacion.mensaje", usuario_asignado_id=None), False),
        ("agente", ev("conversacion.estado", usuario_asignado_id=6, usuario_anterior_id=5), True),
        ("agente", ev("conversacion.estado", usuario_asignado_id=5, usuario_anterior_id=6), True),
        ("agente", ev("conversacion.estado", usuario_asignado_id=6, usuario_anterior_id=7), False),
        (
            "agente",
            ev("conversacion.estado", usuario_asignado_id=None, usuario_anterior_id=None),
            False,
        ),
        ("agente", ev("atencion.cola", cola_id=1), True),
        ("agente", ev("trabajo.fallido", trabajo_id=1), False),
        ("agente", ev("consola.registro", campana_id=1), True),
        ("agente", ev("agente.estado", usuario_id=5), True),
        ("agente", ev("agente.estado", usuario_id=6), False),
        ("agente", ev("evento.desconocido"), False),
    ],
)
def test_debe_recibir(rol, evento, esperado):
    assert debe_recibir(Conexion(usuario_id=5, rol=rol), evento) is esperado


# ---- Extremo a extremo por WebSocket ----------------------------------------
def drenar(ws) -> list[dict]:
    """Eventos recibidos hasta el `pong` de un ping enviado tras una pausa breve."""
    time.sleep(0.3)  # deja que los eventos ya despachados lleguen al socket
    ws.send_text(json.dumps({"tipo": "ping"}))
    eventos = []
    while True:
        e = ws.receive_json()
        if e["tipo"] == "pong":
            return eventos
        eventos.append(e)


def tipos(eventos):
    return [e["tipo"] for e in eventos]


def test_el_agente_solo_recibe_lo_suyo_y_el_supervisor_todo(
    client, db, esc, crear_usuario, reloj, correr_trabajos, firmar_twilio
):
    ctx = contexto(esc, crear_usuario, reloj, db)
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    sup = crear_usuario("supervisor")
    mia = crear_conv(db, reloj(), cc=ctx.cc, con_cola=True)
    ajena_cc = esc.registro(ctx.campana, numeros=("+573115550001",))
    ajena = crear_conv(db, reloj(), numero="+573115550001", cc=ajena_cc, dueno=Humano(otro.id))
    with (
        client.websocket_connect(url(ctx.agente, client)) as ws_a,
        client.websocket_connect(url(sup, client)) as ws_s,
    ):
        recibir(ws_a, "conexion.lista")
        recibir(ws_s, "conexion.lista")
        # El agente toma la suya: él y el supervisor reciben la cola y el cambio de estado.
        assert client.post(f"{API}/{mia.id}/tomar", headers=cab(ctx.agente)).status_code == 200
        for ws in (ws_a, ws_s):
            eventos = drenar(ws)
            assert sorted(tipos(eventos)) == ["atencion.cola", "conversacion.estado"]
            estado = next(e for e in eventos if e["tipo"] == "conversacion.estado")["datos"]
            assert (
                estado["usuario_asignado_id"] == ctx.agente.id
                and estado["conversacion_id"] == mia.id
            )
        # Un estado de entrega en la conversación AJENA: el supervisor lo ve; el agente no.
        m = crear_saliente(db, ajena, reloj(), estado="enviado", sid="SMajeno")
        assert estado_webhook(client, firmar_twilio, "SMajeno", "delivered").status_code == 204
        assert drenar(ws_a) == []
        (e,) = drenar(ws_s)
        assert (e["tipo"], e["datos"]["conversacion_id"], e["datos"]["mensaje_id"]) == (
            "conversacion.mensaje", ajena.id, m.id,
        )  # fmt: skip
        assert e["datos"]["accion"] == "estado" and e["datos"]["estado"] == "entregado"
        # En la suya, el agente y el supervisor lo reciben.
        propio = crear_saliente(db, mia, reloj(), estado="enviado", sid="SMmio")
        estado_webhook(client, firmar_twilio, "SMmio", "read")
        for ws in (ws_a, ws_s):
            (e,) = drenar(ws)
            assert e["datos"]["mensaje_id"] == propio.id and e["datos"]["estado"] == "leido"
        # Reasignación: el agente anterior recibe el evento gracias a `usuario_anterior_id`.
        r = client.post(f"{API}/{mia.id}/asignar", json={"usuario_id": otro.id}, headers=cab(sup))
        assert r.status_code == 200
        e = next(x for x in drenar(ws_a) if x["tipo"] == "conversacion.estado")
        assert (e["datos"]["usuario_anterior_id"], e["datos"]["usuario_asignado_id"]) == (
            ctx.agente.id, otro.id,
        )  # fmt: skip


def test_trabajo_fallido_solo_llega_a_supervisores(
    client, db, crear_usuario, correr_trabajos, reloj
):
    from app.trabajos import cola, registro

    agente = crear_usuario("agente")
    sup = crear_usuario("supervisor")
    registro.cargar_manejadores()

    def malo(*_):
        raise registro.ErrorTrabajo("MALO", transitorio=False)

    registro.MANEJADORES["test.malo"] = malo
    try:
        with (
            client.websocket_connect(url(agente, client)) as ws_a,
            client.websocket_connect(url(sup, client)) as ws_s,
        ):
            recibir(ws_a, "conexion.lista")
            recibir(ws_s, "conexion.lista")
            cola.encolar(db, "test.malo", {}, ahora=reloj())
            db.commit()
            correr_trabajos()
            (e,) = drenar(ws_s)
            assert e["tipo"] == "trabajo.fallido"
            assert e["datos"]["codigo"] == "MALO" and e["datos"]["tipo"] == "test.malo"
            assert drenar(ws_a) == []
    finally:
        registro.MANEJADORES.pop("test.malo", None)


# ---- Ningún evento lleva texto ni números -----------------------------------
def test_ningun_evento_contiene_texto_de_mensajes_ni_numeros(
    client, db, esc, crear_usuario, reloj, correr_trabajos, firmar_twilio
):
    ctx = contexto(esc, crear_usuario, reloj, db)
    from wa import autorizar

    autorizar(db)
    recibidos: list[dict] = []
    anterior = bus._bus
    bus.obtener_bus().suscribir(recibidos.append)  # type: ignore[union-attr]
    try:
        entrante(client, firmar_twilio, texto="SECRETO-ENTRANTE-123", ProfileName="Nombre Secreto")
        correr_trabajos()
        conv = db.scalar(select(Conversacion))
        client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
        r = client.post(
            f"{API}/{conv.id}/mensajes",
            json={"texto": "RESPUESTA-CONFIDENCIAL-456", "idempotencia_clave": clave()},
            headers=cab(ctx.agente),
        )
        correr_trabajos()
        client.post(f"{API}/{conv.id}/liberar", headers=cab(ctx.agente))
        client.post(
            f"{API}/{conv.id}/opt-out", json={"alcance": "whatsapp"}, headers=cab(ctx.agente)
        )
        client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
        client.post(
            f"{API}/{conv.id}/cerrar",
            json={"tipificacion": {"resultado": "contactado", "observacion": "OBS-SECRETA-789"}},
            headers=cab(ctx.agente),
        )
        assert r.status_code == 202
    finally:
        bus._bus = anterior
    tipos = {e["tipo"] for e in recibidos}
    assert {"conversacion.estado", "conversacion.mensaje", "atencion.cola"} <= tipos
    volcado = json.dumps(recibidos, ensure_ascii=False)
    for prohibido in (
        "+57",
        NUMERO,
        "3001234567",
        "SECRETO",
        "CONFIDENCIAL",
        "OBS-",
        "Nombre",
        "tipo_contenido",
    ):
        assert prohibido not in volcado, prohibido
