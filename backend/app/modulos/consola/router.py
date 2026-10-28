"""Endpoints de la consola del agente (`/consola/*`) y tipificaciones por campaña."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.consola import estado as estado_agente
from app.modulos.consola import servicio, tipificacion
from app.modulos.consola.esquemas import (
    CambioEstado,
    CampanaConsola,
    EstadoAgenteSalida,
    FichaCliente,
    LlamadaSalida,
    Origen,
    RegistroTrabajo,
    Resultado,
    TipificacionCampanaSalida,
    TipificacionCrear,
    TipificacionSalida,
)
from app.modulos.conversaciones.esquemas import PlantillaConsolaCrear, ResultadoEnvioPlantilla
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_envio
from app.paginacion import IdRuta, Pagina, Paginacion
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/consola", tags=["consola"])
router_campana = APIRouter(tags=["tipificaciones"])
Agente = Annotated[Usuario, Depends(requiere_rol("agente"))]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]


@router.get("/estado", response_model=EstadoAgenteSalida)
def obtener_estado(usuario: Agente, db: Db, reloj: RelojDep) -> EstadoAgenteSalida:
    return estado_agente.a_salida(db, usuario.id, reloj())


@router.put("/estado", response_model=EstadoAgenteSalida)
def cambiar_estado(
    datos: CambioEstado, usuario: Agente, db: Db, reloj: RelojDep
) -> EstadoAgenteSalida:
    return estado_agente.cambiar_manual(db, usuario, datos, reloj())


@router.get("/campanas", response_model=list[CampanaConsola])
def campanas(usuario: Agente, db: Db, reloj: RelojDep) -> list[CampanaConsola]:
    return servicio.campanas_asignadas(db, usuario, reloj())


@router.get("/registros", response_model=Pagina[RegistroTrabajo])
def registros(
    usuario: Agente,
    params: Paginacion,
    db: Db,
    reloj: RelojDep,
    campana_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
) -> Pagina[RegistroTrabajo]:
    items, total = servicio.listar_registros(db, usuario, params, campana_id, reloj())
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("/registros/{registro_id}/tomar", response_model=FichaCliente)
def tomar(registro_id: IdRuta, usuario: Agente, db: Db, reloj: RelojDep) -> FichaCliente:
    return servicio.tomar(db, usuario, registro_id, reloj())


@router.post("/registros/{registro_id}/soltar", status_code=204)
def soltar(registro_id: IdRuta, usuario: Agente, db: Db, reloj: RelojDep) -> Response:
    servicio.soltar(db, usuario, registro_id, reloj())
    return Response(status_code=204)


@router.get("/registros/{registro_id}", response_model=FichaCliente)
def ficha(registro_id: IdRuta, usuario: Agente, db: Db, reloj: RelojDep) -> FichaCliente:
    return servicio.ver_ficha(db, usuario, registro_id, reloj())


@router.post("/registros/{registro_id}/whatsapp/plantilla", response_model=ResultadoEnvioPlantilla)
def enviar_plantilla_whatsapp(
    registro_id: IdRuta,
    datos: PlantillaConsolaCrear,
    usuario: Agente,
    db: Db,
    reloj: RelojDep,
) -> ResultadoEnvioPlantilla:
    return servicio_envio.enviar_plantilla_consola(
        db,
        usuario,
        registro_id,
        datos.telefono_id,
        datos.plantilla_id,
        datos.idempotencia_clave,
        reloj(),
    )


@router.get("/llamadas/{llamada_id}", response_model=LlamadaSalida)
def llamada(llamada_id: IdRuta, usuario: Agente, db: Db) -> LlamadaSalida:
    return servicio.obtener_llamada(db, usuario, llamada_id)


@router.post("/tipificaciones", response_model=TipificacionSalida, status_code=201)
def tipificar(
    datos: TipificacionCrear, usuario: Agente, db: Db, reloj: RelojDep
) -> TipificacionSalida:
    return tipificacion.tipificar(db, usuario, datos, reloj())


@router_campana.get(
    "/campanas/{campana_id}/tipificaciones", response_model=Pagina[TipificacionCampanaSalida]
)
def listar_tipificaciones(
    campana_id: IdRuta,
    _usuario: Gestor,
    params: Paginacion,
    db: Db,
    resultado: Resultado | None = None,
    origen: Origen | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> Pagina[TipificacionCampanaSalida]:
    items, total = tipificacion.listar_campana(
        db, campana_id, params, resultado, origen, desde, hasta
    )
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)
