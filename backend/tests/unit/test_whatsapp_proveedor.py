"""Proveedor de WhatsApp: parseo de webhooks, proveedor falso y adaptador de Twilio (con dobles)."""

from types import SimpleNamespace

import httpx
import pytest
import requests
from twilio.base.exceptions import TwilioRestException

from app.config import Settings
from app.integraciones.whatsapp import parseo
from app.integraciones.whatsapp.falso import ProveedorWhatsAppFalso
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio

SID = "AC" + "1" * 32
URL_MEDIA = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/MM1/Media/ME1"


def settings() -> Settings:
    return Settings(
        _env_file=None,
        entorno="test",
        whatsapp_proveedor="twilio",
        twilio_account_sid=SID,
        twilio_auth_token="tok",
        twilio_api_key_sid="SK1",
        twilio_api_key_secret="secreto",
        public_base_url="https://x.co",
    )


def entrante(**kw):
    p = {
        "MessageSid": "SM1",
        "From": "whatsapp:+573001234567",
        "To": "whatsapp:+573000000001",
        "Body": "Hola",
        "NumMedia": "0",
    }
    p.update(kw)
    return p


# ---- Parseo ---------------------------------------------------------------------------------
def test_parsear_entrante_valido_con_todos_los_campos():
    m = parseo.parsear_entrante(
        entrante(
            AccountSid="AC1", ProfileName="  María  ", ButtonPayload="BAJA", ButtonText="Baja",
            OriginalRepliedMessageSid="SM0", NumMedia="2", MediaUrl0="https://m/0",
            MediaContentType0="Image/JPEG", MediaUrl1="https://m/1",
            MediaContentType1="audio/ogg; codecs=opus",
        )
    )  # fmt: skip
    assert m is not None
    assert (m.proveedor_id, m.numero_cliente, m.numero_empresa) == (
        "SM1", "+573001234567", "+573000000001",
    )  # fmt: skip
    assert (m.cuenta, m.texto, m.nombre_perfil) == ("AC1", "Hola", "María")
    assert (m.boton_payload, m.boton_texto, m.respuesta_a) == ("BAJA", "Baja", "SM0")
    assert [(x.indice, x.tipo_contenido) for x in m.media] == [(0, "image/jpeg"), (1, "audio/ogg")]


@pytest.mark.parametrize(
    "cambios",
    [
        {"MessageSid": ""},
        {"MessageSid": "S" * 65},
        {"From": "+573001234567"},
        {"From": "whatsapp:3001234567"},
        {"From": "whatsapp:+0123456789"},
        {"To": "sms:+573000000001"},
        {"NumMedia": "11"},
        {"NumMedia": "-1"},
        {"NumMedia": "x"},
    ],
)
def test_parsear_entrante_invalido(cambios):
    assert parseo.parsear_entrante(entrante(**cambios)) is None


def test_parsear_entrante_recorta_y_normaliza():
    m = parseo.parsear_entrante(
        entrante(Body="x" * 5000, ProfileName="n" * 200, NumMedia="1", MediaUrl0="https://m/0")
    )
    assert len(m.texto) == 4096 and len(m.nombre_perfil) == 100
    assert m.media[0].tipo_contenido == ""
    assert parseo.parsear_entrante(entrante(Body="   ")).texto is None
    sin_url = parseo.parsear_entrante(entrante(NumMedia="2", MediaUrl1="https://m/1"))
    assert [x.indice for x in sin_url.media] == [1]


@pytest.mark.parametrize(
    ("crudo", "estado"),
    [
        ("queued", "enviado"), ("accepted", "enviado"), ("scheduled", "enviado"),
        ("sending", "enviado"), ("sent", "enviado"), ("delivered", "entregado"),
        ("read", "leido"), ("failed", "fallido"), ("undelivered", "fallido"),
        ("canceled", "fallido"), ("receiving", None), ("otra", None),
    ],
)  # fmt: skip
def test_parsear_estado(crudo, estado):
    e = parseo.parsear_estado({"MessageSid": "SM1", "MessageStatus": crudo, "ErrorCode": "63016"})
    assert (e.proveedor_id, e.estado_proveedor, e.estado, e.error_codigo) == (
        "SM1", crudo, estado, "63016",
    )  # fmt: skip


def test_parsear_estado_invalido():
    assert parseo.parsear_estado({"MessageStatus": "sent"}) is None
    assert parseo.parsear_estado({"MessageSid": "SM1"}) is None


# ---- Falso ----------------------------------------------------------------------------------
def test_falso_envia_y_registra():
    p = ProveedorWhatsAppFalso("tok")
    r = p.enviar_texto(
        origen="+573000000001", destino="+573001234567", texto="hola", url_estado="u"
    )
    assert r.proveedor_id.startswith("SMfalso") and r.estado_proveedor == "queued"
    p.enviar_plantilla(
        origen="+57300",
        destino="+573001234567",
        plantilla_ref="HX1",
        variables={"1": "a"},
        url_estado="u",
    )
    assert [e["tipo"] for e in p.enviados] == ["texto", "plantilla"]
    assert p.enviados[1]["variables"] == {"1": "a"}
    p.reiniciar()
    assert p.enviados == []


def test_falso_reglas_de_error_por_destino():
    p = ProveedorWhatsAppFalso("tok")
    with pytest.raises(ErrorProveedorWhatsApp) as e0:
        p.enviar_texto(origen="o", destino="+573000000000", texto="x", url_estado="u")
    assert (e0.value.codigo, e0.value.transitorio) == ("63003", False)
    with pytest.raises(ErrorProveedorWhatsApp) as e9:
        p.enviar_texto(origen="o", destino="+573009999999", texto="x", url_estado="u")
    assert (e9.value.codigo, e9.value.transitorio) == ("429", True)
    assert p.enviados == []


def test_falso_plantillas_fijas():
    p = ProveedorWhatsAppFalso("tok")
    plantillas = {x.ref: x for x in p.listar_plantillas()}
    assert list(plantillas) == ["HXfalso0001", "HXfalso0002", "HXfalso0003", "HXfalso0004"]
    assert plantillas["HXfalso0002"].botones[0].payload == "BAJA"
    assert plantillas["HXfalso0003"].estado_aprobacion == "pendiente"
    assert (
        plantillas["HXfalso0004"].categoria == "marketing" and not plantillas["HXfalso0004"].botones
    )


def test_falso_medios():
    p = ProveedorWhatsAppFalso("tok")
    base = "https://media.falso.invalid/abc/"
    assert p.url_media_valida(base + "image/png") and not p.url_media_valida("https://otro/x")
    tipo, datos = p.descargar_media(base + "image/png", 1000)
    assert tipo == "image/png" and datos.startswith(b"\x89PNG")
    assert p.descargar_media(base + "audio/ogg", 1000)[1].startswith(b"OggS")
    assert p.descargar_media(base + "application/pdf", 1000)[1].startswith(b"%PDF")
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        p.descargar_media("https://media.falso.invalid/grande/image/png", 1000)
    assert e.value.codigo == "MEDIA_DEMASIADO_GRANDE"


# ---- Twilio: envío ---------------------------------------------------------------------------
class ClienteFalso:
    def __init__(self, error=None, plantillas=None):
        self.llamadas: list[dict] = []
        self._error = error
        self.messages = SimpleNamespace(create=self._crear)
        self.content = SimpleNamespace(
            v1=SimpleNamespace(content_and_approvals=SimpleNamespace(list=lambda: plantillas or []))
        )

    def _crear(self, **kw):
        self.llamadas.append(kw)
        if self._error:
            raise self._error
        return SimpleNamespace(sid="SMreal1", status="queued")


def twilio(cliente=None, transporte=None):
    return ProveedorWhatsAppTwilio(
        settings(), cliente_rest=lambda: cliente, transporte_http=transporte
    )


def test_twilio_envia_texto_y_plantilla_con_los_parametros_del_contrato():
    c = ClienteFalso()
    p = twilio(c)
    r = p.enviar_texto(
        origen="+573000000001", destino="+573001234567", texto="Hola ñ", url_estado="https://x/e"
    )
    assert (r.proveedor_id, r.estado_proveedor) == ("SMreal1", "queued")
    p.enviar_plantilla(
        origen="+573000000001", destino="+573001234567", plantilla_ref="HX1",
        variables={"1": "María Ñ"}, url_estado="https://x/e",
    )  # fmt: skip
    assert c.llamadas[0] == {
        "from_": "whatsapp:+573000000001", "to": "whatsapp:+573001234567", "body": "Hola ñ",
        "status_callback": "https://x/e",
    }  # fmt: skip
    assert c.llamadas[1] == {
        "from_": "whatsapp:+573000000001", "to": "whatsapp:+573001234567", "content_sid": "HX1",
        "content_variables": '{"1": "María Ñ"}', "status_callback": "https://x/e",
    }  # fmt: skip
    assert "body" not in c.llamadas[1]


def _rest(status, code):
    return TwilioRestException(status, "https://api.twilio.com/x", "msg", code)


@pytest.mark.parametrize(
    ("error", "codigo", "transitorio"),
    [
        (_rest(429, 20429), "20429", True),
        (_rest(503, None), "503", True),
        (_rest(400, 63016), "63016", False),
        (_rest(400, 63003), "63003", False),
        (_rest(401, None), "401", False),
        (requests.ConnectTimeout(), "CONEXION", True),
        (requests.ReadTimeout(), "ENVIO_INCIERTO", False),
        (requests.ConnectionError(), "ENVIO_INCIERTO", False),
        (RuntimeError("raro"), "ENVIO_INCIERTO", False),
    ],
)
def test_twilio_mapea_errores(error, codigo, transitorio):
    p = twilio(ClienteFalso(error=error))
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        p.enviar_texto(origen="+57300", destino="+573001", texto="x", url_estado="u")
    assert (e.value.codigo, e.value.transitorio) == (codigo, transitorio)


# ---- Twilio: plantillas -----------------------------------------------------------------------
def fila(**kw):
    aprobacion = {"status": "APPROVED", "category": "MARKETING", "rejection_reason": ""}
    quick = {"body": "Hola {{1}}", "actions": [{"id": "BAJA", "title": "Baja"}]}
    base = dict(
        sid="HX1",
        friendly_name="oferta",
        language="es",
        variables={"10": "x", "2": "y", "1": "z"},
        types={"twilio/quick-reply": quick},
        approval_requests={"whatsapp": aprobacion},
    )
    base.update(kw)
    return SimpleNamespace(**base)


RECHAZADA = {"status": "rejected", "category": "otra", "rejection_reason": "spam"}


def test_twilio_lista_plantillas_y_mapea_campos():
    p = twilio(
        ClienteFalso(
            plantillas=[
                fila(),
                fila(
                    sid="HX2",
                    variables={},
                    types={"twilio/text": {"body": "Simple"}},
                    approval_requests={"whatsapp": RECHAZADA},
                ),
                fila(sid="HX3", types={"twilio/media": {"media": []}}, approval_requests={}),
                fila(
                    sid="HX4",
                    types={"twilio/call-to-action": {"body": "b", "actions": [
                        {"type": "URL", "title": "Web", "url": "https://x"},
                        {"type": "PHONE_NUMBER", "title": "Llamar", "phone": "+57"},
                    ]}},
                ),
                SimpleNamespace(sid=None),
            ]
        )
    )  # fmt: skip
    r = {x.ref: x for x in p.listar_plantillas()}
    assert set(r) == {"HX1", "HX2", "HX3", "HX4"}
    assert r["HX1"].variables == ("1", "2", "10")  # orden numérico
    assert (r["HX1"].cuerpo, r["HX1"].categoria, r["HX1"].estado_aprobacion) == (
        "Hola {{1}}", "marketing", "aprobada",
    )  # fmt: skip
    assert (r["HX1"].botones[0].tipo, r["HX1"].botones[0].payload) == ("respuesta_rapida", "BAJA")
    assert (r["HX2"].estado_aprobacion, r["HX2"].categoria, r["HX2"].motivo_rechazo) == (
        "rechazada", "desconocida", "spam",
    )  # fmt: skip
    assert r["HX3"].cuerpo == "" and r["HX3"].estado_aprobacion == "desconocido"
    assert [b.tipo for b in r["HX4"].botones] == ["url", "telefono"]


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("approved", "aprobada"), ("pending", "pendiente"), ("received", "pendiente"),
        ("in_review", "pendiente"), ("rejected", "rechazada"), ("paused", "pausada"),
        ("disabled", "deshabilitada"), ("x", "desconocido"),
    ],
)  # fmt: skip
def test_twilio_estados_de_aprobacion(crudo, esperado):
    f = fila(approval_requests={"whatsapp": {"status": crudo, "category": "UTILITY"}})
    (r,) = twilio(ClienteFalso(plantillas=[f])).listar_plantillas()
    assert r.estado_aprobacion == esperado and r.categoria == "utility"


def test_twilio_error_al_listar_plantillas():
    class Roto:
        content = SimpleNamespace(
            v1=SimpleNamespace(
                content_and_approvals=SimpleNamespace(
                    list=lambda: (_ for _ in ()).throw(_rest(503, None))
                )
            )
        )

    with pytest.raises(ErrorProveedorWhatsApp) as e:
        twilio(Roto()).listar_plantillas()
    assert (e.value.codigo, e.value.transitorio) == ("PROVEEDOR_NO_DISPONIBLE", True)


# ---- Twilio: medios -----------------------------------------------------------------------------
def test_url_media_valida_solo_el_prefijo_de_la_cuenta():
    p = twilio()
    assert p.url_media_valida(URL_MEDIA)
    assert not p.url_media_valida("https://api.twilio.com/2010-04-01/Accounts/ACotra/Messages/MM1")
    assert not p.url_media_valida(
        "http://api.twilio.com/2010-04-01/Accounts/" + SID + "/Messages/x"
    )
    assert not p.url_media_valida("https://evil.com/?https://api.twilio.com/")
    assert not p.url_media_valida(URL_MEDIA.replace("api.twilio.com", "api.twilio.com.evil.com"))


def test_m7_basic_auth_a_twilio_y_no_en_la_redireccion_al_cdn():
    vistas: list[httpx.Request] = []

    def manejador(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        if req.url.host == "api.twilio.com":
            return httpx.Response(307, headers={"Location": "https://media.twiliocdn.com/ME1"})
        return httpx.Response(200, content=b"\x89PNGdatos", headers={"content-type": "image/png"})

    p = twilio(transporte=httpx.MockTransport(manejador))
    tipo, datos = p.descargar_media(URL_MEDIA, 1000)
    assert (tipo, datos) == ("image/png", b"\x89PNGdatos")
    assert vistas[0].headers["authorization"].startswith("Basic ")
    assert "authorization" not in vistas[1].headers and vistas[1].url.host == "media.twiliocdn.com"


def test_descarga_aborta_al_superar_el_limite_de_bytes():
    def manejador(req):
        return httpx.Response(200, content=b"x" * 5000, headers={"content-type": "image/png"})

    with pytest.raises(ErrorProveedorWhatsApp) as e:
        twilio(transporte=httpx.MockTransport(manejador)).descargar_media(URL_MEDIA, 1000)
    assert e.value.codigo == "MEDIA_DEMASIADO_GRANDE"


def test_descarga_aborta_en_streaming_sin_content_length():
    def contenido():
        yield b"x" * 600
        yield b"x" * 600
        raise AssertionError("no debió seguir leyendo")

    def manejador(req):
        return httpx.Response(200, content=contenido(), headers={"content-type": "image/png"})

    with pytest.raises(ErrorProveedorWhatsApp) as e:
        twilio(transporte=httpx.MockTransport(manejador)).descargar_media(URL_MEDIA, 1000)
    assert e.value.codigo == "MEDIA_DEMASIADO_GRANDE"


@pytest.mark.parametrize(
    ("estado", "codigo", "transitorio"),
    [
        (404, "MEDIA_NO_DISPONIBLE", False),
        (410, "MEDIA_NO_DISPONIBLE", False),
        (500, "PROVEEDOR_NO_DISPONIBLE", True),
        (503, "PROVEEDOR_NO_DISPONIBLE", True),
        (401, "PROVEEDOR_NO_DISPONIBLE", False),
    ],
)
def test_descarga_mapea_estados_http(estado, codigo, transitorio):
    p = twilio(transporte=httpx.MockTransport(lambda req: httpx.Response(estado)))
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        p.descargar_media(URL_MEDIA, 1000)
    assert (e.value.codigo, e.value.transitorio) == (codigo, transitorio)


def test_descarga_timeout_es_transitorio():
    def manejador(req):
        raise httpx.ConnectTimeout("lento")

    with pytest.raises(ErrorProveedorWhatsApp) as e:
        twilio(transporte=httpx.MockTransport(manejador)).descargar_media(URL_MEDIA, 1000)
    assert (e.value.codigo, e.value.transitorio) == ("PROVEEDOR_NO_DISPONIBLE", True)


def test_descarga_rechaza_urls_ajenas_sin_hacer_peticiones():
    def manejador(req):
        raise AssertionError("no debió llamar a la red")

    with pytest.raises(ErrorProveedorWhatsApp) as e:
        twilio(transporte=httpx.MockTransport(manejador)).descargar_media(
            "https://evil.com/x", 1000
        )
    assert e.value.codigo == "MEDIA_NO_DISPONIBLE"


def test_validar_firma_usa_el_token_compartido():
    from app.integraciones.twilio_firma import firma_twilio

    p = twilio()
    firma = firma_twilio("https://x.co/ruta", {"a": "1"}, "tok")
    assert p.validar_firma("https://x.co/ruta", {"a": "1"}, firma)
    assert not p.validar_firma("https://x.co/ruta", {"a": "2"}, firma)
    assert not p.validar_firma("https://x.co/ruta", {"a": "1"}, None)
