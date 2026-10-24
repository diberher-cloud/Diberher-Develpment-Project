"""Configuración de la aplicación (variables de entorno, ver .env.example)."""

import re
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.0"
SECRETO_EJEMPLO = "cambia-esto-por-un-secreto-de-32-caracteres-o-mas"
TOKEN_TWILIO_EJEMPLO = "token-falso-solo-desarrollo"
_E164 = re.compile(r"\+[1-9]\d{7,14}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    entorno: Literal["desarrollo", "test", "produccion"] = "desarrollo"
    database_url: str = "sqlite:///./outbound.db"
    jwt_secreto: str = ""
    jwt_expiracion_minutos: int = 480
    bcrypt_coste: int = 12
    cors_origenes: str = "http://localhost:5173"
    importacion_max_bytes: int = 10 * 1024 * 1024
    importacion_max_filas: int = 50_000
    exclusiones_max_filas: int = 200_000
    admin_password: str | None = None

    # Empresa y telefonía (Fase 2A)
    empresa_nombre: str = "Mi Empresa S.A.S."
    telefonia_proveedor: Literal["falso", "twilio"] = "falso"
    public_base_url: str = "http://localhost:8000"
    twilio_account_sid: str = ""
    twilio_auth_token: str = TOKEN_TWILIO_EJEMPLO
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_twiml_app_sid: str = ""
    twilio_numero_saliente: str = ""
    telefonia_token_ttl_segundos: int = 3600
    telefonia_grabar: bool = True
    telefonia_aviso_grabacion: str = (
        "Le informamos que esta llamada será grabada y monitoreada "
        "con fines de calidad y seguridad."
    )
    telefonia_idioma_voz: str = "es-MX"
    telefonia_mensaje_bloqueo: str = "No es posible realizar la llamada en este momento."

    # Consola del agente
    consola_reserva_minutos: int = 15
    consola_desconexion_segundos: int = 60
    promesa_max_dias: int = 60

    # Importación Excel y tiempo real
    importacion_max_bytes_descomprimido: int = 100 * 1024 * 1024
    ws_revalidar_segundos: float = 60
    bus_eventos: Literal["auto", "memoria", "postgres"] = "auto"

    @model_validator(mode="after")
    def _validar_secreto(self) -> "Settings":
        if self.entorno != "test" and len(self.jwt_secreto) < 32:
            raise ValueError("JWT_SECRETO debe tener al menos 32 caracteres.")
        if self.entorno == "produccion" and self.jwt_secreto == SECRETO_EJEMPLO:
            raise ValueError("JWT_SECRETO no puede ser el valor de ejemplo de .env.example.")
        if self.entorno == "test" and not self.jwt_secreto:
            self.jwt_secreto = "secreto-solo-para-tests-0123456789abcdef"
        self._validar_telefonia()
        return self

    def _validar_telefonia(self) -> None:
        if self.public_base_url.endswith("/"):
            raise ValueError("PUBLIC_BASE_URL no debe terminar en barra.")
        if self.telefonia_proveedor == "twilio":
            faltan = [
                nombre.upper()
                for nombre in (
                    "twilio_account_sid",
                    "twilio_auth_token",
                    "twilio_api_key_sid",
                    "twilio_api_key_secret",
                    "twilio_twiml_app_sid",
                    "twilio_numero_saliente",
                )
                if not getattr(self, nombre)
            ]
            if faltan:
                raise ValueError("TELEFONIA_PROVEEDOR=twilio exige: " + ", ".join(faltan) + ".")
            if not _E164.fullmatch(self.twilio_numero_saliente):
                raise ValueError("TWILIO_NUMERO_SALIENTE debe estar en formato E.164 (+57...).")
            if self.entorno != "test" and not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL debe usar https:// con el proveedor twilio.")
        if self.entorno not in ("test", "desarrollo"):
            # También con el proveedor falso: la firma de los webhooks usa este token.
            if not self.twilio_auth_token or self.twilio_auth_token == TOKEN_TWILIO_EJEMPLO:
                raise ValueError(
                    "TWILIO_AUTH_TOKEN no puede estar vacío ni ser el valor de ejemplo."
                )
        if self.entorno == "produccion":
            if not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL debe usar https:// en producción.")

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
