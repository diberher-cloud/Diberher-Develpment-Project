"""Simulación de WhatsApp para desarrollo sin credenciales (proveedor falso, no producción).

Ejecuta los MISMOS servicios que los webhooks de Twilio. Si no se cumple la condición, el router
no se registra (404)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencias import usuario_actual
from app.errores import ErrorApp, detalle
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.integraciones.whatsapp.falso import PREFIJO_MEDIA
from app.integraciones.whatsapp.proveedor import ProveedorWhatsApp
from app.modulos.conversaciones.modelos import Mensaje
from app.modulos.importacion.telefonos import ErrorTelefono, normalizar_telefono
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_entrante, servicio_estado
from app.modulos.whatsapp.esquemas import (
    SimulacionEntrante,
    SimulacionEntranteSalida,
    SimulacionEstado,
)
from app.paginacion import IdRuta
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/whatsapp/simulacion", tags=["whatsapp (simulación)"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]
Proveedor = Annotated[ProveedorWhatsApp, Depends(obtener_proveedor_whatsapp)]


@router.post("/entrante", response_model=SimulacionEntranteSalida)
def simular_entrante(
    datos: SimulacionEntrante, _usuario: Cualquiera, db: Db, reloj: RelojDep, proveedor: Proveedor
) -> SimulacionEntranteSalida:
    try:
        numero = normalizar_telefono(datos.numero).numero_e164
    except ErrorTelefono as exc:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("numero", f"{exc.codigo}: {exc.mensaje}")],
        ) from exc
    sid = "SMsim" + uuid.uuid4().hex
    params = {
        "MessageSid": sid,
        "From": f"whatsapp:{numero}",
        "To": f"whatsapp:{get_settings().whatsapp_numero_empresa}",
        "Body": datos.texto or "",
        "NumMedia": str(len(datos.media)),
    }
    if datos.nombre_perfil:
        params["ProfileName"] = datos.nombre_perfil
    if datos.boton_payload:
        params["ButtonPayload"] = datos.boton_payload
    if datos.boton_texto:
        params["ButtonText"] = datos.boton_texto
    for i, m in enumerate(datos.media):
        tipo = m.tipo_contenido.strip().lower()
        params[f"MediaUrl{i}"] = f"{PREFIJO_MEDIA}{uuid.uuid4().hex}/{tipo}"
        params[f"MediaContentType{i}"] = tipo
    mensaje = servicio_entrante.recibir(db, proveedor, params, reloj())
    if mensaje is None:
        raise ErrorApp(422, "VALIDACION", "El mensaje simulado no es válido.")
    return SimulacionEntranteSalida(mensaje_id=mensaje.id, proveedor_id=sid)


@router.post("/mensajes/{mensaje_id}/estado", status_code=204)
def simular_estado(
    mensaje_id: IdRuta,
    datos: SimulacionEstado,
    _usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
    proveedor: Proveedor,
) -> Response:
    mensaje = db.scalar(select(Mensaje).where(Mensaje.id == mensaje_id))
    if mensaje is None or not mensaje.proveedor_id:
        raise ErrorApp(404, "NO_ENCONTRADO", "El mensaje no existe o aún no tiene identificador.")
    params = {"MessageSid": mensaje.proveedor_id, "MessageStatus": datos.estado}
    if datos.error_codigo:
        params["ErrorCode"] = datos.error_codigo
    servicio_estado.procesar_webhook(db, proveedor, params, reloj())
    return Response(status_code=204)
