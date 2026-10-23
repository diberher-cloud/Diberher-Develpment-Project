"""Interfaz del proveedor de telefonía (ADR-0003, §4.5)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True)
class TokenAcceso:
    proveedor: Literal["twilio", "falso"]
    token: str
    identity: str
    expira_en: datetime


class ProveedorTelefonia(Protocol):
    nombre: Literal["twilio", "falso"]

    def emitir_token(self, identity: str, ttl_segundos: int) -> TokenAcceso: ...

    def colgar(self, call_sid: str) -> None:
        """REST `status=completed` (uso administrativo)."""
        ...

    def validar_firma(self, url: str, params: Mapping[str, str], firma: str | None) -> bool: ...
