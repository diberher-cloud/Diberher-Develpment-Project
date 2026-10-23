"""Endpoints de telefonía: token (JWT) y TwiML/webhooks de Twilio (firma, sin JWT)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencias import requiere_rol
from app.errores import ErrorApp
from app.integraciones.telefonia.fabrica import obtener_proveedor
from app.integraciones.telefonia.proveedor import ProveedorTelefonia
from app.modulos.telefonia import servicio, twiml
from app.modulos.telefonia.esquemas import TokenSalida
from app.modulos.usuarios.modelos import Usuario
from app.reloj import Reloj, get_reloj

logger = logging.getLogger("app")
router = APIRouter(prefix="/telefonia", tags=["telefonía"])
Agente = Annotated[Usuario, Depends(requiere_rol("agente"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]
Proveedor = Annotated[ProveedorTelefonia, Depends(obtener_proveedor)]
XML = "application/xml"


async def validar_peticion_twilio(request: Request, proveedor: Proveedor) -> dict[str, str]:
    """Valida `X-Twilio-Signature` ANTES de cualquier otro procesamiento (ADR-0013 §1).

    URL firmada = PUBLIC_BASE_URL + ruta + query original. Devuelve los parámetros del formulario.
    """
    formulario = await request.form()
    multiples: dict[str, list[str]] = {}
    for clave, valor in formulario.multi_items():
        if isinstance(valor, str):
            multiples.setdefault(clave, []).append(valor)
    consulta = request.url.query
    url = get_settings().public_base_url + request.url.path + (f"?{consulta}" if consulta else "")
    firma = request.headers.get("X-Twilio-Signature")
    firmables = {k: v[0] if len(v) == 1 else v for k, v in multiples.items()}
    if not proveedor.validar_firma(url, firmables, firma):  # type: ignore[arg-type]
        logger.warning("Firma de Twilio inválida en %s", request.url.path)
        raise ErrorApp(403, "FIRMA_INVALIDA", "Firma inválida.")
    return {k: v[0] for k, v in multiples.items()}


Firmado = Annotated[dict[str, str], Depends(validar_peticion_twilio)]


@router.post("/token", response_model=TokenSalida)
def token(usuario: Agente, proveedor: Proveedor) -> TokenSalida:
    emitido = proveedor.emitir_token(
        f"agente_{usuario.id}", get_settings().telefonia_token_ttl_segundos
    )
    return TokenSalida(
        proveedor=emitido.proveedor,
        token=emitido.token,
        identity=emitido.identity,
        expira_en=emitido.expira_en,
    )


@router.post("/twiml/saliente")
def twiml_saliente(params: Firmado, db: Db, reloj: RelojDep, proveedor: Proveedor) -> Response:
    resultado = servicio.procesar_saliente(
        db,
        call_sid=(params.get("CallSid") or "")[:64],
        desde=params.get("From", ""),
        account_sid=params.get("AccountSid"),
        campana_cliente_id=params.get("campana_cliente_id"),
        telefono_id=params.get("telefono_id"),
        ahora=reloj(),
        verificar_cuenta=proveedor.nombre == "twilio",
    )
    return Response(resultado.xml, media_type=XML)


@router.post("/twiml/aviso-grabacion")
def twiml_aviso(_params: Firmado) -> Response:
    s = get_settings()
    return Response(
        twiml.twiml_aviso_grabacion(s.telefonia_aviso_grabacion, s.telefonia_idioma_voz),
        media_type=XML,
    )


@router.post("/twiml/dial-terminado")
def twiml_dial_terminado(
    params: Firmado, db: Db, reloj: RelojDep, llamada_id: str | None = None
) -> Response:
    servicio.procesar_dial_terminado(db, params, llamada_id, reloj())
    return Response(twiml.twiml_colgar(), media_type=XML)


@router.post("/webhooks/estado", status_code=204)
def webhook_estado(
    params: Firmado, db: Db, reloj: RelojDep, llamada_id: str | None = None
) -> Response:
    servicio.procesar_estado(db, params, llamada_id, reloj())
    return Response(status_code=204)


@router.post("/webhooks/grabacion", status_code=204)
def webhook_grabacion(
    params: Firmado, db: Db, reloj: RelojDep, llamada_id: str | None = None
) -> Response:
    servicio.procesar_grabacion(db, params, llamada_id, reloj())
    return Response(status_code=204)
