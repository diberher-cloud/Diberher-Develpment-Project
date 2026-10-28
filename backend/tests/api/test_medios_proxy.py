"""Medios entrantes por proxy autenticado (M1-M6, §4.11)."""

import logging

import pytest
from escenario import cab
from sqlalchemy import select
from wa import NUMERO, contexto, crear_conv

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Mensaje

API = "/api/v1/conversaciones"
BASE = "https://media.falso.invalid/abc"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def media_msg(db, conv, reloj, items):
    m = Mensaje(
        conversacion_id=conv.id, numero_cliente_e164=NUMERO, direccion="entrante", autor="cliente",
        tipo="media", cuerpo="foto", estado="recibido", creado_en=reloj(), procesado_en=reloj(),
        media=[
            {"indice": i, "tipo_contenido": t, "categoria": c, "url_proveedor": u}
            for i, (t, c, u) in enumerate(items)
        ],
    )  # fmt: skip
    db.add(m)
    db.commit()
    return m


@pytest.fixture()
def mensaje(db, ctx, reloj):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    m = media_msg(
        db, conv, reloj,
        [
            ("image/png", "imagen", f"{BASE}/image/png"),
            ("application/pdf", "documento", f"{BASE}/application/pdf"),
            ("video/mp4", "no_soportado", f"{BASE}/video/mp4"),
            ("image/png", "imagen", f"{BASE}/grande/image/png"),
            ("image/png", "imagen", "https://evil.example.com/x.png"),
            ("audio/ogg", "audio", f"{BASE}/audio/ogg"),
            ("image/jpeg", "imagen", f"{BASE}/application/pdf"),  # el proveedor entrega otro tipo
        ],
    )  # fmt: skip
    return conv, m


def url(conv, m, i):
    return f"{API}/{conv.id}/mensajes/{m.id}/media/{i}"


def test_m1_imagen_200_con_cabeceras_y_auditoria(client, db, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 0), headers=cab(ctx.agente))
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")
    h = r.headers
    assert h["content-type"] == "image/png" and h["content-disposition"] == "inline"
    assert h["x-content-type-options"] == "nosniff" and h["cache-control"] == "private, no-store"
    assert h["content-security-policy"] == "sandbox; default-src 'none'"
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "whatsapp.media_ver"))
    assert aud.detalle == {"conversacion_id": conv.id, "mensaje_id": m.id, "indice": 0}
    assert aud.usuario_id == ctx.agente.id


def test_audio_en_linea(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 5), headers=cab(ctx.agente))
    assert r.status_code == 200 and r.headers["content-disposition"] == "inline"
    assert r.content.startswith(b"OggS")


def test_m2_pdf_como_adjunto(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 1), headers=cab(ctx.agente))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-disposition"] == f'attachment; filename="documento-{m.id}-1.pdf"'
    assert r.headers["content-type"] == "application/pdf"


def test_m3_no_soportado_404(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 2), headers=cab(ctx.agente))
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "MEDIA_NO_DISPONIBLE"


def test_m4_demasiado_grande_413(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 3), headers=cab(ctx.agente))
    assert r.status_code == 413 and r.json()["error"]["codigo"] == "MEDIA_DEMASIADO_GRANDE"


def test_m5_url_fuera_del_prefijo_404_sin_descarga(
    client, ctx, mensaje, proveedor_whatsapp, monkeypatch, caplog
):
    conv, m = mensaje
    llamadas = []
    monkeypatch.setattr(proveedor_whatsapp, "descargar_media", lambda *a, **k: llamadas.append(a))
    with caplog.at_level(logging.WARNING):
        r = client.get(url(conv, m, 4), headers=cab(ctx.agente))
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "MEDIA_NO_DISPONIBLE"
    assert llamadas == []
    assert any("media_url_invalida" in x.getMessage() for x in caplog.records)
    assert "evil.example.com" not in caplog.text


def test_el_tipo_devuelto_debe_coincidir_con_la_categoria_guardada(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(url(conv, m, 6), headers=cab(ctx.agente))
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "MEDIA_NO_DISPONIBLE"


def test_indice_o_mensaje_inexistente(client, ctx, mensaje, db, reloj):
    conv, m = mensaje
    assert (
        client.get(url(conv, m, 9), headers=cab(ctx.agente)).json()["error"]["codigo"]
        == "MEDIA_NO_DISPONIBLE"
    )
    assert client.get(url(conv, m, 10), headers=cab(ctx.agente)).status_code == 422
    assert (
        client.get(f"{API}/{conv.id}/mensajes/9999/media/0", headers=cab(ctx.agente)).status_code
        == 404
    )
    otra = crear_conv(db, reloj(), numero="+573119998877", dueno=Humano(ctx.agente.id))
    assert (
        client.get(f"{API}/{otra.id}/mensajes/{m.id}/media/0", headers=cab(ctx.agente)).status_code
        == 404
    )


def test_m6_agente_ajeno_403_y_supervisor_ok(client, ctx, mensaje, crear_usuario, h_supervisor):
    conv, m = mensaje
    r = client.get(url(conv, m, 0), headers=cab(crear_usuario("agente")))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"
    assert client.get(url(conv, m, 0), headers=h_supervisor).status_code == 200
    assert client.get(url(conv, m, 0)).status_code == 401


def test_error_transitorio_del_proveedor_502(client, ctx, mensaje, proveedor_whatsapp, monkeypatch):
    from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp

    conv, m = mensaje

    def roto(*a, **k):
        raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", True)

    monkeypatch.setattr(proveedor_whatsapp, "descargar_media", roto)
    r = client.get(url(conv, m, 0), headers=cab(ctx.agente))
    assert r.status_code == 502 and r.json()["error"]["codigo"] == "PROVEEDOR_NO_DISPONIBLE"


def test_media_no_expone_la_url_del_proveedor(client, ctx, mensaje):
    conv, m = mensaje
    r = client.get(f"{API}/{conv.id}/mensajes", headers=cab(ctx.agente))
    texto = r.text
    assert "media.falso.invalid" not in texto and "url_proveedor" not in texto
    item = r.json()["items"][0]["media"]
    assert item[0] == {
        "indice": 0,
        "categoria": "imagen",
        "tipo_contenido": "image/png",
        "disponible": True,
    }
    assert item[2]["disponible"] is False
