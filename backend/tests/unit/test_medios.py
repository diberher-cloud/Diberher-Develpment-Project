import pytest

from app.modulos.whatsapp import medios


@pytest.mark.parametrize(
    ("tipo", "esperada"),
    [
        ("image/jpeg", "imagen"),
        ("image/png", "imagen"),
        ("image/webp", "imagen"),
        ("audio/ogg", "audio"),
        ("audio/ogg; codecs=opus", "audio"),
        ("AUDIO/MPEG", "audio"),
        ("audio/mp4", "audio"),
        ("audio/aac", "audio"),
        ("audio/amr", "audio"),
        ("application/pdf", "documento"),
        ("video/mp4", "no_soportado"),
        ("image/svg+xml", "no_soportado"),
        ("text/vcard", "no_soportado"),
        ("application/vnd.ms-excel", "no_soportado"),
        ("", "no_soportado"),
    ],
)
def test_categoria(tipo, esperada):
    assert medios.categoria(tipo) == esperada


def test_cabeceras_de_respuesta():
    h = medios.cabeceras_respuesta("imagen", "image/png", 7, 0)
    assert h["Content-Disposition"] == "inline" and h["Content-Type"] == "image/png"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Cache-Control"] == "private, no-store"
    assert h["Content-Security-Policy"] == "sandbox; default-src 'none'"
    d = medios.cabeceras_respuesta("documento", "application/pdf", 7, 2)
    assert d["Content-Disposition"] == 'attachment; filename="documento-7-2.pdf"'
    assert medios.cabeceras_respuesta("audio", "audio/ogg", 1, 0)["Content-Disposition"] == "inline"
