"""Registro de manejadores de trabajos (ADR-0013 §4). Los manejadores se cargan de forma
diferida (`cargar_manejadores`) para evitar importaciones circulares con los servicios que
encolan trabajos."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session


class ErrorTrabajo(Exception):
    """Fallo controlado de un manejador. `codigo` no debe contener datos personales."""

    def __init__(self, codigo: str, transitorio: bool) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.transitorio = transitorio


class ReprogramarTrabajo(Exception):
    """El manejador pide ejecutarse más tarde sin contar el intento (p. ej. mensaje retenido)."""

    def __init__(self, disponible_desde: datetime) -> None:
        super().__init__("reprogramar")
        self.disponible_desde = disponible_desde


Manejador = Callable[[Session, dict[str, Any], datetime], None]
# Se invoca cuando el trabajo pasa a `fallido` (p. ej. el envío agota sus intentos).
AlAgotar = Callable[[Session, dict[str, Any], str, datetime], None]

MANEJADORES: dict[str, Manejador] = {}
AL_AGOTAR: dict[str, AlAgotar] = {}


def cargar_manejadores() -> None:
    """Puebla `MANEJADORES` (idempotente)."""
    if "whatsapp.enviar_mensaje" in MANEJADORES:
        return
    from app.modulos.conversaciones import cierre_inactivas
    from app.modulos.whatsapp import servicio_entrante, servicio_envio
    from app.trabajos import mantenimiento

    MANEJADORES["whatsapp.procesar_entrante"] = servicio_entrante.procesar_entrante
    MANEJADORES["whatsapp.enviar_mensaje"] = servicio_envio.ejecutar_envio
    MANEJADORES["conversaciones.cerrar_inactivas"] = cierre_inactivas.cerrar_inactivas
    MANEJADORES["trabajos.purgar"] = mantenimiento.purgar
    AL_AGOTAR["whatsapp.enviar_mensaje"] = servicio_envio.envio_agotado
