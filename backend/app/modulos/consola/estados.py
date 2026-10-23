"""Máquina de estados del agente: transiciones manuales válidas (§4.3). Módulo puro."""

from typing import Literal

DESTINOS_MANUALES = ("disponible", "pausa", "desconectado")
Transicion = Literal["cambia", "igual"]


class ErrorTransicion(Exception):
    def __init__(self, status: int, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje


def resolver_transicion(
    actual: str, motivo_actual: str | None, destino: str, motivo: str | None
) -> Transicion:
    """`cambia` si la transición manual es válida, `igual` si es la identidad (sin efectos);
    lanza `ErrorTransicion` si no está permitida."""
    if actual == "en_llamada":
        raise ErrorTransicion(409, "AGENTE_EN_LLAMADA", "El agente está en una llamada.")
    if actual == "tipificando":
        raise ErrorTransicion(
            409, "TIPIFICACION_PENDIENTE", "Debe tipificar la llamada anterior primero."
        )
    if destino not in DESTINOS_MANUALES:
        raise ErrorTransicion(
            409, "TRANSICION_ESTADO_INVALIDA", f"No se puede pasar a '{destino}' manualmente."
        )
    if actual == destino and (destino != "pausa" or motivo_actual == motivo):
        return "igual"
    return "cambia"
