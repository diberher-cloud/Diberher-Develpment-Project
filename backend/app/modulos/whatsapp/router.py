"""Endpoints de WhatsApp: webhooks de Twilio (firma, sin JWT), configuración, plantillas y
autorizaciones (fase-2b.md §4.1-4.4, §4.9-4.10)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencias import requiere_rol, usuario_actual
from app.integraciones.twilio_webhook import validar_peticion_twilio
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.integraciones.whatsapp.proveedor import ProveedorWhatsApp
from app.modulos.consola.servicio import enmascarar_telefono
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import (
    servicio_autorizaciones,
    servicio_entrante,
    servicio_estado,
    servicio_plantillas,
)
from app.modulos.whatsapp.esquemas import (
    AutorizacionCrear,
    AutorizacionSalida,
    ConfiguracionWhatsApp,
    Finalidad,
    PlantillaActualizar,
    PlantillaSalida,
    ResultadoSincronizacion,
)
from app.paginacion import IdRuta, Pagina, Paginacion
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
router_autorizaciones = APIRouter(prefix="/autorizaciones", tags=["autorizaciones"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Admin = Annotated[Usuario, Depends(requiere_rol("administrador"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]
Proveedor = Annotated[ProveedorWhatsApp, Depends(obtener_proveedor_whatsapp)]
XML_VACIO = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


async def _validar_peticion(request: Request, proveedor: Proveedor) -> dict[str, str]:
    return await validar_peticion_twilio(request, proveedor.validar_firma)


Firmado = Annotated[dict[str, str], Depends(_validar_peticion)]


def simulacion_habilitada() -> bool:
    s = get_settings()
    return s.whatsapp_proveedor == "falso" and s.entorno != "produccion"


# ---- Webhooks ----------------------------------------------------------------------------------
@router.post("/webhooks/entrante")
def webhook_entrante(params: Firmado, db: Db, reloj: RelojDep, proveedor: Proveedor) -> Response:
    servicio_entrante.recibir(db, proveedor, params, reloj())
    return Response(XML_VACIO, media_type="application/xml")


@router.post("/webhooks/estado", status_code=204)
def webhook_estado(params: Firmado, db: Db, reloj: RelojDep, proveedor: Proveedor) -> Response:
    servicio_estado.procesar_webhook(db, proveedor, params, reloj())
    return Response(status_code=204)


# ---- Configuración -----------------------------------------------------------------------------
@router.get("/configuracion", response_model=ConfiguracionWhatsApp)
def configuracion(_usuario: Cualquiera) -> ConfiguracionWhatsApp:
    s = get_settings()
    return ConfiguracionWhatsApp(
        proveedor=s.whatsapp_proveedor,
        simulacion=simulacion_habilitada(),
        numero_empresa_mascara=enmascarar_telefono(s.whatsapp_numero_empresa),
        margen_ventana_segundos=s.whatsapp_margen_ventana_segundos,
        max_caracteres_texto=4096,
        max_conversaciones_agente=s.atencion_max_conversaciones_agente,
        media_max_bytes=s.whatsapp_media_max_bytes,
    )


# ---- Plantillas --------------------------------------------------------------------------------
@router.get("/plantillas", response_model=list[PlantillaSalida])
def listar_plantillas(
    usuario: Cualquiera,
    db: Db,
    campana_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    enviables: bool | None = None,
) -> list[PlantillaSalida]:
    return servicio_plantillas.listar(db, usuario, campana_id, enviables)


@router.post("/plantillas/sincronizar", response_model=ResultadoSincronizacion)
def sincronizar(usuario: Admin, db: Db, reloj: RelojDep, proveedor: Proveedor):
    return servicio_plantillas.sincronizar(db, proveedor, usuario, reloj())


@router.put("/plantillas/{plantilla_id}", response_model=PlantillaSalida)
def actualizar_plantilla(
    plantilla_id: IdRuta, datos: PlantillaActualizar, usuario: Gestor, db: Db, reloj: RelojDep
) -> PlantillaSalida:
    return servicio_plantillas.actualizar(db, plantilla_id, datos, usuario, reloj())


# ---- Autorizaciones (opt-in) -------------------------------------------------------------------
@router_autorizaciones.get("", response_model=Pagina[AutorizacionSalida])
def listar_autorizaciones(
    usuario: Gestor,
    params: Paginacion,
    db: Db,
    numero: str | None = None,
    finalidad: Finalidad | None = None,
    vigentes: bool | None = None,
) -> Pagina[AutorizacionSalida]:
    items, total = servicio_autorizaciones.listar(db, usuario, params, numero, finalidad, vigentes)
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)


@router_autorizaciones.post("", response_model=AutorizacionSalida, status_code=201)
def crear_autorizacion(
    datos: AutorizacionCrear, usuario: Gestor, db: Db, reloj: RelojDep
) -> AutorizacionSalida:
    return servicio_autorizaciones.crear(db, usuario, datos, reloj())


@router_autorizaciones.delete("/{autorizacion_id}", status_code=204)
def revocar_autorizacion(
    autorizacion_id: IdRuta, usuario: Gestor, db: Db, reloj: RelojDep
) -> Response:
    servicio_autorizaciones.revocar(db, usuario, autorizacion_id, reloj())
    return Response(status_code=204)
