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

    # WhatsApp (Fase 2B)
    whatsapp_proveedor: Literal["falso", "twilio"] = "falso"
    whatsapp_numero_empresa: str = "+573000000001"
    whatsapp_margen_ventana_segundos: int = 60
    whatsapp_media_max_bytes: int = 16 * 1024 * 1024
    whatsapp_dias_resolucion_plantilla: int = 30
    # Hosts a los que se puede seguir una redirección al descargar medios (https, sin credenciales).
    # api.twilio.com siempre está permitido. Separados por comas.
    whatsapp_hosts_medios: str = "media.twiliocdn.com"
    whatsapp_payload_baja: str = "BAJA"
    whatsapp_frases_opt_out: str = ""
    whatsapp_frases_opt_out_todos: str = ""
    whatsapp_mensaje_opt_out: str = (
        "Hemos registrado su solicitud. No le enviaremos más mensajes por WhatsApp."
    )
    whatsapp_mensaje_opt_out_todos: str = (
        "Hemos registrado su solicitud. No volveremos a contactarle por ningún medio."
    )
    whatsapp_mensaje_espera: str = (
        "Gracias por escribirnos. Un asesor le responderá en nuestro horario de atención."
    )
    whatsapp_mensaje_fuera_de_franja: str = (
        "Recibimos su mensaje. Le responderemos dentro de nuestro horario de atención."
    )
    conversacion_inactividad_horas: int = 24
    atencion_max_conversaciones_agente: int = 5

    # Worker (Fase 2B)
    worker_intervalo_segundos: float = 1
    worker_lote: int = 10
    worker_bloqueo_segundos: int = 300
    purga_eventos_huerfanos_dias: int = 7
    whatsapp_media_concurrencia: int = 4
    whatsapp_media_duracion_segundos: int = 30

    @model_validator(mode="after")
    def _validar_secreto(self) -> "Settings":
        if self.entorno != "test" and len(self.jwt_secreto) < 32:
            raise ValueError("JWT_SECRETO debe tener al menos 32 caracteres.")
        if self.entorno == "produccion" and self.jwt_secreto == SECRETO_EJEMPLO:
            raise ValueError("JWT_SECRETO no puede ser el valor de ejemplo de .env.example.")
        if self.entorno == "test" and not self.jwt_secreto:
            self.jwt_secreto = "secreto-solo-para-tests-0123456789abcdef"
        self._validar_telefonia()
        self._validar_whatsapp()
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
    def hosts_medios(self) -> frozenset[str]:
        extra = {h.strip().lower() for h in self.whatsapp_hosts_medios.split(",") if h.strip()}
        return frozenset({"api.twilio.com", *extra})

    def _validar_whatsapp(self) -> None:
        if not _E164.fullmatch(self.whatsapp_numero_empresa):
            raise ValueError("WHATSAPP_NUMERO_EMPRESA debe estar en formato E.164 (+57...).")
        if self.whatsapp_proveedor == "twilio":
            faltan = [
                nombre.upper()
                for nombre in (
                    "twilio_account_sid",
                    "twilio_auth_token",
                    "twilio_api_key_sid",
                    "twilio_api_key_secret",
                    "public_base_url",
                )
                if not getattr(self, nombre)
            ]
            if faltan:
                raise ValueError("WHATSAPP_PROVEEDOR=twilio exige: " + ", ".join(faltan) + ".")
            if self.entorno != "test" and not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL debe usar https:// con el proveedor twilio.")
        rangos = (
            ("WHATSAPP_MARGEN_VENTANA_SEGUNDOS", self.whatsapp_margen_ventana_segundos, 0, 3600),
            ("WHATSAPP_MEDIA_MAX_BYTES", self.whatsapp_media_max_bytes, 1024, 64 * 1024 * 1024),
            ("WHATSAPP_DIAS_RESOLUCION_PLANTILLA", self.whatsapp_dias_resolucion_plantilla, 1, 365),
            ("CONVERSACION_INACTIVIDAD_HORAS", self.conversacion_inactividad_horas, 1, 168),
            ("ATENCION_MAX_CONVERSACIONES_AGENTE", self.atencion_max_conversaciones_agente, 1, 50),
            ("WORKER_INTERVALO_SEGUNDOS", self.worker_intervalo_segundos, 0.1, 60),
            ("WORKER_LOTE", self.worker_lote, 1, 100),
            ("WORKER_BLOQUEO_SEGUNDOS", self.worker_bloqueo_segundos, 30, 3600),
            ("PURGA_EVENTOS_HUERFANOS_DIAS", self.purga_eventos_huerfanos_dias, 1, 365),
            ("WHATSAPP_MEDIA_CONCURRENCIA", self.whatsapp_media_concurrencia, 1, 100),
            ("WHATSAPP_MEDIA_DURACION_SEGUNDOS", self.whatsapp_media_duracion_segundos, 5, 300),
        )
        for nombre, valor, minimo, maximo in rangos:
            if not minimo <= valor <= maximo:
                raise ValueError(f"{nombre} debe estar entre {minimo} y {maximo}.")
        mensajes = (
            ("WHATSAPP_MENSAJE_OPT_OUT", self.whatsapp_mensaje_opt_out),
            ("WHATSAPP_MENSAJE_OPT_OUT_TODOS", self.whatsapp_mensaje_opt_out_todos),
            ("WHATSAPP_MENSAJE_ESPERA", self.whatsapp_mensaje_espera),
            ("WHATSAPP_MENSAJE_FUERA_DE_FRANJA", self.whatsapp_mensaje_fuera_de_franja),
        )
        for nombre, texto in mensajes:
            if len(texto) > 1000:
                raise ValueError(f"{nombre} no puede superar 1000 caracteres.")

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
