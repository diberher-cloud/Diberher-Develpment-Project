"""Medios entrantes por proxy autenticado, sin almacenar el binario (fase-2b.md §4.11)."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.modelos import Mensaje
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import medios

logger = logging.getLogger("app")


@dataclass
class MedioDescargado:
    contenido: bytes
    cabeceras: dict[str, str]


def _no_disponible() -> ErrorApp:
    return ErrorApp(404, "MEDIA_NO_DISPONIBLE", "El adjunto no está disponible.")


def descargar(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    mensaje_id: int,
    indice: int,
    ahora: datetime,
) -> MedioDescargado:
    conv = conversaciones.cargar(db, conversacion_id)
    conversaciones.exigir_acceso(conv, usuario)
    mensaje = db.scalar(
        select(Mensaje).where(Mensaje.id == mensaje_id, Mensaje.conversacion_id == conv.id)
    )
    if mensaje is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Mensaje no encontrado.")
    item = next((x for x in (mensaje.media or []) if x.get("indice") == indice), None)
    if item is None or item.get("categoria") == "no_soportado":
        raise _no_disponible()
    proveedor = obtener_proveedor_whatsapp()
    url = item.get("url_proveedor", "")
    if not proveedor.url_media_valida(url):
        logger.warning("whatsapp.media_url_invalida mensaje=%s", mensaje.id)
        raise _no_disponible()
    try:
        tipo, contenido = proveedor.descargar_media(url, get_settings().whatsapp_media_max_bytes)
    except ErrorProveedorWhatsApp as exc:
        if exc.codigo == "MEDIA_DEMASIADO_GRANDE":
            raise ErrorApp(
                413, "MEDIA_DEMASIADO_GRANDE", "El adjunto supera el tamaño máximo."
            ) from None
        if exc.codigo == "MEDIA_NO_DISPONIBLE":
            raise _no_disponible() from None
        raise ErrorApp(
            502, "PROVEEDOR_NO_DISPONIBLE", "No se pudo obtener el adjunto del proveedor."
        ) from None
    categoria = item["categoria"]
    if medios.categoria(tipo) != categoria:
        raise _no_disponible()
    auditoria.registrar(
        db,
        "whatsapp.media_ver",
        usuario.id,
        "mensaje",
        mensaje.id,
        {"conversacion_id": conv.id, "mensaje_id": mensaje.id, "indice": indice},
    )
    db.commit()
    return MedioDescargado(
        contenido,
        medios.cabeceras_respuesta(categoria, item["tipo_contenido"], mensaje.id, indice),
    )
