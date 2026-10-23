"""Proveedor Twilio: AccessToken con VoiceGrant (SDK) y REST para colgar."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.config import Settings
from app.integraciones import twilio_firma
from app.integraciones.telefonia.proveedor import TokenAcceso


class ProveedorTwilio:
    nombre: Literal["twilio", "falso"] = "twilio"

    def __init__(self, settings: Settings, cliente_rest: Callable[[], Any] | None = None) -> None:
        self._s = settings
        self._cliente_rest = cliente_rest

    def emitir_token(self, identity: str, ttl_segundos: int) -> TokenAcceso:
        from twilio.jwt.access_token import AccessToken
        from twilio.jwt.access_token.grants import VoiceGrant

        token = AccessToken(
            self._s.twilio_account_sid,
            self._s.twilio_api_key_sid,
            self._s.twilio_api_key_secret,
            identity=identity,
            ttl=ttl_segundos,
        )
        token.add_grant(
            VoiceGrant(outgoing_application_sid=self._s.twilio_twiml_app_sid, incoming_allow=False)
        )
        jwt = token.to_jwt()
        return TokenAcceso(
            proveedor="twilio",
            token=jwt if isinstance(jwt, str) else jwt.decode(),
            identity=identity,
            expira_en=datetime.now(UTC) + timedelta(seconds=ttl_segundos),
        )

    def colgar(self, call_sid: str) -> None:
        if self._cliente_rest is not None:
            cliente = self._cliente_rest()
        else:
            from twilio.rest import Client

            cliente = Client(
                self._s.twilio_api_key_sid,
                self._s.twilio_api_key_secret,
                self._s.twilio_account_sid,
            )
        cliente.calls(call_sid).update(status="completed")

    def validar_firma(self, url: str, params: Mapping[str, str], firma: str | None) -> bool:
        return twilio_firma.validar_firma(url, params, firma, self._s.twilio_auth_token)
