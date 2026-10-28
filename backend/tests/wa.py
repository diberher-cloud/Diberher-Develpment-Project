"""Ayudantes compartidos para los tests de WhatsApp (2B): escenario, webhooks y trabajos."""

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.modulos.whatsapp.modelos import AutorizacionCanal, PlantillaWhatsApp

API = "/api/v1"
RUTA_ENTRANTE = f"{API}/whatsapp/webhooks/entrante"
RUTA_ESTADO = f"{API}/whatsapp/webhooks/estado"
EMPRESA = "+573000000001"
NUMERO = "+573001234567"


def clave() -> str:
    return str(uuid.uuid4())


def params_entrante(numero: str = NUMERO, texto: str | None = "Hola", sid: str | None = None, **kw):
    p = {
        "MessageSid": sid or "SM" + uuid.uuid4().hex,
        "From": f"whatsapp:{numero}",
        "To": f"whatsapp:{EMPRESA}",
        "Body": texto or "",
        "NumMedia": "0",
    }
    p.update({k: v for k, v in kw.items() if v is not None})
    return p


def entrante(client, firmar_twilio, numero: str = NUMERO, texto: str | None = "Hola", **kw):
    p = params_entrante(numero, texto, **kw)
    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p))
    assert r.status_code == 200, r.text
    return p


def estado_webhook(client, firmar_twilio, sid: str, estado: str, **kw):
    p = {"MessageSid": sid, "MessageStatus": estado, **kw}
    return client.post(RUTA_ESTADO, **firmar_twilio(RUTA_ESTADO, p))


def plantilla(db, sid="HXfalso0001", finalidad="cobranza", activa=True, mapeo=None, **kw):
    """Crea (o actualiza) una plantilla enviable sin pasar por la sincronización."""
    from datetime import UTC, datetime

    ahora = datetime(2026, 10, 1, tzinfo=UTC)
    p = db.scalar(select(PlantillaWhatsApp).where(PlantillaWhatsApp.content_sid == sid))
    if p is None:
        p = PlantillaWhatsApp(
            content_sid=sid,
            nombre="recordatorio_cobranza",
            idioma="es",
            categoria="utility",
            estado_aprobacion="aprobada",
            cuerpo="Hola {{1}}, le escribimos de {{2}}. ¿Podemos conversar sobre su cuenta?",
            variables=["1", "2"],
            botones=[],
            tiene_boton_baja=False,
            sincronizada_en=ahora,
            actualizado_en=ahora,
        )
        db.add(p)
    p.mapeo_variables = mapeo if mapeo is not None else {"1": "primer_nombre", "2": "empresa"}
    p.finalidad = finalidad
    p.activa = activa
    for k, v in kw.items():
        setattr(p, k, v)
    db.commit()
    return p


def autorizar(db, numero=NUMERO, finalidad="cobranza", usuario_id=None):
    from datetime import UTC, datetime

    ahora = datetime(2026, 10, 1, tzinfo=UTC)
    db.add(
        AutorizacionCanal(
            numero_e164=numero,
            canal="whatsapp",
            finalidad=finalidad,
            origen="importacion",
            evidencia="test",
            otorgada_en=ahora,
            clave_vigente=f"{numero}|whatsapp|{finalidad}",
            creado_en=ahora,
        )
    )
    db.commit()


def contexto(esc, crear_usuario, reloj, db, tipo="cobranza", numero=NUMERO, **kw_registro):
    """Campaña activa con WhatsApp, un agente disponible asignado, un registro con móvil y una
    plantilla enviable. Sin autorización (la agrega el test que la necesite)."""
    agente = crear_usuario("agente")
    campana = esc.campana(tipo=tipo, whatsapp_habilitado=True)
    esc.asignar(campana, agente)
    kw_registro.setdefault("producto", "Tarjeta Oro")
    cc = esc.registro(campana, numeros=(numero,), **kw_registro)
    esc.estado(agente, "disponible", reloj())
    return SimpleNamespace(
        agente=agente,
        campana=campana,
        cc=cc,
        numero=numero,
        plantilla=plantilla(db, finalidad=tipo),
    )


def crear_conv(
    db,
    ahora,
    numero=NUMERO,
    dueno=None,
    cc=None,
    campana=None,
    iniciada_por="cliente",
    con_cola=False,
    ventana=True,
    motivo_cola="entrante",
):
    """Conversación abierta creada directamente (sin pasar por el webhook)."""
    from datetime import timedelta

    from app.modulos.conversaciones import servicio
    from app.modulos.conversaciones.dueno import SinAsignar

    conv = servicio.crear_conversacion(
        db,
        numero_cliente=numero,
        numero_empresa=EMPRESA,
        iniciada_por=iniciada_por,
        ahora=ahora,
        dueno=dueno or SinAsignar(),
        cliente_id=cc.cliente_id if cc else None,
        campana_id=cc.campana_id if cc else (campana.id if campana else None),
        campana_cliente_id=cc.id if cc else None,
    )
    if cc is not None:
        from app.modulos.clientes.modelos import Telefono

        conv.telefono_id = db.scalar(
            select(Telefono.id).where(
                Telefono.cliente_id == cc.cliente_id, Telefono.numero_e164 == numero
            )
        )
    if ventana:
        conv.ultimo_entrante_en = ahora
        conv.ventana_expira_en = ahora + timedelta(hours=24)
    if con_cola:
        servicio.cambiar_dueno(db, conv, SinAsignar(), motivo_cola, None, ahora)
    db.commit()
    return conv


def crear_saliente(
    db, conv, ahora, estado="enviado", sid=None, tipo="texto", autor="sistema", **kw
):
    from app.modulos.conversaciones.modelos import Mensaje

    m = Mensaje(
        conversacion_id=conv.id,
        numero_cliente_e164=conv.numero_cliente_e164,
        direccion="saliente",
        autor=autor,
        tipo=tipo,
        cuerpo="saliente",
        estado=estado,
        proveedor_id=sid,
        creado_en=ahora,
        **kw,
    )
    db.add(m)
    db.commit()
    return m
