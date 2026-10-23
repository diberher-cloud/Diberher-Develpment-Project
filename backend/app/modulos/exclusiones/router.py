from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.exclusiones import servicio
from app.modulos.exclusiones.esquemas import (
    AplicaA,
    ExclusionCrear,
    ExclusionSalida,
    Motivo,
    ResultadoImportacionExclusiones,
    resolver_aplica_a,
)
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.servicio import leer_subida
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta, Pagina, Paginacion

router = APIRouter(prefix="/exclusiones", tags=["exclusiones"])
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=Pagina[ExclusionSalida])
def listar(
    _usuario: Gestor,
    params: Paginacion,
    db: Db,
    q: str | None = None,
    motivo: Motivo | None = None,
    aplica_a: AplicaA | None = None,
) -> Pagina[ExclusionSalida]:
    filas, total = servicio.listar(db, params, q, motivo, aplica_a)
    return Pagina(
        items=[ExclusionSalida.model_validate(e) for e in filas],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=ExclusionSalida, status_code=201)
def crear(datos: ExclusionCrear, usuario: Gestor, db: Db) -> Exclusion:
    return servicio.crear(db, datos, usuario)


@router.post("/importar", response_model=ResultadoImportacionExclusiones)
def importar(
    usuario: Gestor,
    db: Db,
    archivo: Annotated[UploadFile, File()],
    motivo: Annotated[Motivo, Form()],
    aplica_a: Annotated[AplicaA | None, Form()] = None,
) -> dict:
    # Valida `aplica_a` antes de leer el archivo.
    resolver_aplica_a(motivo, aplica_a)
    nombre, contenido = leer_subida(archivo, get_settings().importacion_max_bytes)
    return servicio.importar(db, usuario, contenido, motivo, aplica_a, nombre)


@router.delete("/{exclusion_id}", status_code=204)
def eliminar(exclusion_id: IdRuta, usuario: Gestor, db: Db) -> Response:
    servicio.eliminar(db, exclusion_id, usuario)
    return Response(status_code=204)
