from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol, usuario_actual
from app.modulos.cumplimiento import servicio
from app.modulos.cumplimiento.esquemas import (
    EvaluarPeticion,
    EvaluarRespuesta,
    FestivoActualizar,
    FestivoCrear,
    FestivoSalida,
    GenerarFestivosPeticion,
    GenerarFestivosRespuesta,
    PoliticaSalida,
    TipoCampana,
)
from app.modulos.usuarios.modelos import Usuario

router = APIRouter(tags=["cumplimiento"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Admin = Annotated[Usuario, Depends(requiere_rol("administrador"))]
Db = Annotated[Session, Depends(get_db)]


@router.get("/cumplimiento/politicas", response_model=list[PoliticaSalida])
def politicas(_u: Cualquiera, db: Db):
    return servicio.politicas_activas(db)


@router.get("/cumplimiento/politicas/{tipo_campana}/versiones", response_model=list[PoliticaSalida])
def versiones(tipo_campana: TipoCampana, _u: Gestor, db: Db):
    return servicio.versiones(db, tipo_campana)


@router.put(
    "/cumplimiento/politicas/{tipo_campana}", response_model=PoliticaSalida, status_code=201
)
def actualizar_politica(tipo_campana: TipoCampana, configuracion: dict[str, Any], u: Admin, db: Db):
    return servicio.actualizar_politica(db, tipo_campana, configuracion, u)


@router.post("/cumplimiento/evaluar", response_model=EvaluarRespuesta)
def evaluar(datos: EvaluarPeticion, _u: Cualquiera, db: Db) -> EvaluarRespuesta:
    return servicio.evaluar(db, datos.tipo_campana, datos.momento)


@router.get("/festivos", response_model=list[FestivoSalida])
def listar_festivos(_u: Cualquiera, db: Db, anio: Annotated[int, Query(ge=1984, le=2100)]):
    return servicio.listar_festivos(db, anio)


@router.post("/festivos/generar", response_model=GenerarFestivosRespuesta)
def generar(datos: GenerarFestivosPeticion, u: Admin, db: Db) -> GenerarFestivosRespuesta:
    return servicio.generar_festivos(db, datos.anio, u.id)


@router.post("/festivos", response_model=FestivoSalida, status_code=201)
def crear_festivo(datos: FestivoCrear, u: Admin, db: Db):
    return servicio.crear_festivo(db, datos, u)


@router.patch("/festivos/{festivo_id}", response_model=FestivoSalida)
def actualizar_festivo(festivo_id: int, datos: FestivoActualizar, u: Admin, db: Db):
    return servicio.actualizar_festivo(db, festivo_id, datos, u)
