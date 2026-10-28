"""Correcciones de la iteración 1 de QA: texto hostil (H5), redirecciones (H1) y URLs (H2/H3),
y opt-out de voz."""

import json

import httpx
import pytest
from escenario import cab
from sqlalchemy import select
from wa import (
    RUTA_ENTRANTE,
    autorizar,
    clave,
    contexto,
    crear_conv,
    entrante,
    params_entrante,
)

from app.config import Settings
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.exclusiones.modelos import Exclusion
from app.saneamiento import es_hostil, limpiar
from app.trabajos.modelos import Trabajo

API = "/api/v1"
SID = "AC" + "1" * 32
BASE = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages/MM1/Media/ME1"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def test_limpiar_y_es_hostil():
    assert es_hostil("a\x00b") and es_hostil("a\ud800b") and not es_hostil("ñandú 😀")
    assert limpiar("a\x00b\ud800c") == "ab�c"
    assert limpiar("normal") == "normal"


@pytest.mark.parametrize("hostil", ["a\x00b", "a\ud800b"])
def test_h5_texto_del_agente_hostil_422_en_el_campo(client, db, ctx, reloj, hostil):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    cuerpo = json.dumps(
        {"texto": hostil, "idempotencia_clave": clave()}
    )  # \u0000 / \ud800 escapados
    r = client.post(
        f"{API}/conversaciones/{conv.id}/mensajes",
        content=cuerpo,
        headers={**cab(ctx.agente), "Content-Type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert r.json()["error"]["detalles"][0]["campo"] == "texto"
    assert db.scalar(select(Mensaje.id)) is None


def test_h5_otros_campos_libres_y_query(client, h_admin, h_supervisor):
    r = client.post(
        f"{API}/autorizaciones",
        json={"telefono": "3001234567", "finalidad": "venta", "evidencia": "malo\x00 aquí"},
        headers=h_supervisor,
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "evidencia"
    r = client.post(
        f"{API}/campanas", json={"nombre": "Camp\x00X", "tipo": "venta"}, headers=h_admin
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "nombre"
    r = client.post(
        f"{API}/campanas",
        content='{"nombre": "Campaña ok", "tipo": "venta", "guion": "hola \\ud800"}',
        headers={**h_admin, "Content-Type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "guion"
    r = client.get(f"{API}/campanas?q=a%00b", headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "q"
    r = client.post(
        f"{API}/exclusiones",
        json={
            "telefono": "3001234567",
            "motivo": "manual",
            "aplica_a": "todas",
            "observacion": "x\x00",
        },
        headers=h_admin,
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "observacion"


def test_h5_observacion_de_la_tipificacion_anidada(client, db, ctx, reloj):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.post(
        f"{API}/conversaciones/{conv.id}/cerrar",
        json={"tipificacion": {"resultado": "contactado", "observacion": "x\x00y"}},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == "tipificacion.observacion"


def test_h5_el_webhook_saneado_nunca_da_500_y_se_procesa(
    client, firmar_twilio, correr_trabajos, db, ctx
):
    p = params_entrante(texto="hola\x00mundo", ProfileName="Mar\x00ía", ButtonText="b\x00")
    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p))
    assert r.status_code == 200
    correr_trabajos()
    db.expire_all()
    m = db.scalar(select(Mensaje))
    assert m.cuerpo == "holamundo" and m.conversacion_id is not None
    assert db.scalar(select(Conversacion)).nombre_perfil == "María"
    assert [t.estado for t in db.scalars(select(Trabajo)) if t.estado == "fallido"] == []


def test_h5_parseo_sanea_surrogates_sueltos():
    from app.integraciones.whatsapp import parseo

    m = parseo.parsear_entrante(params_entrante(texto="a\ud800b", ProfileName="x\ud800"))
    assert m.texto == "a\ufffdb" and m.nombre_perfil == "x\ufffd"


# ---- Opt-out de voz ----------------------------------------------------------------------------
def test_no_me_llamen_crea_exclusion_de_voz_sin_cerrar_whatsapp(
    client, firmar_twilio, correr_trabajos, db, ctx
):
    autorizar(db)
    entrante(client, firmar_twilio, texto="No me llamen más")
    correr_trabajos()
    db.expire_all()
    e = db.scalar(select(Exclusion))
    assert (e.canal, e.aplica_a, e.motivo, e.origen) == (
        "voz",
        "todas",
        "solicitud_titular",
        "sistema",
    )
    conv = db.scalar(select(Conversacion))
    assert conv.estado == "abierta" and conv.atendida_por == "sin_asignar"
    from app.modulos.whatsapp.modelos import AutorizacionCanal

    assert (
        db.scalar(select(AutorizacionCanal)).clave_vigente is not None
    )  # WhatsApp sigue autorizado
    entrante(client, firmar_twilio, texto="no me llamen")  # no duplica
    correr_trabajos()
    assert len(db.scalars(select(Exclusion)).all()) == 1


def test_frases_nuevas_de_opt_out_por_el_webhook(client, firmar_twilio, correr_trabajos, db, ctx):
    autorizar(db)
    entrante(client, firmar_twilio, texto="¿me pueden dar de baja?")
    correr_trabajos()
    db.expire_all()
    assert db.scalar(select(Exclusion)).canal == "whatsapp"
    assert db.scalar(select(Conversacion)).motivo_cierre == "opt_out"


# ---- Redirecciones y URLs de medios --------------------------------------------------------------
def prov(manejador):
    s = Settings(
        _env_file=None, entorno="test", whatsapp_proveedor="twilio", twilio_account_sid=SID,
        twilio_auth_token="t", twilio_api_key_sid="SK1", twilio_api_key_secret="s",
        public_base_url="https://x.co",
    )  # fmt: skip
    return ProveedorWhatsAppTwilio(s, transporte_http=httpx.MockTransport(manejador))


def redirige(destinos):
    vistas: list[httpx.Request] = []

    def manejador(req):
        vistas.append(req)
        if destinos and req.url.host in ("api.twilio.com", "media.twiliocdn.com"):
            return httpx.Response(302, headers={"location": destinos.pop(0)})
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    return manejador, vistas


@pytest.mark.parametrize(
    "destino",
    [
        "http://media.twiliocdn.com/x",  # no https
        "https://evil.example/x",
        "https://media.twiliocdn.com.evil.example/x",
        "https://user:pw@media.twiliocdn.com/x",
        "https://media.twiliocdn.com:8443/x",
        "https://api.twilio.com/2010-04-01/Accounts/ACotra/Messages/MM1",
        "https://169.254.169.254/",
        "file:///etc/passwd",
    ],
)
def test_h1_destinos_de_redireccion_no_permitidos(destino):
    manejador, vistas = redirige([destino])
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        prov(manejador).descargar_media(BASE, 1000)
    assert e.value.codigo == "MEDIA_NO_DISPONIBLE"
    assert [str(v.url.host) for v in vistas] == ["api.twilio.com"]


def test_h1_cdn_permitido_sin_credenciales_y_maximo_de_saltos():
    manejador, vistas = redirige(["https://media.twiliocdn.com/ME1"])
    tipo, datos = prov(manejador).descargar_media(BASE, 1000)
    assert (tipo, datos) == ("image/png", b"\x89PNG")
    assert "authorization" in vistas[0].headers and "authorization" not in vistas[1].headers
    # Demasiados saltos (3 redirecciones seguidas).
    manejador, vistas = redirige(["https://media.twiliocdn.com/a"] * 5)
    with pytest.raises(ErrorProveedorWhatsApp):
        prov(manejador).descargar_media(BASE, 1000)
    assert len(vistas) == 3


@pytest.mark.parametrize(
    "url",
    [
        BASE + "/../../Calls.json",
        BASE.replace("MM1/Media/ME1", "MM1/%2e%2e/Calls"),
        BASE.replace("MM1/Media/ME1", "MM1/./Media/ME1"),
        BASE + "?x=1",
        BASE + "#f",
        BASE + "\r\nX: 1",
        BASE + "\x00",
        BASE + " ",
        BASE.replace("Messages/MM1", "Messages/XX1"),
        BASE.replace("/Media/ME1", "/Media/XX1"),
        BASE + "/extra",
        BASE.replace("api.twilio.com", "api.twilio.com:443"),
        BASE.replace("https://", "https://x@"),
        BASE.replace("/Messages/", "\\Messages\\"),
    ],
)
def test_h2_h3_urls_no_validas(url):
    p = prov(lambda req: pytest.fail("no debe haber petición"))
    assert p.url_media_valida(url) is False
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        p.descargar_media(url, 1000)
    assert e.value.codigo == "MEDIA_NO_DISPONIBLE"


def test_urls_validas():
    p = prov(lambda req: None)
    assert p.url_media_valida(BASE) and p.url_media_valida(BASE.rsplit("/Media", 1)[0])
