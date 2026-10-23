"""Proveedor de telefonía falso: sin red ni credenciales."""

import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.integraciones import twilio_firma
from app.integraciones.telefonia.proveedor import TokenAcceso


class ProveedorTelefoniaFalso:
    nombre: Literal["twilio", "falso"] = "falso"

    def __init__(self, auth_token: str) -> None:
        self._auth_token = auth_token
        self.colgadas: list[str] = []

    def emitir_token(self, identity: str, ttl_segundos: int) -> TokenAcceso:
        return TokenAcceso(
            proveedor="falso",
            token=f"falso.{identity}.{secrets.token_hex(8)}",
            identity=identity,
            expira_en=datetime.now(UTC) + timedelta(seconds=ttl_segundos),
        )

    def colgar(self, call_sid: str) -> None:
        self.colgadas.append(call_sid)

    def validar_firma(self, url: str, params: Mapping[str, str], firma: str | None) -> bool:
        return twilio_firma.validar_firma(url, params, firma, self._auth_token)
