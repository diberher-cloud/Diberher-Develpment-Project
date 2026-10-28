"""Resolución determinista del contexto de una conversación nueva (R1-R8, §4.5)."""

from datetime import timedelta

from sqlalchemy import select
from wa import NUMERO, crear_conv, crear_saliente, entrante

from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion


def procesar(client, firmar_twilio, correr_trabajos, db, texto="Hola", **kw):
    entrante(client, firmar_twilio, texto=texto, **kw)
    correr_trabajos()
    db.expire_all()
    return db.scalars(select(Conversacion).order_by(Conversacion.id.desc())).first()


def test_r1_un_solo_registro_vincula_e_inscribe_el_intento(
    client, firmar_twilio, correr_trabajos, db, esc, crear_usuario, reloj
):
    campana = esc.campana(whatsapp_habilitado=True)
    cc = esc.registro(campana)
    conv = procesar(client, firmar_twilio, correr_trabajos, db)
    assert (conv.campana_id, conv.campana_cliente_id, conv.cliente_id) == (
        campana.id,
        cc.id,
        cc.cliente_id,
    )
    assert conv.telefono_id is not None and conv.intento_contacto_id is not None
    intento = db.get(IntentoContacto, conv.intento_contacto_id)
    assert (intento.canal, intento.iniciado_por, intento.contacto_directo) == (
        "whatsapp_mensaje",
        "cliente",
        True,
    )
    assert intento.momento == conv.abierta_en and intento.politica_version == 1
    assert intento.campana_cliente_id == cc.id and intento.tipo_campana == "cobranza"
    fila = db.scalar(select(ColaAtencion))
    assert (fila.motivo, fila.campana_id) == ("entrante", campana.id)


def test_r2_dos_registros_sin_plantilla_previa_quedan_sin_registro(
    client, firmar_twilio, correr_trabajos, db, esc, h_supervisor
):
    c1 = esc.campana(whatsapp_habilitado=True)
    c2 = esc.campana(whatsapp_habilitado=True, tipo="venta")
    esc.registro(c1)
    esc.registro(c2)
    conv = procesar(client, firmar_twilio, correr_trabajos, db)
    assert (
        conv.campana_cliente_id is None
        and conv.campana_id is None
        and conv.intento_contacto_id is None
    )
    assert db.scalar(select(ColaAtencion)).motivo == "sin_campana"
    r = client.get(f"/api/v1/conversaciones/{conv.id}", headers=h_supervisor)
    codigos = [a["codigo"] for a in r.json()["alertas"]]
    assert "VARIOS_REGISTROS" in codigos and "SIN_CAMPANA" in codigos


def _plantilla_previa(db, reloj, cc, dias):
    """Conversación cerrada con una plantilla enviada hace `dias` días desde el registro `cc`."""
    antes = reloj() - timedelta(days=dias)
    conv = crear_conv(db, antes, cc=cc, iniciada_por="empresa", ventana=False)
    crear_saliente(
        db, conv, antes, estado="enviado", sid="SMprev", tipo="plantilla", autor="sistema"
    )
    conversaciones.cerrar(db, conv, "agente", None, antes + timedelta(hours=1))
    db.commit()


def test_r3_plantilla_reciente_desambigua(client, firmar_twilio, correr_trabajos, db, esc, reloj):
    c1 = esc.campana(whatsapp_habilitado=True)
    c2 = esc.campana(whatsapp_habilitado=True, tipo="venta")
    esc.registro(c1)
    cc2 = esc.registro(c2)
    _plantilla_previa(db, reloj, cc2, dias=10)
    conv = procesar(client, firmar_twilio, correr_trabajos, db)
    assert conv.campana_cliente_id == cc2.id and conv.campana_id == c2.id


def test_r4_plantilla_de_hace_31_dias_no_cuenta(
    client, firmar_twilio, correr_trabajos, db, esc, reloj
):
    c1 = esc.campana(whatsapp_habilitado=True)
    c2 = esc.campana(whatsapp_habilitado=True, tipo="venta")
    esc.registro(c1)
    cc2 = esc.registro(c2)
    _plantilla_previa(db, reloj, cc2, dias=31)
    conv = procesar(client, firmar_twilio, correr_trabajos, db)
    assert conv.campana_cliente_id is None


def test_plantilla_fallida_no_cuenta(client, firmar_twilio, correr_trabajos, db, esc, reloj):
    c1 = esc.campana(whatsapp_habilitado=True)
    c2 = esc.campana(whatsapp_habilitado=True, tipo="venta")
    esc.registro(c1)
    cc2 = esc.registro(c2)
    antes = reloj() - timedelta(days=2)
    conv = crear_conv(db, antes, cc=cc2, iniciada_por="empresa", ventana=False)
    crear_saliente(db, conv, antes, estado="fallido", tipo="plantilla", error_codigo="63003")
    conversaciones.cerrar(db, conv, "agente", None, antes)
    db.commit()
    assert procesar(client, firmar_twilio, correr_trabajos, db).campana_cliente_id is None


def test_r5_campana_sin_whatsapp_o_pausada_no_cuenta(
    client, firmar_twilio, correr_trabajos, db, esc
):
    sin_wa = esc.campana(whatsapp_habilitado=False)
    pausada = esc.campana(whatsapp_habilitado=True, estado="pausada")
    esc.registro(sin_wa)
    esc.registro(pausada)
    conv = procesar(client, firmar_twilio, correr_trabajos, db)
    assert conv.campana_cliente_id is None


def test_r5b_una_campana_valida_y_una_que_no_cuenta_vincula_la_valida(
    client, firmar_twilio, correr_trabajos, db, esc
):
    sin_wa = esc.campana(whatsapp_habilitado=False)
    buena = esc.campana(whatsapp_habilitado=True)
    esc.registro(sin_wa)
    cc = esc.registro(buena)
    assert procesar(client, firmar_twilio, correr_trabajos, db).campana_cliente_id == cc.id


def test_r6_numero_errado_no_vincula(client, firmar_twilio, correr_trabajos, db, esc, admin):
    campana = esc.campana(whatsapp_habilitado=True)
    esc.registro(campana)
    db.add(
        Exclusion(numero_e164=NUMERO, motivo="numero_errado", aplica_a="todas", creado_por=admin.id)
    )
    db.commit()
    assert procesar(client, firmar_twilio, correr_trabajos, db).campana_cliente_id is None


def test_r7_numero_desconocido(client, firmar_twilio, correr_trabajos, db, esc):
    esc.registro(esc.campana(whatsapp_habilitado=True))
    conv = procesar(client, firmar_twilio, correr_trabajos, db, numero="+573119998877")
    assert conv.campana_id is None and conv.cliente_id is None


def test_r8_segundo_mensaje_reutiliza_la_conversacion_sin_repetir_la_resolucion(
    client, firmar_twilio, correr_trabajos, db, esc
):
    campana = esc.campana(whatsapp_habilitado=True)
    esc.registro(campana)
    c1 = procesar(client, firmar_twilio, correr_trabajos, db, texto="uno")
    c2 = procesar(client, firmar_twilio, correr_trabajos, db, texto="dos")
    assert c1.id == c2.id and len(db.scalars(select(Conversacion)).all()) == 1
    assert len(db.scalars(select(IntentoContacto)).all()) == 1
    assert c2.mensajes_sin_leer == 2
    assert len(db.scalars(select(ColaAtencion)).all()) == 1  # no se encola dos veces


def test_entrante_tras_el_cierre_abre_otra_conversacion_c14(
    client, firmar_twilio, correr_trabajos, db, esc, reloj
):
    campana = esc.campana(whatsapp_habilitado=True)
    esc.registro(campana)
    c1 = procesar(client, firmar_twilio, correr_trabajos, db, texto="uno")
    conversaciones.cerrar(db, db.get(Conversacion, c1.id), "agente", None, reloj())
    db.commit()
    c2 = procesar(client, firmar_twilio, correr_trabajos, db, texto="otra vez")
    assert c2.id != c1.id and c2.estado == "abierta"
    assert db.get(Conversacion, c1.id).estado == "cerrada"
