from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.clientes import servicio
from app.modulos.clientes.esquemas import CampanaClienteSalida
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta, Pagina, Paginacion

router = APIRouter(tags=["clientes"])


@router.get("/campanas/{campana_id}/clientes", response_model=Pagina[CampanaClienteSalida])
def listar(
    campana_id: IdRuta,
    _usuario: Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))],
    params: Paginacion,
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    estado: Literal["pendiente", "en_gestion", "gestionado", "descartado"] | None = None,
) -> Pagina[CampanaClienteSalida]:
    items, total = servicio.listar_clientes_campana(db, campana_id, params, q, estado)
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)
