"""Categorías de medios entrantes y cabeceras del proxy. Módulo PURO."""

from app.integraciones.whatsapp.proveedor import CategoriaMedia

_IMAGEN = ("image/jpeg", "image/png", "image/webp")
_AUDIO = ("audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr")
_DOCUMENTO = ("application/pdf",)


def categoria(tipo_contenido: str) -> CategoriaMedia:
    tipo = tipo_contenido.split(";", 1)[0].strip().lower()
    if tipo in _IMAGEN:
        return "imagen"
    if tipo in _AUDIO:
        return "audio"
    if tipo in _DOCUMENTO:
        return "documento"
    return "no_soportado"


def cabeceras_respuesta(
    cat: CategoriaMedia, tipo_contenido: str, mensaje_id: int, indice: int
) -> dict[str, str]:
    disposicion = (
        "inline"
        if cat in ("imagen", "audio")
        else f'attachment; filename="documento-{mensaje_id}-{indice}.pdf"'
    )
    return {
        "Content-Type": tipo_contenido,
        "Content-Disposition": disposicion,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
