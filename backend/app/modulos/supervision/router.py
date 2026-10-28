from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.supervision import servicio
from app.modulos.supervision.servicio import AgenteSupervision, EstadoTrabajos
from app.modulos.usuarios.modelos import Usuario
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/supervision", tags=["supervisión"])


@router.get("/agentes", response_model=list[AgenteSupervision])
def agentes(
    _usuario: Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))],
    db: Annotated[Session, Depends(get_db)],
    reloj: Annotated[Reloj, Depends(get_reloj)],
) -> list[AgenteSupervision]:
    return servicio.listar_agentes(db, reloj())


@router.get("/trabajos", response_model=EstadoTrabajos)
def trabajos(
    _usuario: Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))],
    db: Annotated[Session, Depends(get_db)],
    reloj: Annotated[Reloj, Depends(get_reloj)],
) -> EstadoTrabajos:
    return servicio.estado_trabajos(db, reloj())
