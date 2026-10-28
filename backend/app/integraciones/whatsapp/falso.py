"""Proveedor de WhatsApp falso: memoria del proceso, sin red ni credenciales (solo desarrollo y
tests). Reglas deterministas por destino: termina en `0000` → error permanente `63003`; termina
en `9999` → error transitorio `429`."""

import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.integraciones import twilio_firma
from app.integraciones.whatsapp import parseo
from app.integraciones.whatsapp.proveedor import (
    BotonPlantilla,
    EnvioResultado,
    ErrorProveedorWhatsApp,
    EstadoMensaje,
    MensajeEntrante,
    PlantillaRemota,
)

PREFIJO_MEDIA = "https://media.falso.invalid/"
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a1d9d6c30000000049454e44ae426082"
)
_OGG = b"OggS\x00\x02" + b"\x00" * 20
_PDF = b"%PDF-1.1\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def plantillas_fijas() -> list[PlantillaRemota]:
    return [
        PlantillaRemota(
            "HXfalso0001", "recordatorio_cobranza", "es", "utility", "aprobada", None,
            "Hola {{1}}, le escribimos de {{2}}. ¿Podemos conversar sobre su cuenta?",
            ("1", "2"), (),
        ),
        PlantillaRemota(
            "HXfalso0002", "oferta_venta", "es", "marketing", "aprobada", None,
            "Hola {{1}}, {{2}} tiene una oferta de {{3}} para usted.",
            ("1", "2", "3"),
            (BotonPlantilla("respuesta_rapida", "Darme de baja", "BAJA"),),
        ),
        PlantillaRemota(
            "HXfalso0003", "seguimiento", "es", "utility", "pendiente", None,
            "Hola {{1}}, ¿pudo revisar nuestro mensaje?", ("1",), (),
        ),
        PlantillaRemota(
            "HXfalso0004", "marketing_sin_baja", "es", "marketing", "aprobada", None,
            "Hola {{1}}, conozca nuestras novedades.", ("1",), (),
        ),
    ]  # fmt: skip


class ProveedorWhatsAppFalso:
    nombre: Literal["twilio", "falso"] = "falso"

    def __init__(self, auth_token: str) -> None:
        self._auth_token = auth_token
        self.reiniciar()

    def reiniciar(self) -> None:
        self.enviados: list[dict[str, Any]] = []
        self.plantillas: list[PlantillaRemota] = plantillas_fijas()
        self.fallo_listado: ErrorProveedorWhatsApp | None = None

    # ---- envío ---------------------------------------------------------------------------
    def _registrar(self, registro: dict[str, Any]) -> EnvioResultado:
        destino = registro["destino"]
        if destino.endswith("0000"):
            raise ErrorProveedorWhatsApp("63003", transitorio=False)
        if destino.endswith("9999"):
            raise ErrorProveedorWhatsApp("429", transitorio=True)
        self.enviados.append(registro)
        return EnvioResultado("SMfalso" + secrets.token_hex(16), "queued")

    def enviar_texto(
        self, *, origen: str, destino: str, texto: str, url_estado: str
    ) -> EnvioResultado:
        return self._registrar({"tipo": "texto", "destino": destino, "texto": texto})

    def enviar_plantilla(
        self,
        *,
        origen: str,
        destino: str,
        plantilla_ref: str,
        variables: dict[str, str],
        url_estado: str,
    ) -> EnvioResultado:
        return self._registrar(
            {
                "tipo": "plantilla",
                "destino": destino,
                "plantilla_ref": plantilla_ref,
                "variables": dict(variables),
            }
        )

    def listar_plantillas(self) -> list[PlantillaRemota]:
        if self.fallo_listado is not None:
            raise self.fallo_listado
        return list(self.plantillas)

    # ---- webhooks --------------------------------------------------------------------------
    def validar_firma(
        self, url: str, params: Mapping[str, str | Sequence[str]], firma: str | None
    ) -> bool:
        return twilio_firma.validar_firma(url, params, firma, self._auth_token)

    def parsear_entrante(self, params: Mapping[str, str]) -> MensajeEntrante | None:
        return parseo.parsear_entrante(params)

    def parsear_estado(self, params: Mapping[str, str]) -> EstadoMensaje | None:
        return parseo.parsear_estado(params)

    # ---- medios ----------------------------------------------------------------------------
    def url_media_valida(self, url: str) -> bool:
        return url.startswith(PREFIJO_MEDIA)

    def descargar_media(self, url: str, max_bytes: int) -> tuple[str, bytes]:
        if not self.url_media_valida(url):
            raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False)
        if "/grande/" in url:
            raise ErrorProveedorWhatsApp("MEDIA_DEMASIADO_GRANDE", transitorio=False)
        partes = url.rstrip("/").split("/")
        tipo = "/".join(partes[-2:]).lower() if len(partes) >= 2 else ""
        if tipo.startswith("image/"):
            contenido = _PNG
        elif tipo.startswith("audio/"):
            contenido = _OGG
        elif tipo == "application/pdf":
            contenido = _PDF
        else:
            raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False)
        if len(contenido) > max_bytes:
            raise ErrorProveedorWhatsApp("MEDIA_DEMASIADO_GRANDE", transitorio=False)
        return tipo, contenido
