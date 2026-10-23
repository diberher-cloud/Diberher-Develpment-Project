"""Selección del proveedor de telefonía según `TELEFONIA_PROVEEDOR`."""

from app.config import get_settings
from app.integraciones.telefonia.falso import ProveedorTelefoniaFalso
from app.integraciones.telefonia.proveedor import ProveedorTelefonia
from app.integraciones.telefonia.twilio import ProveedorTwilio

_instancia: ProveedorTelefonia | None = None


def obtener_proveedor() -> ProveedorTelefonia:
    global _instancia
    if _instancia is None:
        settings = get_settings()
        if settings.telefonia_proveedor == "twilio":
            _instancia = ProveedorTwilio(settings)
        else:
            _instancia = ProveedorTelefoniaFalso(settings.twilio_auth_token)
    return _instancia


def reiniciar_proveedor() -> None:
    """Descarta la instancia en caché (tests y recarga de configuración)."""
    global _instancia
    _instancia = None
