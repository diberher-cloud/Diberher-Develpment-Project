"""Webhook entrante de WhatsApp (W1-W7) y procesamiento básico (§4.4-4.5)."""

from sqlalchemy import select
from wa import EMPRESA, NUMERO, RUTA_ENTRANTE, entrante, params_entrante

from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.trabajos.modelos import Trabajo


def test_w1_firma_invalida_o_ausente_403_sin_filas(client, db):
    p = params_entrante()
    r = client.post(RUTA_ENTRANTE, data=p)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "FIRMA_INVALIDA"
    r = client.post(RUTA_ENTRANTE, data=p, headers={"X-Twilio-Signature": "mala"})
    assert r.status_code == 403
    assert db.scalar(select(Mensaje.id)) is None and db.scalar(select(Trabajo.id)) is None


def test_w2_entrante_valido_guarda_mensaje_sin_conversacion_y_encola(client, firmar_twilio, db):
    p = params_entrante(texto="Hola, necesito ayuda", ProfileName="María")
    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert r.text == '<?xml version="1.0" encoding="UTF-8"?><Response/>'
    m = db.scalar(select(Mensaje))
    assert (m.estado, m.direccion, m.autor, m.tipo) == ("recibido", "entrante", "cliente", "texto")
    assert m.conversacion_id is None and m.proveedor_id == p["MessageSid"]
    t = db.scalar(select(Trabajo))
    assert (t.tipo, t.estado, t.clave_unica) == (
        "whatsapp.procesar_entrante",
        "pendiente",
        f"entrante:{m.id}",
    )
    assert t.payload == {"mensaje_id": m.id}  # solo ids: nunca texto ni números


def test_w3_mismo_messagesid_dos_veces_una_fila_y_un_trabajo(client, firmar_twilio, db):
    p = params_entrante()
    for _ in range(2):
        assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
    assert len(db.scalars(select(Mensaje)).all()) == 1
    assert len(db.scalars(select(Trabajo)).all()) == 1


def test_w4_numero_de_empresa_ajeno_se_ignora(client, firmar_twilio, db):
    p = params_entrante()
    p["To"] = "whatsapp:+573009999999"
    assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
    assert db.scalar(select(Mensaje.id)) is None


def test_w5_cuenta_ajena_con_proveedor_twilio(client, firmar_twilio, db, monkeypatch):
    from app.config import get_settings
    from app.integraciones.whatsapp import fabrica
    from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio
    from app.main import app

    s = get_settings()
    monkeypatch.setattr(s, "twilio_account_sid", "ACpropia")
    prov = ProveedorWhatsAppTwilio(s)
    app.dependency_overrides[fabrica.obtener_proveedor_whatsapp] = lambda: prov
    try:
        p = params_entrante(AccountSid="ACajena")
        assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
        assert db.scalar(select(Mensaje.id)) is None
        p = params_entrante(AccountSid="ACpropia")
        assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
        assert db.scalar(select(Mensaje.id)) is not None
    finally:
        app.dependency_overrides.pop(fabrica.obtener_proveedor_whatsapp, None)


def test_w6_from_sin_prefijo_o_no_e164_se_ignora(client, firmar_twilio, db):
    for origen in (NUMERO, "whatsapp:3001234567", "whatsapp:+0123", "sms:+573001234567"):
        p = params_entrante()
        p["From"] = origen
        assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
    p = params_entrante()
    p["MessageSid"] = ""
    assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
    assert db.scalar(select(Mensaje.id)) is None


def test_w7_cuatro_medios_con_categorias_correctas(client, firmar_twilio, db):
    p = params_entrante(texto="Mire", NumMedia="4")
    tipos = ["image/jpeg", "audio/ogg; codecs=opus", "application/pdf", "video/mp4"]
    for i, t in enumerate(tipos):
        p[f"MediaUrl{i}"] = (
            f"https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME{i}"
        )
        p[f"MediaContentType{i}"] = t
    assert client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p)).status_code == 200
    m = db.scalar(select(Mensaje))
    assert m.tipo == "media" and m.cuerpo == "Mire"
    assert [(x["indice"], x["tipo_contenido"], x["categoria"]) for x in m.media] == [
        (0, "image/jpeg", "imagen"),
        (1, "audio/ogg", "audio"),
        (2, "application/pdf", "documento"),
        (3, "video/mp4", "no_soportado"),
    ]
    assert all(x["url_proveedor"].startswith("https://api.twilio.com/") for x in m.media)


def test_tipos_boton_y_no_soportado(client, firmar_twilio, db):
    entrante(client, firmar_twilio, texto="Sí", ButtonPayload="SI", ButtonText="Sí, acepto")
    entrante(client, firmar_twilio, texto=None, Latitude="4.6")
    m1, m2 = db.scalars(select(Mensaje).order_by(Mensaje.id)).all()
    assert (m1.tipo, m1.boton_payload, m1.boton_texto) == ("boton", "SI", "Sí, acepto")
    assert (m2.tipo, m2.cuerpo) == ("no_soportado", None)


def test_el_worker_crea_conversacion_sin_registro_y_la_encola(
    client, firmar_twilio, db, correr_trabajos, h_supervisor, proveedor_whatsapp
):
    entrante(client, firmar_twilio, texto="Hola", ProfileName="María")
    # Entrante + aviso de espera (no hay agentes disponibles).
    assert correr_trabajos() == 2
    assert [e["tipo"] for e in proveedor_whatsapp.enviados] == ["texto"]
    db.expire_all()
    conv = db.scalar(select(Conversacion))
    assert (conv.estado, conv.atendida_por, conv.iniciada_por) == (
        "abierta",
        "sin_asignar",
        "cliente",
    )
    assert conv.numero_cliente_e164 == NUMERO and conv.numero_empresa_e164 == EMPRESA
    assert conv.campana_id is None and conv.nombre_perfil == "María" and conv.mensajes_sin_leer == 1
    assert conv.ventana_expira_en is not None and conv.clave_abierta == f"{NUMERO}|{EMPRESA}"
    m = db.scalar(select(Mensaje))
    assert m.conversacion_id == conv.id and m.procesado_en is not None and m.variables is None
    fila = db.scalar(select(ColaAtencion))
    assert (fila.motivo, fila.estado, fila.prioridad, fila.campana_id) == (
        "sin_campana",
        "pendiente",
        2,
        None,
    )
    r = client.get("/api/v1/atencion/cola", headers=h_supervisor)
    assert r.status_code == 200 and r.json()[0]["conversacion_id"] == conv.id
    assert r.json()[0]["numero_mascara"] == "+57300****567"
