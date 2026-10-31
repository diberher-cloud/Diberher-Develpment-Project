"""Endpoints de configuración IA, ofertas, interruptor global y evaluaciones (fase-2c.md §6)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.agente_ia import configuracion
from app.modulos.agente_ia.esquemas import (
    ConfiguracionGlobalActualizar,
    ConfiguracionGlobalIA,
    ConfiguracionIA,
    ConfiguracionIAActualizar,
    EvaluacionCrear,
    EvaluacionIA,
    Oferta,
    OfertaActualizar,
    OfertaCrear,
)
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta, Pagina, Paginacion
from app.reloj import Reloj, get_reloj

router = APIRouter(tags=["agente ia"])
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Admin = Annotated[Usuario, Depends(requiere_rol("administrador"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]


# ---- Configuración por campaña -----------------------------------------------------------------
@router.get("/campanas/{campana_id}/ia", response_model=ConfiguracionIA)
def ver_configuracion(campana_id: IdRuta, _u: Gestor, db: Db, reloj: RelojDep) -> ConfiguracionIA:
    return configuracion.obtener(db, campana_id, reloj())


@router.put("/campanas/{campana_id}/ia", response_model=ConfiguracionIA)
def actualizar_configuracion(
    campana_id: IdRuta, datos: ConfiguracionIAActualizar, usuario: Gestor, db: Db, reloj: RelojDep
) -> ConfiguracionIA:
    return configuracion.actualizar(db, usuario, campana_id, datos, reloj())


@router.post("/campanas/{campana_id}/ia/activar", response_model=ConfiguracionIA)
def activar(campana_id: IdRuta, usuario: Gestor, db: Db, reloj: RelojDep) -> ConfiguracionIA:
    return configuracion.activar(db, usuario, campana_id, reloj())


@router.post("/campanas/{campana_id}/ia/desactivar", response_model=ConfiguracionIA)
def desactivar(
    campana_id: IdRuta, usuario: Gestor, db: Db, reloj: RelojDep, _cuerpo: dict | None = None
) -> ConfiguracionIA:
    return configuracion.desactivar(db, usuario, campana_id, reloj())


# ---- Ofertas -----------------------------------------------------------------------------------
@router.get("/campanas/{campana_id}/ofertas", response_model=list[Oferta])
def listar_ofertas(
    campana_id: IdRuta, _u: Gestor, db: Db, activas: bool | None = None
) -> list[Oferta]:
    return [Oferta.model_validate(o) for o in configuracion.listar_ofertas(db, campana_id, activas)]


@router.post("/campanas/{campana_id}/ofertas", response_model=Oferta, status_code=201)
def crear_oferta(
    campana_id: IdRuta, datos: OfertaCrear, usuario: Gestor, db: Db, reloj: RelojDep
) -> Oferta:
    return Oferta.model_validate(
        configuracion.crear_oferta(db, usuario, campana_id, datos, reloj())
    )


@router.patch("/campanas/{campana_id}/ofertas/{oferta_id}", response_model=Oferta)
def actualizar_oferta(
    campana_id: IdRuta,
    oferta_id: IdRuta,
    datos: OfertaActualizar,
    usuario: Gestor,
    db: Db,
    reloj: RelojDep,
) -> Oferta:
    return Oferta.model_validate(
        configuracion.actualizar_oferta(db, usuario, campana_id, oferta_id, datos, reloj())
    )


# ---- Global ------------------------------------------------------------------------------------
@router.get("/configuracion/ia", response_model=ConfiguracionGlobalIA)
def ver_global(_u: Gestor, db: Db) -> ConfiguracionGlobalIA:
    return configuracion.global_salida(db)


@router.put("/configuracion/ia", response_model=ConfiguracionGlobalIA)
def fijar_global(
    datos: ConfiguracionGlobalActualizar, usuario: Admin, db: Db, reloj: RelojDep
) -> ConfiguracionGlobalIA:
    return configuracion.fijar_global(db, usuario, datos.ia_activa, reloj())


# ---- Evaluaciones ------------------------------------------------------------------------------
@router.post("/ia/evaluaciones", response_model=EvaluacionIA, status_code=202)
def lanzar_evaluacion(
    datos: EvaluacionCrear, usuario: Admin, db: Db, reloj: RelojDep
) -> EvaluacionIA:
    from app.modulos.agente_ia.evaluacion import servicio

    return servicio.crear(db, usuario, datos, reloj())


@router.get("/ia/evaluaciones", response_model=Pagina[EvaluacionIA])
def listar_evaluaciones(
    _u: Gestor,
    db: Db,
    params: Paginacion,
    modo: Literal["offline", "online"] | None = None,
    campana_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
) -> Pagina[EvaluacionIA]:
    from app.modulos.agente_ia.evaluacion import servicio

    return servicio.listar(db, params, modo, campana_id)


@router.get("/ia/evaluaciones/{evaluacion_id}", response_model=EvaluacionIA)
def ver_evaluacion(evaluacion_id: IdRuta, _u: Gestor, db: Db) -> EvaluacionIA:
    from app.modulos.agente_ia.evaluacion import servicio

    return servicio.ver(db, evaluacion_id)
