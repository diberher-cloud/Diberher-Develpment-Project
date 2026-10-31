"""Dueño de la conversación y transiciones permitidas (fase-2b.md §3.3). Módulo PURO."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class SinAsignar:
    pass


@dataclass(frozen=True)
class Humano:
    usuario_id: int


@dataclass(frozen=True)
class IA:
    pass


Dueno = SinAsignar | Humano | IA
NombreDueno = Literal["sin_asignar", "humano", "ia"]


class ErrorTransicionDueno(Exception):
    pass


class ConDueno(Protocol):
    atendida_por: str
    usuario_asignado_id: int | None


def nombre(dueno: Dueno) -> NombreDueno:
    if isinstance(dueno, Humano):
        return "humano"
    return "ia" if isinstance(dueno, IA) else "sin_asignar"


def de_conversacion(conv: ConDueno) -> Dueno:
    if conv.atendida_por == "humano" and conv.usuario_asignado_id is not None:
        return Humano(conv.usuario_asignado_id)
    if conv.atendida_por == "ia":
        return IA()
    return SinAsignar()


def validar_transicion(actual: Dueno, nuevo: Dueno) -> None:
    """Toda transición entre dueños distintos está permitida, salvo `IA → IA` y
    `SinAsignar → SinAsignar` (que no son transiciones). `Humano(a) → Humano(b)` es reasignación."""
    if actual == nuevo:
        raise ErrorTransicionDueno("El dueño no cambia.")


def decidir_dueno_inicial(
    conv: object,
    campana: object | None,
    abre_agente_id: int | None = None,
    ia_disponible: bool = False,
) -> Dueno:
    """Dueño al abrir una conversación: `Humano` si la abre un agente con una plantilla; `IA` si
    la abre el cliente, hay campaña (registro resuelto) y la IA está disponible para ella (2C);
    si no, `SinAsignar`."""
    if abre_agente_id is not None:
        return Humano(abre_agente_id)
    if campana is not None and ia_disponible:
        return IA()
    return SinAsignar()
