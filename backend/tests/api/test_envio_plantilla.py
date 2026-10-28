"""Envío de plantillas desde la consola y desde la bandeja (E1-E12, §4.6)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from escenario import cab, telefono_de
from sqlalchemy import select
from wa import NUMERO, autorizar, clave, contexto, crear_conv, entrante, plantilla

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion

BOG = ZoneInfo("America/Bogota")


def utc(dia, h, m=0, mes=10):
    return datetime(2026, mes, dia, h, m, tzinfo=BOG).astimezone(UTC)


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    c = contexto(esc, crear_usuario, reloj, db)
    esc.reservar(c.cc, c.agente, reloj())
    return c


def consola(client, ctx, db, plantilla_id=None, telefono=None, idem=None, usuario=None, cc=None):
    cc = cc or ctx.cc
    return client.post(
        f"/api/v1/consola/registros/{cc.id}/whatsapp/plantilla",
        json={
            "telefono_id": telefono or telefono_de(db, cc).id,
            "plantilla_id": plantilla_id or ctx.plantilla.id,
            "idempotencia_clave": idem or clave(),
        },
        headers=cab(usuario or ctx.agente),
    )


def test_e1_permitida_crea_conversacion_intento_y_mensaje_y_el_worker_lo_envia(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    r = consola(client, ctx, db)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["permitido"], cuerpo["motivos"], cuerpo["proxima_ventana_inicio"]) == (
        True,
        [],
        None,
    )
    assert cuerpo["politica_version"] == 1 and cuerpo["conversacion_id"] is not None
    m = cuerpo["mensaje"]
    assert (m["estado"], m["tipo"], m["autor"]) == ("pendiente", "plantilla", "agente")
    assert (
        m["cuerpo"]
        == "Hola María, le escribimos de Mi Empresa S.A.S.. ¿Podemos conversar sobre su cuenta?"
    )
    assert m["plantilla"]["nombre"] == "recordatorio_cobranza"
    db.expire_all()
    conv = db.get(Conversacion, cuerpo["conversacion_id"])
    assert (conv.atendida_por, conv.usuario_asignado_id, conv.iniciada_por) == (
        "humano",
        ctx.agente.id,
        "empresa",
    )
    assert conv.ventana_expira_en is None and conv.campana_cliente_id == ctx.cc.id
    intento = db.get(IntentoContacto, conv.intento_contacto_id)
    assert (intento.canal, intento.iniciado_por, intento.contacto_directo) == (
        "whatsapp_mensaje",
        "empresa",
        False,
    )
    assert intento.politica_version == 1 and intento.momento == reloj()
    assert db.scalar(select(ColaAtencion.id)) is None  # el agente es dueño desde el inicio
    fila = db.get(Mensaje, m["id"])
    assert (
        fila.variables == {"1": "María", "2": "Mi Empresa S.A.S."}
        and fila.plantilla_id == ctx.plantilla.id
    )
    # El registro conserva la reserva y registra la gestión; los intentos cuentan al cerrar.
    cc = ctx.cc
    db.refresh(cc)
    assert (
        cc.intentos == 0 and cc.ultima_gestion_en == reloj() and cc.reservado_por == ctx.agente.id
    )
    assert db.scalar(
        select(Auditoria).where(Auditoria.accion == "whatsapp.plantilla_enviada")
    ).detalle == {
        "mensaje_id": m["id"],
        "conversacion_id": conv.id,
        "plantilla_id": ctx.plantilla.id,
        "campana_cliente_id": cc.id,
    }
    assert correr_trabajos() == 1
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert fila.estado == "enviado" and fila.proveedor_id.startswith("SMfalso")
    assert proveedor_whatsapp.enviados == [
        {
            "tipo": "plantilla",
            "destino": NUMERO,
            "plantilla_ref": "HXfalso0001",
            "variables": {"1": "María", "2": "Mi Empresa S.A.S."},
        }
    ]


def test_e2_sin_autorizacion_no_es_error_http_y_no_crea_filas(client, db, ctx):
    r = consola(client, ctx, db)
    assert r.status_code == 200
    cuerpo = r.json()
    assert (
        cuerpo["permitido"] is False
        and cuerpo["conversacion_id"] is None
        and cuerpo["mensaje"] is None
    )
    assert [m["codigo"] for m in cuerpo["motivos"]] == ["SIN_AUTORIZACION"]
    assert "cobranza" in cuerpo["motivos"][0]["mensaje"]
    assert db.scalar(select(Mensaje.id)) is None and db.scalar(select(Conversacion.id)) is None
    assert db.scalar(select(IntentoContacto.id)) is None
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.plantilla_bloqueada"))
    assert aud.detalle == {
        "campana_cliente_id": ctx.cc.id,
        "plantilla_id": ctx.plantilla.id,
        "codigos": ["SIN_AUTORIZACION"],
    }


def test_e2b_autorizacion_de_otra_finalidad_no_sirve(client, db, ctx):
    autorizar(db, finalidad="venta")
    assert consola(client, ctx, db).json()["permitido"] is False
    autorizar(db, finalidad="todas")
    assert consola(client, ctx, db).json()["permitido"] is True


def test_e3_exclusion_para_whatsapp_bloquea_con_excluido(client, db, ctx, admin):
    autorizar(db)
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="rne",
            aplica_a="cobranza",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    codigos = [m["codigo"] for m in consola(client, ctx, db).json()["motivos"]]
    assert codigos == ["EXCLUIDO"]


def test_e3b_exclusion_todos_y_motivos_en_orden(client, db, ctx, admin):
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="manual",
            aplica_a="todas",
            canal="todos",
            creado_por=admin.id,
        )
    )
    db.commit()
    codigos = [m["codigo"] for m in consola(client, ctx, db).json()["motivos"]]
    assert codigos == ["EXCLUIDO", "SIN_AUTORIZACION"]


def test_e4_exclusion_solo_de_voz_no_bloquea_whatsapp(client, db, ctx, admin):
    autorizar(db)
    db.add(
        Exclusion(
            numero_e164=NUMERO, motivo="rne", aplica_a="todas", canal="voz", creado_por=admin.id
        )
    )
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="rne",
            aplica_a="venta",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    assert consola(client, ctx, db).json()["permitido"] is True


def test_e5_domingo_dia_sin_franja_con_proxima_ventana(client, db, ctx, reloj, esc):
    autorizar(db)
    reloj.fijar(utc(25, 10))
    esc.reservar(ctx.cc, ctx.agente, reloj())
    r = consola(client, ctx, db).json()
    assert r["permitido"] is False
    assert [m["codigo"] for m in r["motivos"]] == ["DIA_SIN_FRANJA"]
    assert r["proxima_ventana_inicio"] == "2026-10-26T07:00:00-05:00"


def test_fuera_de_franja_y_festivo(client, db, ctx, reloj, esc):
    autorizar(db)
    reloj.fijar(utc(23, 20))
    esc.reservar(ctx.cc, ctx.agente, reloj())
    assert [m["codigo"] for m in consola(client, ctx, db).json()["motivos"]] == ["FUERA_DE_FRANJA"]
    reloj.fijar(utc(12, 10))  # lunes festivo (Día de la Raza)
    esc.reservar(ctx.cc, ctx.agente, reloj())
    assert "FESTIVO" in [m["codigo"] for m in consola(client, ctx, db).json()["motivos"]]


def test_e6_llamada_de_voz_con_contacto_directo_hoy_bloquea_la_plantilla(client, db, ctx, reloj):
    autorizar(db)
    cumplimiento.registrar_intento(
        db,
        cliente_id=ctx.cc.cliente_id,
        tipo_campana="cobranza",
        canal="voz",
        iniciado_por="empresa",
        momento=reloj() - timedelta(hours=1),
        campana_id=ctx.campana.id,
        contacto_directo=True,
    )
    db.commit()
    codigos = [m["codigo"] for m in consola(client, ctx, db).json()["motivos"]]
    assert codigos == ["FRECUENCIA_DIA", "FRECUENCIA_MEDIOS"] or codigos == ["FRECUENCIA_DIA"]
    assert "FRECUENCIA_DIA" in codigos


def test_e7_la_plantilla_respondida_cuenta_para_la_frecuencia_de_la_voz(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos, esc
):
    autorizar(db)
    reloj.fijar(utc(26, 10))  # lunes
    esc.reservar(ctx.cc, ctx.agente, reloj())
    assert consola(client, ctx, db).json()["permitido"] is True
    correr_trabajos()
    # El cliente responde el mismo lunes: la conversación pasa a contacto directo.
    entrante(client, firmar_twilio, texto="Sí, dígame")
    correr_trabajos()
    db.expire_all()
    intento = db.scalar(select(IntentoContacto))
    assert (intento.iniciado_por, intento.contacto_directo) == ("empresa", True)
    # El miércoles, la voz ya no puede usar otro medio esa semana.
    resultado, _ = cumplimiento.evaluar_para_cliente(
        db, ctx.cc.cliente_id, "cobranza", "voz", utc(28, 10)
    )
    assert [m.codigo for m in resultado.motivos] == ["FRECUENCIA_MEDIOS"]
    # Y la plantilla del mismo día queda limitada por el contacto directo del día.
    wa, _ = cumplimiento.evaluar_para_cliente(
        db, ctx.cc.cliente_id, "cobranza", "whatsapp_mensaje", utc(26, 11)
    )
    assert "FRECUENCIA_DIA" in [m.codigo for m in wa.motivos]


def test_e8_variable_vacia_422(client, db, ctx, esc):
    autorizar(db)
    p = plantilla(
        db,
        sid="HXfalso0002",
        finalidad="cobranza",
        cuerpo="Hola {{1}}, {{2}} tiene una oferta de {{3}}.",
        variables=["1", "2", "3"],
        mapeo={"1": "primer_nombre", "2": "empresa", "3": "producto"},
    )
    cc_sin_producto = esc.registro(ctx.campana, numeros=("+573115550001",))
    esc.reservar(cc_sin_producto, ctx.agente, datetime(2026, 10, 23, 15, 15, tzinfo=UTC))
    r = consola(client, ctx, db, plantilla_id=p.id, cc=cc_sin_producto)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_VARIABLE_VACIA"
    assert r.json()["error"]["detalles"] == [
        {"campo": "plantilla_id", "mensaje": "Falta el valor de {{3}} (producto)."}
    ]
    assert (
        consola(client, ctx, db, plantilla_id=p.id).status_code == 200
    )  # el registro con producto sí


def test_e9_plantilla_de_otra_finalidad_o_no_enviable_422(client, db, ctx):
    autorizar(db)
    venta = plantilla(db, sid="HXventa", finalidad="venta")
    inactiva = plantilla(db, sid="HXinactiva", finalidad="cobranza", activa=False)
    pendiente = plantilla(
        db, sid="HXpend", finalidad="cobranza", activa=False, estado_aprobacion="pendiente"
    )
    for p in (venta, inactiva, pendiente):
        r = consola(client, ctx, db, plantilla_id=p.id)
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_NO_DISPONIBLE", (
            p.content_sid
        )
    assert (
        consola(client, ctx, db, plantilla_id=99999).json()["error"]["codigo"]
        == "PLANTILLA_NO_DISPONIBLE"
    )
    todas = plantilla(db, sid="HXtodas", finalidad="todas")
    assert consola(client, ctx, db, plantilla_id=todas.id).status_code == 200


def test_e12_idempotencia_de_la_plantilla(client, db, ctx, crear_usuario, esc, reloj):
    autorizar(db)
    k = clave()
    r1 = consola(client, ctx, db, idem=k)
    r2 = consola(client, ctx, db, idem=k)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["mensaje"]["id"] == r2.json()["mensaje"]["id"]
    assert (
        r2.json()["permitido"] is True
        and r2.json()["conversacion_id"] == r1.json()["conversacion_id"]
    )
    assert len(db.scalars(select(Mensaje)).all()) == 1
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    cc2 = esc.registro(ctx.campana, numeros=("+573115550001",))
    esc.reservar(cc2, otro, reloj())
    r3 = consola(client, ctx, db, idem=k, usuario=otro, cc=cc2)
    assert r3.status_code == 409 and r3.json()["error"]["codigo"] == "IDEMPOTENCIA_CONFLICTO"


def test_validaciones_previas_de_la_consola(client, db, ctx, esc, crear_usuario, reloj):
    autorizar(db)
    assert consola(client, ctx, db, cc=type("R", (), {"id": 999})(), telefono=1).status_code == 404
    ajeno = crear_usuario("agente")
    esc.estado(ajeno, "disponible", reloj())
    r = consola(client, ctx, db, usuario=ajeno)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"
    esc.asignar(ctx.campana, ajeno)
    r = consola(client, ctx, db, usuario=ajeno)  # asignado, pero sin la reserva del registro
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_NO_RESERVADO"
    # Solo agentes.
    assert (
        client.post(
            f"/api/v1/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
            json={"telefono_id": 1, "plantilla_id": 1, "idempotencia_clave": clave()},
            headers=cab(crear_usuario("supervisor")),
        ).status_code
        == 403
    )


def test_campana_sin_whatsapp_o_no_activa_409(client, db, ctx, esc):
    autorizar(db)
    ctx.campana.whatsapp_habilitado = False
    db.commit()
    r = consola(client, ctx, db)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "WHATSAPP_NO_HABILITADO"
    ctx.campana.whatsapp_habilitado, ctx.campana.estado = True, "pausada"
    db.commit()
    assert consola(client, ctx, db).json()["error"]["codigo"] == "WHATSAPP_NO_HABILITADO"


def test_telefono_de_otro_cliente_o_fijo_422(client, db, ctx, esc):
    autorizar(db)
    otro = esc.registro(ctx.campana, numeros=("+573115550001",))
    r = consola(client, ctx, db, telefono=telefono_de(db, otro).id)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "TELEFONO_NO_VALIDO"
    fijo = esc.registro(ctx.campana, numeros=("+576012345678",))
    esc.reservar(fijo, ctx.agente, datetime(2026, 10, 23, 15, 15, tzinfo=UTC))
    r = consola(client, ctx, db, cc=fijo)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "TELEFONO_NO_VALIDO"
    assert (
        consola(client, ctx, db, telefono=999999).json()["error"]["codigo"] == "TELEFONO_NO_VALIDO"
    )


def test_capacidad_maxima_al_abrir_una_conversacion_nueva(client, db, ctx, esc, reloj):
    autorizar(db)
    for i in range(5):
        cc = esc.registro(ctx.campana, numeros=(f"+57311000000{i}",))
        crear_conv(db, reloj(), numero=f"+57311000000{i}", cc=cc, dueno=Humano(ctx.agente.id))
    r = consola(client, ctx, db)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAPACIDAD_MAXIMA"


def test_ventana_abierta_la_consola_pide_responder_en_la_conversacion(client, db, ctx, reloj):
    autorizar(db)
    crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = consola(client, ctx, db)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "VENTANA_ABIERTA"


def test_conversacion_de_otro_dueno_o_de_otro_registro_409(
    client, db, ctx, esc, crear_usuario, reloj
):
    autorizar(db)
    otro = crear_usuario("agente")
    crear_conv(db, reloj() - timedelta(days=2), cc=ctx.cc, dueno=Humano(otro.id), ventana=False)
    r = consola(client, ctx, db)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_ASIGNADA"


def test_conversacion_abierta_de_otro_registro_409(client, db, ctx, esc, reloj):
    autorizar(db)
    otra = esc.campana(whatsapp_habilitado=True, tipo="venta")
    cc_otro = esc.registro(otra, numeros=(NUMERO,))
    crear_conv(db, reloj() - timedelta(days=2), cc=cc_otro, ventana=False)
    r = consola(client, ctx, db)
    assert (
        r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_ABIERTA_OTRO_REGISTRO"
    )


def test_reutiliza_la_conversacion_sin_dueno_y_se_la_asigna(client, db, ctx, reloj):
    autorizar(db)
    conv = crear_conv(db, reloj() - timedelta(days=2), cc=ctx.cc, con_cola=True, ventana=False)
    r = consola(client, ctx, db)
    assert r.status_code == 200 and r.json()["conversacion_id"] == conv.id
    db.expire_all()
    c = db.get(Conversacion, conv.id)
    assert (c.atendida_por, c.usuario_asignado_id) == ("humano", ctx.agente.id)
    assert len(db.scalars(select(Conversacion)).all()) == 1
    assert db.scalar(select(ColaAtencion)).estado == "asignada"


def test_desde_la_bandeja_usa_el_registro_de_la_conversacion(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    conv = crear_conv(
        db, reloj() - timedelta(days=2), cc=ctx.cc, dueno=Humano(ctx.agente.id), ventana=False
    )
    url = f"/api/v1/conversaciones/{conv.id}/plantillas"
    r = client.post(
        url,
        json={"plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200, r.text
    assert r.json()["permitido"] is True and r.json()["conversacion_id"] == conv.id
    # Con la ventana abierta también se puede enviar plantilla desde la bandeja.
    abierta = crear_conv(
        db, reloj(), numero="+573115550001", cc=ctx.cc, dueno=Humano(ctx.agente.id)
    )
    assert abierta.id
    correr_trabajos()
    assert proveedor_whatsapp.enviados[0]["tipo"] == "plantilla"


def test_desde_la_bandeja_exige_ser_dueno_y_registro(client, db, ctx, reloj, crear_usuario):
    autorizar(db)
    sin_registro = crear_conv(db, reloj(), numero="+573119998877", dueno=Humano(ctx.agente.id))
    cuerpo = {"plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()}
    r = client.post(
        f"/api/v1/conversaciones/{sin_registro.id}/plantillas", json=cuerpo, headers=cab(ctx.agente)
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "WHATSAPP_NO_HABILITADO"
    ajena = crear_conv(db, reloj(), numero="+573115550001", cc=ctx.cc)
    cuerpo = {"plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()}
    r = client.post(
        f"/api/v1/conversaciones/{ajena.id}/plantillas", json=cuerpo, headers=cab(ctx.agente)
    )
    assert r.status_code == 403
    assert (
        client.post(
            "/api/v1/conversaciones/999/plantillas", json=cuerpo, headers=cab(ctx.agente)
        ).status_code
        == 404
    )


def test_el_trabajo_no_envia_si_se_agrego_una_exclusion_despues(
    client, db, ctx, reloj, correr_trabajos, admin, proveedor_whatsapp
):
    autorizar(db)
    m = consola(client, ctx, db).json()["mensaje"]
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="manual",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    correr_trabajos()
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo) == ("fallido", "CONTACTO_NO_PERMITIDO")
    assert proveedor_whatsapp.enviados == []
