"""QA 2B: el proxy de medios con el adaptador REAL de Twilio (transporte simulado) no debe
hablar con nadie que no sea `api.twilio.com` de la cuenta configurada, ni con rutas fuera del
prefijo de mensajes, ni seguir redirecciones a otros orígenes, ni caerse con URLs raras."""

import httpx
import pytest
from escenario import cab
from wa import NUMERO, contexto, crear_conv

from app.config import Settings
from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Mensaje

SID = "AC" + "1" * 32
PREFIJO = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/"


class Transporte:
    def __init__(self, redirige_a: str | None = None):
        self.peticiones: list[httpx.Request] = []
        self.redirige_a = redirige_a

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.peticiones.append(req)
        if self.redirige_a and req.url.host == "api.twilio.com":
            return httpx.Response(302, headers={"location": self.redirige_a})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG")


def _montar(db, reloj, monkeypatch, ctx, url, transporte):
    ajustes = Settings(
        _env_file=None,
        entorno="test",
        whatsapp_proveedor="twilio",
        twilio_account_sid=SID,
        twilio_auth_token="tok",
        twilio_api_key_sid="SK1",
        twilio_api_key_secret="secreto",
        public_base_url="https://x.co",
    )
    proveedor = ProveedorWhatsAppTwilio(ajustes, transporte_http=httpx.MockTransport(transporte))
    monkeypatch.setattr(
        "app.modulos.whatsapp.servicio_medios.obtener_proveedor_whatsapp", lambda: proveedor
    )
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    m = Mensaje(
        conversacion_id=conv.id,
        numero_cliente_e164=NUMERO,
        direccion="entrante",
        autor="cliente",
        tipo="media",
        cuerpo="x",
        estado="recibido",
        creado_en=reloj(),
        procesado_en=reloj(),
        media=[
            {
                "indice": 0,
                "tipo_contenido": "image/png",
                "categoria": "imagen",
                "url_proveedor": url,
            }
        ],
    )
    db.add(m)
    db.commit()
    return f"/api/v1/conversaciones/{conv.id}/mensajes/{m.id}/media/0"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "https://api.twilio.com.evil.example/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "https://api.twilio.com@evil.example/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "http://api.twilio.com/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "HTTPS://api.twilio.com/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "https://api.twilio.com/2010-04-01/Accounts/ACotra/Messages/MM1",
        "https://api.twilio.com:8443/2010-04-01/Accounts/" + SID + "/Messages/MM1",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/api/v1/usuarios",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_PING",
        "//evil.example/x",
        "",
    ],
)
def test_urls_fuera_del_prefijo_no_generan_ninguna_peticion(
    client, db, ctx, reloj, monkeypatch, url
):
    t = Transporte()
    ruta = _montar(db, reloj, monkeypatch, ctx, url, t)
    r = client.get(ruta, headers=cab(ctx.agente))
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "MEDIA_NO_DISPONIBLE"
    assert t.peticiones == []


def test_url_valida_envia_credenciales_solo_a_api_twilio(client, db, ctx, reloj, monkeypatch):
    t = Transporte()
    ruta = _montar(db, reloj, monkeypatch, ctx, PREFIJO + "MM1/Media/ME1", t)
    r = client.get(ruta, headers=cab(ctx.agente))
    assert r.status_code == 200
    assert [p.url.host for p in t.peticiones] == ["api.twilio.com"]
    assert t.peticiones[0].headers["authorization"].startswith("Basic ")


# --- Hallazgos: estas pruebas fallan hoy (ver informe de QA) ------------------------------------
def test_h1_una_redireccion_a_otro_origen_no_se_sigue(client, db, ctx, reloj, monkeypatch):
    """El CDN legítimo de Twilio es `media.twiliocdn.com`; cualquier otro destino (p. ej. la
    metadata de la nube) debe abortarse."""
    t = Transporte(redirige_a="http://169.254.169.254/latest/meta-data/")
    ruta = _montar(db, reloj, monkeypatch, ctx, PREFIJO + "MM1/Media/ME1", t)
    r = client.get(ruta, headers=cab(ctx.agente))
    assert [p.url.host for p in t.peticiones] == ["api.twilio.com"], [
        str(p.url) for p in t.peticiones
    ]
    assert r.status_code in (404, 502)


@pytest.mark.parametrize(
    "sufijo", ["../../ACotra/Calls.json", "%2e%2e/%2e%2e/ACotra/Calls.json", "MM1/../../Calls.json"]
)
def test_h2_las_rutas_con_puntos_no_escapan_del_prefijo_de_mensajes(
    client, db, ctx, reloj, monkeypatch, sufijo
):
    t = Transporte()
    ruta = _montar(db, reloj, monkeypatch, ctx, PREFIJO + sufijo, t)
    client.get(ruta, headers=cab(ctx.agente))
    for p in t.peticiones:
        assert str(p.url).startswith(PREFIJO), str(p.url)


def test_h3_una_url_con_caracteres_de_control_no_provoca_500(client, db, ctx, reloj, monkeypatch):
    t = Transporte()
    ruta = _montar(db, reloj, monkeypatch, ctx, PREFIJO + "MM1\r\nX-Inyectado: 1", t)
    r = client.get(ruta, headers=cab(ctx.agente))
    assert r.status_code == 404, r.status_code
