"""Bandeja: tomar, asignar, liberar, historial, vinculación y cierre por inactividad (C1-C14)."""

from datetime import timedelta

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, contexto, crear_conv, crear_saliente, entrante

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto

API = "/api/v1/conversaciones"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def conv_de(db, ctx, reloj, numero=NUMERO, **kw):
    return crear_conv(db, reloj(), numero=numero, cc=ctx.cc, con_cola=True, **kw)


def test_c1_tomar_sin_asignar_deja_al_agente_como_dueno(client, db, ctx, reloj):
    conv = conv_de(db, ctx, reloj)
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["atendida_por"], cuerpo["usuario_asignado"]["id"]) == ("humano", ctx.agente.id)
    assert cuerpo["numero_e164"] is None and cuerpo["numero_mascara"] == "+57300****567"
    assert cuerpo["puede_responder"] is True and cuerpo["motivo_cola"] == "entrante"
    db.expire_all()
    fila = db.scalar(select(ColaAtencion))
    assert (fila.estado, fila.asignada_a, fila.clave_activa) == (
        "asignada",
        ctx.agente.id,
        str(conv.id),
    )
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "conversacion.dueno"))
    assert aud.detalle == {
        "conversacion_id": conv.id, "de": "sin_asignar", "a": "humano", "motivo": None,
    }  # fmt: skip
    assert db.scalar(select(Auditoria).where(Auditoria.accion == "conversacion.tomar"))


def test_tomar_una_ya_mia_es_idempotente(client, db, ctx, reloj):
    conv = conv_de(db, ctx, reloj)
    for _ in range(2):
        assert client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente)).status_code == 200
    assert (
        len(db.scalars(select(Auditoria).where(Auditoria.accion == "conversacion.tomar")).all())
        == 1
    )


def test_c2_tomar_una_ajena_409(client, db, ctx, reloj, crear_usuario, esc):
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    conv = conv_de(db, ctx, reloj)
    assert client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente)).status_code == 200
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(otro))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_ASIGNADA"


def test_c3_agente_sin_la_campana_403(client, db, ctx, reloj, crear_usuario, esc):
    ajeno = crear_usuario("agente")
    esc.estado(ajeno, "disponible", reloj())
    conv = conv_de(db, ctx, reloj)
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(ajeno))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"


def test_tomar_conversacion_sin_campana_prohibido_para_el_agente(client, db, ctx, reloj):
    conv = crear_conv(db, reloj(), numero="+573119998877", con_cola=True, motivo_cola="sin_campana")
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"


@pytest.mark.parametrize("estado", ["pausa", "desconectado", "tipificando", "en_llamada"])
def test_c4_agente_no_disponible_409(client, db, ctx, reloj, esc, estado):
    kw = {"motivo_pausa": "descanso"} if estado == "pausa" else {}
    esc.estado(ctx.agente, estado, reloj(), **kw)
    conv = conv_de(db, ctx, reloj)
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "AGENTE_NO_DISPONIBLE"


def test_c5_capacidad_maxima(client, db, ctx, reloj, esc):
    ids = []
    for i in range(6):
        numero = f"+57311000000{i}"
        esc_cc = esc.registro(ctx.campana, numeros=(numero,))
        ids.append(crear_conv(db, reloj(), numero=numero, cc=esc_cc, con_cola=True).id)
    for cid in ids[:5]:
        assert client.post(f"{API}/{cid}/tomar", headers=cab(ctx.agente)).status_code == 200
    r = client.post(f"{API}/{ids[5]}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAPACIDAD_MAXIMA"
    assert (
        client.post("/api/v1/atencion/tomar-siguiente", headers=cab(ctx.agente)).status_code == 409
    )


def test_tomar_cerrada_409(client, db, ctx, reloj):
    from app.modulos.conversaciones import servicio

    conv = conv_de(db, ctx, reloj)
    servicio.cerrar(db, conv, "agente", None, reloj())
    db.commit()
    r = client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_CERRADA"


def test_conversacion_inexistente_404(client, ctx):
    assert client.post(f"{API}/999/tomar", headers=cab(ctx.agente)).status_code == 404
    assert client.get(f"{API}/999", headers=cab(ctx.agente)).status_code == 404


def test_c7_asignar_por_supervisor(client, db, ctx, reloj, crear_usuario, h_supervisor, esc):
    ajeno = crear_usuario("agente")
    conv = conv_de(db, ctx, reloj)
    r = client.post(f"{API}/{conv.id}/asignar", json={"usuario_id": ajeno.id}, headers=h_supervisor)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"] == [
        {"campo": "usuario_id", "mensaje": "El agente no está asignado a la campaña."}
    ]
    r = client.post(
        f"{API}/{conv.id}/asignar", json={"usuario_id": ctx.agente.id}, headers=h_supervisor
    )
    assert r.status_code == 200 and r.json()["usuario_asignado"]["id"] == ctx.agente.id
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "conversacion.asignar"))
    assert aud.detalle == {"conversacion_id": conv.id, "usuario_id": ctx.agente.id}
    # El agente no puede asignar; el destino debe estar activo.
    assert (
        client.post(
            f"{API}/{conv.id}/asignar", json={"usuario_id": 1}, headers=cab(ctx.agente)
        ).status_code
        == 403
    )
    inactivo = crear_usuario("agente", activo=False)
    r = client.post(
        f"{API}/{conv.id}/asignar", json={"usuario_id": inactivo.id}, headers=h_supervisor
    )
    assert r.status_code == 422


def test_asignar_sin_campana_solo_a_supervisor_o_admin(
    client, db, ctx, reloj, crear_usuario, h_supervisor
):
    sup = crear_usuario("supervisor")
    conv = crear_conv(db, reloj(), numero="+573119998877", con_cola=True, motivo_cola="sin_campana")
    r = client.post(
        f"{API}/{conv.id}/asignar", json={"usuario_id": ctx.agente.id}, headers=h_supervisor
    )
    assert r.status_code == 422
    assert "Solo un supervisor" in r.json()["error"]["detalles"][0]["mensaje"]
    r = client.post(f"{API}/{conv.id}/asignar", json={"usuario_id": sup.id}, headers=h_supervisor)
    assert r.status_code == 200 and r.json()["atendida_por"] == "humano"


def test_reasignacion_conserva_un_solo_registro_de_cola(
    client, db, ctx, reloj, esc, crear_usuario, h_supervisor
):
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    r = client.post(f"{API}/{conv.id}/asignar", json={"usuario_id": otro.id}, headers=h_supervisor)
    assert r.status_code == 200 and r.json()["usuario_asignado"]["id"] == otro.id
    db.expire_all()
    (fila,) = db.scalars(select(ColaAtencion).where(ColaAtencion.estado == "asignada")).all()
    assert fila.asignada_a == otro.id


def test_c8_liberar_devuelve_a_la_cola_con_motivo_liberada(client, db, ctx, reloj, crear_usuario):
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    ajeno = crear_usuario("agente")
    assert client.post(f"{API}/{conv.id}/liberar", headers=cab(ajeno)).status_code == 403
    r = client.post(f"{API}/{conv.id}/liberar", headers=cab(ctx.agente))
    assert r.status_code == 200
    assert (r.json()["atendida_por"], r.json()["usuario_asignado"]) == ("sin_asignar", None)
    db.expire_all()
    pendientes = db.scalars(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")).all()
    assert [(f.motivo, f.prioridad) for f in pendientes] == [("liberada", 2)]
    cerradas = db.scalars(select(ColaAtencion).where(ColaAtencion.estado == "cerrada")).all()
    assert len(cerradas) == 1 and cerradas[0].clave_activa is None


def test_supervisor_puede_liberar_cualquiera(client, db, ctx, reloj, h_supervisor):
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert client.post(f"{API}/{conv.id}/liberar", headers=h_supervisor).status_code == 200
    # Liberar una sin dueño no hace nada (idempotente).
    r = client.post(f"{API}/{conv.id}/liberar", headers=h_supervisor)
    assert r.status_code == 200 and r.json()["atendida_por"] == "sin_asignar"
    db.expire_all()
    assert (
        len(db.scalars(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")).all()) == 1
    )


def test_c9_desconectado_manual_devuelve_las_conversaciones_a_la_cola(client, db, ctx, reloj):
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    r = client.put(
        "/api/v1/consola/estado",
        json={"estado": "pausa", "motivo_pausa": "almuerzo"},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Conversacion, conv.id).atendida_por == "humano"  # la pausa no las libera
    r = client.put(
        "/api/v1/consola/estado", json={"estado": "desconectado"}, headers=cab(ctx.agente)
    )
    assert r.status_code == 200
    db.expire_all()
    c = db.get(Conversacion, conv.id)
    assert (c.atendida_por, c.usuario_asignado_id) == ("sin_asignar", None)
    (fila,) = db.scalars(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")).all()
    assert fila.motivo == "agente_desconectado"


def test_c9_desconectado_por_inactividad(db, ctx, reloj, client):
    from app.modulos.consola import estado as estado_agente

    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert estado_agente.desconectar_por_inactividad(db, ctx.agente.id, reloj()) is True
    db.expire_all()
    assert db.get(Conversacion, conv.id).atendida_por == "sin_asignar"
    fila = db.scalar(select(ColaAtencion).where(ColaAtencion.estado == "pendiente"))
    assert fila.motivo == "agente_desconectado"


def test_c10_vincular_registro_candidato(client, db, ctx, reloj, h_supervisor, esc):
    # Dos registros del mismo número: la conversación queda sin registro y la vincula el supervisor.
    otra = esc.campana(whatsapp_habilitado=True, tipo="venta")
    cc2 = esc.registro(otra)
    conv = crear_conv(db, reloj(), con_cola=True, motivo_cola="sin_campana")
    r = client.get(f"{API}/{conv.id}/registros-candidatos", headers=h_supervisor)
    assert {x["campana_cliente_id"] for x in r.json()} == {ctx.cc.id, cc2.id}
    r = client.put(
        f"{API}/{conv.id}/registro", json={"campana_cliente_id": ctx.cc.id}, headers=h_supervisor
    )
    assert r.status_code == 200, r.text
    assert r.json()["campana_cliente_id"] == ctx.cc.id and r.json()["motivo_cola"] == "entrante"
    db.expire_all()
    c = db.get(Conversacion, conv.id)
    assert (c.campana_id, c.cliente_id, c.telefono_id) == (
        ctx.campana.id,
        ctx.cc.cliente_id,
        c.telefono_id,
    )
    assert c.telefono_id is not None
    intento = db.get(IntentoContacto, c.intento_contacto_id)
    assert (intento.iniciado_por, intento.momento) == ("cliente", c.abierta_en)
    filas = db.scalars(select(ColaAtencion).order_by(ColaAtencion.id)).all()
    assert [(f.estado, f.motivo, f.campana_id) for f in filas] == [
        ("cerrada", "sin_campana", None),
        ("pendiente", "entrante", ctx.campana.id),
    ]
    assert db.scalar(select(Auditoria).where(Auditoria.accion == "conversacion.vincular"))
    # Ya vinculada.
    r = client.put(
        f"{API}/{conv.id}/registro", json={"campana_cliente_id": cc2.id}, headers=h_supervisor
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_YA_VINCULADA"


def test_c10_registro_no_candidato_422(client, db, ctx, reloj, h_supervisor, esc):
    ajeno = esc.registro(ctx.campana, numeros=("+573115550000",))
    conv = crear_conv(db, reloj(), con_cola=True, motivo_cola="sin_campana")
    r = client.put(
        f"{API}/{conv.id}/registro", json={"campana_cliente_id": ajeno.id}, headers=h_supervisor
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "REGISTRO_NO_COINCIDE"
    r = client.put(
        f"{API}/{conv.id}/registro", json={"campana_cliente_id": 99999}, headers=h_supervisor
    )
    assert r.status_code == 422


def test_c11_el_agente_no_ve_conversaciones_ajenas(
    client, db, ctx, reloj, crear_usuario, h_supervisor
):
    ajeno = crear_usuario("agente")
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    crear_saliente(db, conv, reloj(), sid="SM1")
    base = f"{API}/{conv.id}"
    for ruta in ("", "/mensajes", "/ficha", "/registros-candidatos", "/mensajes/1/media/0"):
        r = client.get(base + ruta, headers=cab(ajeno))
        assert r.status_code == 403, ruta
        assert r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"
    assert client.get(API, headers=cab(ajeno)).json()["items"] == []
    mias = client.get(API, headers=cab(ctx.agente)).json()["items"]
    assert [x["id"] for x in mias] == [conv.id]
    # Un agente ignora los filtros usuario_id y sin_campana.
    assert (
        client.get(f"{API}?usuario_id={ajeno.id}&sin_campana=true", headers=cab(ctx.agente)).json()[
            "total"
        ]
        == 1
    )
    # El supervisor ve todo y recibe el E.164.
    r = client.get(f"{API}/{conv.id}", headers=h_supervisor)
    assert r.status_code == 200 and r.json()["numero_e164"] == NUMERO


def test_listado_filtros_y_orden(client, db, ctx, reloj, h_supervisor, esc):
    c1 = conv_de(db, ctx, reloj)
    cc = esc.registro(ctx.campana, numeros=("+573115550001",))
    c2 = crear_conv(
        db, reloj() + timedelta(minutes=1), numero="+573115550001", cc=cc, con_cola=True
    )
    c2.ultimo_mensaje_en = reloj() + timedelta(minutes=1)
    c3 = crear_conv(db, reloj(), numero="+573115550002", con_cola=True, motivo_cola="sin_campana")
    db.commit()
    r = client.get(API, headers=h_supervisor)
    assert [x["id"] for x in r.json()["items"]] == [c2.id, c3.id, c1.id]  # recientes primero
    assert r.json()["total"] == 3
    assert [
        x["id"] for x in client.get(f"{API}?sin_campana=true", headers=h_supervisor).json()["items"]
    ] == [c3.id]
    assert (
        client.get(f"{API}?campana_id={ctx.campana.id}", headers=h_supervisor).json()["total"] == 2
    )
    assert client.get(f"{API}?estado=cerrada", headers=h_supervisor).json()["total"] == 0
    assert client.get(f"{API}?atendida_por=humano", headers=h_supervisor).json()["total"] == 0
    assert client.get(f"{API}?estado=otra", headers=h_supervisor).status_code == 422


def test_c12_paginacion_de_mensajes_con_antes_de(client, db, ctx, reloj):
    conv = conv_de(db, ctx, reloj)
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    ids = [crear_saliente(db, conv, reloj(), sid=f"SM{i}").id for i in range(7)]
    r = client.get(f"{API}/{conv.id}/mensajes?limite=3", headers=cab(ctx.agente)).json()
    assert [m["id"] for m in r["items"]] == ids[-3:] and r["hay_mas"] is True
    r = client.get(
        f"{API}/{conv.id}/mensajes?limite=3&antes_de={ids[-3]}", headers=cab(ctx.agente)
    ).json()
    assert [m["id"] for m in r["items"]] == ids[1:4] and r["hay_mas"] is True
    r = client.get(
        f"{API}/{conv.id}/mensajes?limite=3&antes_de={ids[1]}", headers=cab(ctx.agente)
    ).json()
    assert [m["id"] for m in r["items"]] == ids[:1] and r["hay_mas"] is False
    assert (
        client.get(f"{API}/{conv.id}/mensajes?limite=101", headers=cab(ctx.agente)).status_code
        == 422
    )
    assert (
        len(client.get(f"{API}/{conv.id}/mensajes", headers=cab(ctx.agente)).json()["items"]) == 7
    )


def test_leida_pone_a_cero_el_contador(client, firmar_twilio, correr_trabajos, db, ctx):
    entrante(client, firmar_twilio, texto="uno")
    entrante(client, firmar_twilio, texto="dos")
    correr_trabajos()
    conv = db.scalar(select(Conversacion))
    assert conv.mensajes_sin_leer == 2
    assert (
        client.post(f"{API}/{conv.id}/leida", headers=cab(ctx.agente)).status_code == 403
    )  # no es dueño
    client.post(f"{API}/{conv.id}/tomar", headers=cab(ctx.agente))
    assert client.post(f"{API}/{conv.id}/leida", headers=cab(ctx.agente)).status_code == 204
    db.expire_all()
    assert db.get(Conversacion, conv.id).mensajes_sin_leer == 0


def test_c13_cierre_por_inactividad_sin_tipificacion_y_cancela_retenidos(
    db, ctx, reloj, session_factory
):
    from app.modulos.conversaciones.cierre_inactivas import cerrar_inactivas

    conv = conv_de(db, ctx, reloj)
    retenido = crear_saliente(db, conv, reloj(), estado="retenido", tipo="texto")
    reciente = conv_de(db, ctx, reloj, numero="+573115550003")
    base = reloj()
    # Antes de las 24 h del último mensaje (y de que cierre la ventana): sigue abierta.
    cerrar_inactivas(db, {}, base + timedelta(hours=23, minutes=59))
    db.commit()
    db.expire_all()
    assert db.get(Conversacion, conv.id).estado == "abierta"
    # Pasadas 24 h: se cierra por inactividad, sin tipificación.
    reciente.ultimo_mensaje_en = base + timedelta(hours=20)
    reciente.ventana_expira_en = base + timedelta(hours=44)
    db.commit()
    cerrar_inactivas(db, {}, base + timedelta(hours=24, minutes=1))
    db.commit()
    db.expire_all()
    c = db.get(Conversacion, conv.id)
    assert (c.estado, c.motivo_cierre, c.cerrada_por, c.clave_abierta) == (
        "cerrada",
        "inactividad",
        None,
        None,
    )
    assert db.get(Mensaje, retenido.id).estado == "cancelado"
    assert db.get(Conversacion, reciente.id).estado == "abierta"
    assert (
        db.scalar(select(ColaAtencion).where(ColaAtencion.conversacion_id == conv.id)).estado
        == "cerrada"
    )
    from app.modulos.consola.modelos import Tipificacion

    assert db.scalar(select(Tipificacion.id)) is None


def test_cierre_inactivas_usa_el_maximo_entre_ventana_y_ultimo_mensaje(db, ctx, reloj):
    from app.modulos.conversaciones.cierre_inactivas import cerrar_inactivas

    conv = conv_de(db, ctx, reloj)
    conv.ultimo_mensaje_en = reloj()
    conv.ventana_expira_en = reloj() + timedelta(hours=30)  # la ventana dura más que 24 h
    db.commit()
    cerrar_inactivas(db, {}, reloj() + timedelta(hours=25))
    db.commit()
    db.expire_all()
    assert db.get(Conversacion, conv.id).estado == "abierta"
    cerrar_inactivas(db, {}, reloj() + timedelta(hours=30, seconds=1))
    db.commit()
    db.expire_all()
    assert db.get(Conversacion, conv.id).estado == "cerrada"


def test_ninguna_transicion_de_dueno_fuera_de_cambiar_dueno():
    """B26: nadie escribe `atendida_por` salvo `conversaciones/servicio.py`."""
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2] / "app"
    patron = re.compile(
        r"\batendida_por\s*=[^=]|\.atendida_por\s*=[^=]|usuario_asignado_id\s*=[^=]"
    )
    culpables = []
    for ruta in raiz.rglob("*.py"):
        if ruta.name in ("servicio.py",) and ruta.parent.name == "conversaciones":
            continue
        if ruta.name == "modelos.py":
            continue
        for n, linea in enumerate(ruta.read_text().splitlines(), 1):
            codigo = linea.split("#")[0]
            lado_derecho = codigo.split("=", 1)[-1]
            # Se ignoran las lecturas (salidas de la API) y los filtros `Conversacion.x == ...`.
            if patron.search(codigo) and "atendida_por" not in lado_derecho:
                culpables.append(f"{ruta.relative_to(raiz)}:{n}: {linea.strip()}")
    assert culpables == []
