"""Selección del proveedor de WhatsApp según `WHATSAPP_PROVEEDOR`."""

from app.config import get_settings
from app.integraciones.whatsapp.falso import ProveedorWhatsAppFalso
from app.integraciones.whatsapp.proveedor import ProveedorWhatsApp
from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio

_instancia: ProveedorWhatsApp | None = None


def obtener_proveedor_whatsapp() -> ProveedorWhatsApp:
    global _instancia
    if _instancia is None:
        settings = get_settings()
        if settings.whatsapp_proveedor == "twilio":
            _instancia = ProveedorWhatsAppTwilio(settings)
        else:
            _instancia = ProveedorWhatsAppFalso(settings.twilio_auth_token)
    return _instancia


def reiniciar_proveedor_whatsapp() -> None:
    """Descarta la instancia en caché (tests y recarga de configuración)."""
    global _instancia
    _instancia = None
