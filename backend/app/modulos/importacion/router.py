from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencias import requiere_rol
from app.errores import ErrorApp
from app.modulos.campanas.modelos import Campana
from app.modulos.importacion import servicio
from app.modulos.importacion.esquemas import (
    ErrorImportacionSalida,
    ImportacionDetalleSalida,
    ImportacionSalida,
    Severidad,
)
from app.modulos.importacion.modelos import Importacion, ImportacionError
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import Pagina, Paginacion, paginar

router = APIRouter(tags=["importación"])
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Db = Annotated[Session, Depends(get_db)]


@router.post(
    "/campanas/{campana_id}/importaciones", response_model=ImportacionDetalleSalida, status_code=201
)
def importar(
    campana_id: int,
    usuario: Gestor,
    db: Db,
    archivo: Annotated[UploadFile, File()],
) -> ImportacionDetalleSalida:
    campana = servicio.campana_importable(db, campana_id)
    nombre, contenido = servicio.leer_subida(archivo, get_settings().importacion_max_bytes)
    return servicio.importar(db, campana, usuario, nombre, contenido)


@router.get("/campanas/{campana_id}/importaciones", response_model=Pagina[ImportacionSalida])
def listar(
    campana_id: int, _usuario: Gestor, params: Paginacion, db: Db
) -> Pagina[ImportacionSalida]:
    if db.get(Campana, campana_id) is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    consulta = (
        select(Importacion)
        .where(Importacion.campana_id == campana_id)
        .order_by(Importacion.creado_en.desc(), Importacion.id.desc())
    )
    filas, total = paginar(db, consulta, params)
    return Pagina(
        items=[ImportacionSalida.model_validate(i) for i in filas],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/importaciones/{importacion_id}", response_model=ImportacionSalida)
def obtener(importacion_id: int, _usuario: Gestor, db: Db) -> Importacion:
    imp = db.get(Importacion, importacion_id)
    if imp is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Importación no encontrada.")
    return imp


@router.get(
    "/importaciones/{importacion_id}/errores", response_model=Pagina[ErrorImportacionSalida]
)
def errores(
    importacion_id: int,
    _usuario: Gestor,
    params: Paginacion,
    db: Db,
    severidad: Severidad | None = None,
) -> Pagina[ErrorImportacionSalida]:
    if db.get(Importacion, importacion_id) is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Importación no encontrada.")
    consulta = select(ImportacionError).where(ImportacionError.importacion_id == importacion_id)
    if severidad:
        consulta = consulta.where(ImportacionError.severidad == severidad)
    filas, total = paginar(
        db, consulta.order_by(ImportacionError.fila, ImportacionError.id), params
    )
    return Pagina(
        items=[ErrorImportacionSalida.model_validate(e) for e in filas],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
