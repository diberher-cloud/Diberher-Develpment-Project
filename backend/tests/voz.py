"""Ayudantes compartidos para los tests de voz (TwiML saliente, webhooks, tipificaciones)."""

from types import SimpleNamespace

from escenario import telefono_de

RUTA_SALIENTE = "/api/v1/telefonia/twiml/saliente"
API = "/api/v1/telefonia"


def contexto(esc, crear_usuario, reloj, tipo="cobranza", **kw_registro):
    """Agente disponible, asignado a una campaña activa, con un registro reservado por él."""
    agente = crear_usuario("agente")
    campana = esc.campana(tipo=tipo)
    esc.asignar(campana, agente)
    cc = esc.registro(campana, **kw_registro)
    esc.estado(agente, "disponible", reloj())
    esc.reservar(cc, agente, reloj())
    return SimpleNamespace(agente=agente, campana=campana, cc=cc)


def params_saliente(ctx, db, sid="CA0001", **kw):
    base = {
        "CallSid": sid,
        "From": f"client:agente_{ctx.agente.id}",
        "AccountSid": "ACx",
        "campana_cliente_id": str(ctx.cc.id),
        "telefono_id": str(telefono_de(db, ctx.cc).id),
    }
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def llamar(client, firmar_twilio, p):
    return client.post(RUTA_SALIENTE, **firmar_twilio(RUTA_SALIENTE, p))


def webhook(client, firmar_twilio, ruta, params, consulta=""):
    url = API + ruta
    return client.post(
        url + (f"?{consulta}" if consulta else ""), **firmar_twilio(url, params, consulta)
    )
