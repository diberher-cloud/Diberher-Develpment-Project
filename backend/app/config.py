"""Configuración de la aplicación (variables de entorno, ver .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "0.1.0"


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

    @model_validator(mode="after")
    def _validar_secreto(self) -> "Settings":
        if self.entorno != "test" and len(self.jwt_secreto) < 32:
            raise ValueError("JWT_SECRETO debe tener al menos 32 caracteres.")
        if self.entorno == "test" and not self.jwt_secreto:
            self.jwt_secreto = "secreto-solo-para-tests-0123456789abcdef"
        return self

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
