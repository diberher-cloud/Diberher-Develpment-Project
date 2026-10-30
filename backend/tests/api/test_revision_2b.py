"""Revisión post-revisor 2B: B1 (intentos de plantillas), S1, S3, S4, S6-S10 y S12."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from escenario import cab, telefono_de
from sqlalchemy import func, select
from wa import NUMERO, autorizar, clave, contexto, crear_conv, entrante

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import EventoMensaje, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal, PlantillaWhatsApp
from app.trabajos.modelos import LatidoWorker

API = "/api/v1"
BOG = ZoneInfo("America/Bogota")


def hora(dia, h, m=0):
    return datetime(2026, 10, dia, h, m, tzinfo=BOG).astimezone(UTC)


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    c = contexto(esc, crear_usuario, reloj, db)
    esc.reservar(c.cc, c.agente, reloj())
    return c


def consola(client, ctx, db):
    return client.post(
        f"{API}/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={
            "telefono_id": telefono_de(db, ctx.cc).id,
            "plantilla_id": ctx.plantilla.id,
            "idempotencia_clave": clave(),
        },
        headers=cab(ctx.agente),
    )


def en_conv(client, ctx, conv_id):
    return client.post(
        f"{API}/conversaciones/{conv_id}/plantillas",
        json={"plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )


# ---- B1 ----------------------------------------------------------------------------------------
def test_b1_segunda_plantilla_en_conversacion_reutilizada_registra_intento(
    client, db, ctx, reloj, correr_trabajos
):
    autorizar(db)
    reloj.fijar(hora(20, 10))  # martes
    r = consola(client, ctx, db)
    assert r.json()["permitido"], r.text
    conv_id = r.json()["conversacion_id"]
    correr_trabajos()
    reloj.fijar(hora(21, 9))  # miércoles, 23 h después
    r2 = en_conv(client, ctx, conv_id)
    assert r2.status_code == 200 and r2.json()["permitido"], r2.text
    assert db.scalar(select(func.count(IntentoContacto.id))) == 2
    # El intento de la conversación sigue siendo el primero.
    from app.modulos.conversaciones.modelos import Conversacion

    primero = db.scalar(select(IntentoContacto.id).order_by(IntentoContacto.id))
    assert db.get(Conversacion, conv_id).intento_contacto_id == primero


def test_b1_la_tercera_plantilla_queda_bloqueada_por_frecuencia_dia(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos
):
    autorizar(db)
    reloj.fijar(hora(20, 10))
    conv_id = consola(client, ctx, db).json()["conversacion_id"]
    correr_trabajos()
    entrante(client, firmar_twilio, texto="Sí, dígame")  # contacto directo: activa la frecuencia
    correr_trabajos()
    reloj.fijar(hora(21, 9))
    assert en_conv(client, ctx, conv_id).json()["permitido"] is True  # 2.ª: otro día
    reloj.fijar(hora(21, 9, 30))
    r3 = en_conv(client, ctx, conv_id)
    assert r3.status_code == 200 and r3.json()["permitido"] is False
    assert "FRECUENCIA_DIA" in [m["codigo"] for m in r3.json()["motivos"]]
    assert db.scalar(select(func.count(IntentoContacto.id))) == 2


def test_b1_la_plantilla_en_conversacion_reutilizada_limita_la_voz(client, db, ctx, reloj):
    from app.modulos.cumplimiento import servicio as cumplimiento

    autorizar(db)
    conv = crear_conv(
        db, reloj() - timedelta(days=3), cc=ctx.cc, dueno=Humano(ctx.agente.id), ventana=False
    )
    assert en_conv(client, ctx, conv.id).json()["permitido"] is True
    db.expire_all()
    intento = db.scalar(select(IntentoContacto).where(IntentoContacto.canal == "whatsapp_mensaje"))
    assert intento is not None and intento.iniciado_por == "empresa"
    assert cumplimiento.evaluar_para_cliente is not None


# ---- S1 ----------------------------------------------------------------------------------------
def test_s1_plantilla_encolada_no_se_envia_de_madrugada(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    reloj.fijar(hora(20, 18, 30))
    m = consola(client, ctx, db).json()["mensaje"]
    assert correr_trabajos(hora(21, 2, 0)) == 1  # el worker vuelve a las 02:00
    db.expire_all()
    fila = db.get(Mensaje, m["id"])
    assert (fila.estado, fila.error_codigo) == ("fallido", "FUERA_DE_FRANJA")
    assert proveedor_whatsapp.enviados == []
    r = client.get(f"{API}/conversaciones/{fila.conversacion_id}/mensajes", headers=cab(ctx.agente))
    assert r.json()["items"][0]["error"]["codigo"] == "FUERA_DE_FRANJA"


def test_s1_festivo_se_revalida_al_ejecutar(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    reloj.fijar(hora(9, 10))
    m = consola(client, ctx, db).json()["mensaje"]
    assert correr_trabajos(hora(12, 10)) == 1  # lunes festivo (Día de la Raza)
    db.expire_all()
    assert db.get(Mensaje, m["id"]).error_codigo == "FUERA_DE_FRANJA"
    assert proveedor_whatsapp.enviados == []


def test_s1_plantilla_desactivada_antes_de_enviar(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    m = consola(client, ctx, db).json()["mensaje"]
    ctx.plantilla.activa = False
    db.commit()
    correr_trabajos()
    db.expire_all()
    assert db.get(Mensaje, m["id"]).error_codigo == "PLANTILLA_NO_ENVIABLE"
    assert proveedor_whatsapp.enviados == []


def test_s1_opt_out_entre_el_encolado_y_la_ejecucion(
    client, db, ctx, reloj, correr_trabajos, proveedor_whatsapp, admin
):
    autorizar(db)
    m = consola(client, ctx, db).json()["mensaje"]
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="solicitud_titular",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
            creado_en=reloj(),
        )
    )
    db.commit()
    correr_trabajos()
    db.expire_all()
    assert db.get(Mensaje, m["id"]).error_codigo == "CLIENTE_OPT_OUT"
    assert proveedor_whatsapp.enviados == []


# ---- S7 ----------------------------------------------------------------------------------------
def test_s7_conversacion_ver_solo_se_audita_con_apertura(client, db, ctx, reloj):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    for _ in range(3):
        assert (
            client.get(f"{API}/conversaciones/{conv.id}", headers=cab(ctx.agente)).status_code
            == 200
        )

    def n():
        return db.scalar(
            select(func.count(Auditoria.id)).where(Auditoria.accion == "conversacion.ver")
        )

    assert n() == 0
    r = client.get(f"{API}/conversaciones/{conv.id}?apertura=true", headers=cab(ctx.agente))
    assert r.status_code == 200 and n() == 1
    assert (
        client.get(
            f"{API}/conversaciones/{conv.id}?apertura=false", headers=cab(ctx.agente)
        ).status_code
        == 200
    )
    assert n() == 1


# ---- S8 ----------------------------------------------------------------------------------------
def test_s8_sincronizar_desactiva_marketing_sin_boton_de_baja(
    client, h_admin, db, proveedor_whatsapp
):
    client.post(f"{API}/whatsapp/plantillas/sincronizar", headers=h_admin)
    p = db.scalar(select(PlantillaWhatsApp).where(PlantillaWhatsApp.content_sid == "HXfalso0001"))
    p.activa, p.finalidad, p.mapeo_variables = (
        True,
        "cobranza",
        {"1": "primer_nombre", "2": "empresa"},
    )
    db.commit()
    # La plantilla pasa a marketing sin botón de baja en el proveedor.
    proveedor_whatsapp.plantillas[0] = replace(
        proveedor_whatsapp.plantillas[0], categoria="marketing"
    )
    r = client.post(f"{API}/whatsapp/plantillas/sincronizar", headers=h_admin)
    assert r.json() == {"creadas": 0, "actualizadas": 1, "desactivadas": 1}
    db.expire_all()
    assert db.get(PlantillaWhatsApp, p.id).activa is False
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.plantilla_desactivada"))
    assert aud.detalle == {"plantilla_id": p.id, "motivo": "marketing_sin_baja"}


def test_s8_una_plantilla_marketing_sin_baja_no_es_enviable():
    from app.modulos.whatsapp.servicio_plantillas import enviable

    p = PlantillaWhatsApp(
        categoria="marketing",
        tiene_boton_baja=False,
        activa=True,
        estado_aprobacion="aprobada",
        finalidad="venta",
        variables=[],
        mapeo_variables={},
    )
    assert enviable(p) is False
    p.tiene_boton_baja = True
    assert enviable(p) is True


# ---- S10 ---------------------------------------------------------------------------------------
def _revocada_por_opt_out(db, numero, finalidad, cuando):
    db.add(
        AutorizacionCanal(
            numero_e164=numero,
            canal="whatsapp",
            finalidad=finalidad,
            origen="importacion",
            evidencia="x",
            otorgada_en=cuando - timedelta(days=30),
            revocada_en=cuando,
            motivo_revocacion="opt_out",
            creado_en=cuando - timedelta(days=30),
        )
    )
    db.commit()


def test_s10_no_se_puede_revivir_una_autorizacion_anterior_al_opt_out(client, h_admin, db, reloj):
    _revocada_por_opt_out(db, NUMERO, "cobranza", reloj() - timedelta(days=1))
    cuerpo = {"telefono": "3001234567", "finalidad": "cobranza", "evidencia": "formulario viejo"}
    r = client.post(
        f"{API}/autorizaciones",
        json={**cuerpo, "otorgada_en": (reloj() - timedelta(days=10)).isoformat()},
        headers=h_admin,
    )
    assert (
        r.status_code == 409 and r.json()["error"]["codigo"] == "AUTORIZACION_REVOCADA_POR_OPT_OUT"
    )
    # Una autorización posterior al opt-out (el titular volvió a aceptar) sí se admite.
    r = client.post(f"{API}/autorizaciones", json=cuerpo, headers=h_admin)
    assert r.status_code == 201
    # Otro número u otra finalidad no se ven afectados.
    r = client.post(
        f"{API}/autorizaciones",
        json={
            **cuerpo,
            "telefono": "3109998888",
            "otorgada_en": (reloj() - timedelta(days=10)).isoformat(),
        },
        headers=h_admin,
    )
    assert r.status_code == 201


def test_s10_la_importacion_omite_con_advertencia(client, h_admin, db, reloj):
    _revocada_por_opt_out(db, "+573001111111", "cobranza", datetime(2026, 10, 20, tzinfo=UTC))
    camp = client.post(
        f"{API}/campanas", json={"nombre": "Camp S10", "tipo": "cobranza"}, headers=h_admin
    ).json()
    csv = (
        b"tipo_documento,numero_documento,nombre,telefono_1,autoriza_whatsapp,fecha_autorizacion_whatsapp\n"
        b"CC,1001,Ana Uno,3001111111,si,2026-10-01\n"
        b"CC,1002,Beto Dos,3002222222,si,2026-10-01\n"
    )
    r = client.post(
        f"{API}/campanas/{camp['id']}/importaciones",
        files={"archivo": ("c.csv", csv, "text/csv")},
        headers=h_admin,
    )
    assert r.status_code in (200, 201), r.text
    avisos = [e for e in r.json()["errores"] if e["codigo"] == "AUTORIZACION_REVOCADA_POR_OPT_OUT"]
    assert len(avisos) == 1 and avisos[0]["fila"] == 2 and avisos[0]["severidad"] == "advertencia"
    vigentes = {a.numero_e164 for a in db.scalars(select(AutorizacionCanal)) if a.clave_vigente}
    assert vigentes == {"+573002222222"}
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "importacion.autorizaciones"))
    assert (aud.detalle["creadas"], aud.detalle["ignoradas"]) == (1, 1)


# ---- S6 ----------------------------------------------------------------------------------------
def test_s6_la_purga_limpia_latidos_viejos_y_eventos_huerfanos(db, reloj):
    from app.trabajos.mantenimiento import purgar

    ahora = reloj()
    db.add_all(
        [
            LatidoWorker(
                trabajador="viejo",
                iniciado_en=ahora - timedelta(days=9),
                ultimo_latido=ahora - timedelta(days=8),
                version="x",
            ),
            LatidoWorker(trabajador="vivo", iniciado_en=ahora, ultimo_latido=ahora, version="x"),
            EventoMensaje(
                proveedor_id="SMa", estado_proveedor="sent", recibido_en=ahora - timedelta(days=8)
            ),
            EventoMensaje(
                proveedor_id="SMb", estado_proveedor="sent", recibido_en=ahora - timedelta(days=1)
            ),
        ]
    )
    db.commit()
    purgar(db, {}, ahora)
    db.commit()
    assert {x.trabajador for x in db.scalars(select(LatidoWorker))} == {"vivo"}
    assert {e.proveedor_id for e in db.scalars(select(EventoMensaje))} == {"SMb"}


def test_s6_supervision_no_lista_workers_sin_latido_reciente(client, h_admin, db, reloj):
    ahora = reloj()
    db.add_all(
        [
            LatidoWorker(
                trabajador="reciente",
                iniciado_en=ahora,
                ultimo_latido=ahora - timedelta(minutes=5),
                version="x",
            ),
            LatidoWorker(
                trabajador="antiguo",
                iniciado_en=ahora,
                ultimo_latido=ahora - timedelta(hours=3),
                version="x",
            ),
        ]
    )
    db.commit()
    r = client.get(f"{API}/supervision/trabajos", headers=h_admin).json()
    assert [(t["trabajador"], t["activo"]) for t in r["trabajadores"]] == [("reciente", False)]


def test_s4_exclusion_del_titular_posterior_bloquea_autorizaciones_antiguas(
    client, h_admin, db, reloj
):
    """Sin autorización revocada que lo evidencie, una exclusión del titular posterior basta."""
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="solicitud_titular",
            aplica_a="todas",
            canal="whatsapp",
            origen="sistema",
            creado_en=reloj() - timedelta(days=1),
        )
    )
    db.add(
        Exclusion(
            numero_e164="+573109998888",
            motivo="manual",  # no es solicitud del titular: no bloquea
            aplica_a="todas",
            canal="todos",
            origen="sistema",
            creado_en=reloj() - timedelta(days=1),
        )
    )
    db.commit()
    cuerpo = {"telefono": "3001234567", "finalidad": "cobranza", "evidencia": "formulario viejo"}
    viejo = {"otorgada_en": (reloj() - timedelta(days=10)).isoformat()}
    r = client.post(f"{API}/autorizaciones", json={**cuerpo, **viejo}, headers=h_admin)
    assert (
        r.status_code == 409 and r.json()["error"]["codigo"] == "AUTORIZACION_REVOCADA_POR_OPT_OUT"
    )
    r = client.post(
        f"{API}/autorizaciones", json={**cuerpo, "telefono": "3109998888", **viejo}, headers=h_admin
    )
    assert r.status_code == 201
