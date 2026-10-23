"""Construcción PURA de TwiML (§4.5). Los valores de atributos y textos se escapan como XML."""

from xml.sax.saxutils import escape, quoteattr

CABECERA = '<?xml version="1.0" encoding="UTF-8"?>'


def _attr(nombre: str, valor: object) -> str:
    return f"{nombre}={quoteattr(str(valor))}"


def twiml_marcar(
    *,
    numero: str,
    base_url: str,
    llamada_id: int,
    grabar: bool,
    caller_id: str | None = None,
    timeout: int = 30,
    time_limit: int = 3600,
) -> str:
    """`<Dial>` hacia `numero` con estado, aviso de grabación (pierna del cliente) y grabación."""
    q = f"?llamada_id={llamada_id}"
    api = f"{base_url}/api/v1/telefonia"
    dial = []
    if caller_id:
        dial.append(_attr("callerId", caller_id))
    dial += [
        _attr("answerOnBridge", "true"),
        _attr("timeout", timeout),
        _attr("timeLimit", time_limit),
    ]
    if grabar:
        dial += [
            _attr("record", "record-from-answer-dual"),
            _attr("recordingStatusCallback", f"{api}/webhooks/grabacion{q}"),
            _attr("recordingStatusCallbackEvent", "completed"),
        ]
    dial += [_attr("action", f"{api}/twiml/dial-terminado{q}"), _attr("method", "POST")]
    numero_attrs = []
    if grabar:
        numero_attrs += [_attr("url", f"{api}/twiml/aviso-grabacion{q}"), _attr("method", "POST")]
    numero_attrs += [
        _attr("statusCallback", f"{api}/webhooks/estado{q}"),
        _attr("statusCallbackEvent", "initiated ringing answered completed"),
        _attr("statusCallbackMethod", "POST"),
    ]
    return (
        f"{CABECERA}<Response><Dial {' '.join(dial)}>"
        f"<Number {' '.join(numero_attrs)}>{escape(numero)}</Number></Dial></Response>"
    )


def twiml_rechazo(mensaje: str, idioma: str) -> str:
    return (
        f"{CABECERA}<Response><Say {_attr('language', idioma)}>{escape(mensaje)}</Say>"
        "<Hangup/></Response>"
    )


def twiml_aviso_grabacion(texto: str, idioma: str) -> str:
    return f"{CABECERA}<Response><Say {_attr('language', idioma)}>{escape(texto)}</Say></Response>"


def twiml_colgar() -> str:
    return f"{CABECERA}<Response><Hangup/></Response>"
