"""Ventana de 24 h de WhatsApp y decisión sobre respuestas fuera de franja. Módulo PURO.

`decidir_respuesta` (ADR-0012 §3, ADR-0019 §3) se aplica a mensajes de humano/IA dentro de la
ventana; los mensajes automáticos fijos y las plantillas no pasan por aquí.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento.politica import PoliticaCumplimiento

VENTANA = timedelta(hours=24)


class ConVentana(Protocol):
    ventana_expira_en: datetime | None


def ventana_abierta(conv: ConVentana, ahora: datetime, margen: timedelta) -> bool:
    return conv.ventana_expira_en is not None and ahora < conv.ventana_expira_en - margen


@dataclass(frozen=True)
class Enviar:
    pass


@dataclass(frozen=True)
class Retener:
    programado_para: datetime


@dataclass(frozen=True)
class Rechazar:
    codigo: str
    proxima_franja: datetime | None


Decision = Enviar | Retener | Rechazar


def decidir_respuesta(
    ahora: datetime,
    politicas: Sequence[PoliticaCumplimiento],
    festivos: Mapping[date, str],
    ventana_expira_en: datetime,
    margen: timedelta,
) -> Decision:
    restrictivas = [p for p in politicas if not p.entrantes.responder_fuera_de_franja]
    if not restrictivas:
        return Enviar()
    # Solo horario (sin frecuencia: las respuestas no consumen contactos).
    if all(
        motor.evaluar_contacto(ahora, "whatsapp_mensaje", p, festivos, [], entrante=True).permitido
        for p in restrictivas
    ):
        return Enviar()
    proximas = [motor.proxima_ventana(ahora, p, festivos) for p in restrictivas]
    if any(t is None for t in proximas):
        return Rechazar("RESPUESTA_FUERA_DE_FRANJA", None)
    t = max(t for t in proximas if t is not None)
    if t >= ventana_expira_en - margen:
        return Rechazar("RESPUESTA_FUERA_DE_FRANJA", t)
    return Retener(t)
