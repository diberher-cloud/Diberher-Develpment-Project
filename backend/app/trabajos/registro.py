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


def clave_unica_de(tipo: str, payload: dict[str, Any]) -> str | None:
    """`clave_unica` original de los trabajos que la usan (se anula al tomarlos)."""
    if tipo == "whatsapp.procesar_entrante" and "mensaje_id" in payload:
        return f"entrante:{payload['mensaje_id']}"
    if tipo == "whatsapp.enviar_mensaje" and "mensaje_id" in payload:
        return f"enviar:{payload['mensaje_id']}"
    if tipo == "ia.turno" and "conversacion_id" in payload:
        return f"turno_ia:{payload['conversacion_id']}"
    if tipo == "ia.traspasar_campana" and "campana_id" in payload:
        cid = payload["campana_id"]
        return f"ia_traspaso:{'global' if cid is None else cid}"
    if tipo in ("conversaciones.cerrar_inactivas", "trabajos.purgar"):
        return f"periodico:{tipo}"
    return None


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
    from app.modulos.agente_ia import trabajos as trabajos_ia

    MANEJADORES["ia.turno"] = trabajos_ia.turno
    MANEJADORES["ia.traspasar_campana"] = trabajos_ia.traspasar_campana
    MANEJADORES["ia.evaluacion"] = trabajos_ia.evaluacion
    AL_AGOTAR["ia.turno"] = trabajos_ia.turno_agotado
