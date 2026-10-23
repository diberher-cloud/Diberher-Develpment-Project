import base64
import hashlib
import hmac

from twilio.request_validator import RequestValidator

from app.integraciones.twilio_firma import firma_twilio, validar_firma

TOKEN = "12345"
URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
PARAMS = {
    "CallSid": "CA1234567890ABCDE",
    "Caller": "+14158675309",
    "Digits": "1234",
    "From": "+14158675309",
    "To": "+18005551212",
}


def _independiente(url, params, token):
    texto = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), texto.encode(), hashlib.sha1).digest()
    ).decode()


def test_vector_conocido_de_twilio():
    # Vector de la documentación de Twilio (token 12345, URL con query).
    esperada = _independiente(URL, PARAMS, TOKEN)
    assert firma_twilio(URL, PARAMS, TOKEN) == esperada == "RSOYDt4T1cUTdK1PDd93/VVr8B8="
    # Contraste con el SDK oficial.
    assert RequestValidator(TOKEN).compute_signature(URL, PARAMS) == esperada


def test_firma_valida_y_alteraciones():
    firma = firma_twilio(URL, PARAMS, TOKEN)
    assert validar_firma(URL, PARAMS, firma, TOKEN)
    assert not validar_firma(URL, {**PARAMS, "Digits": "9999"}, firma, TOKEN)
    assert not validar_firma(URL.replace("https", "http"), PARAMS, firma, TOKEN)
    assert not validar_firma(URL + "&x=1", PARAMS, firma, TOKEN)
    assert not validar_firma(URL, PARAMS, firma, "otro-token")
    assert not validar_firma(URL, PARAMS, None, TOKEN)
    assert not validar_firma(URL, PARAMS, "", TOKEN)
    assert not validar_firma(URL, {k: v for k, v in PARAMS.items() if k != "To"}, firma, TOKEN)


def test_parametros_multivaluados_se_ordenan_por_valor():
    params = {"a": ["2", "1"], "b": "x"}
    esperada = base64.b64encode(
        hmac.new(TOKEN.encode(), (URL + "a1a2bx").encode(), hashlib.sha1).digest()
    ).decode()
    assert firma_twilio(URL, params, TOKEN) == esperada
