from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.modulos.usuarios import servicio
from app.modulos.usuarios.esquemas import Rol, UsuarioActualizar, UsuarioCrear, UsuarioSalida
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import Pagina, Paginacion

router = APIRouter(prefix="/usuarios", tags=["usuarios"])
Admin = Annotated[Usuario, Depends(requiere_rol("administrador"))]


@router.get("", response_model=Pagina[UsuarioSalida])
def listar(
    _actor: Admin,
    params: Paginacion,
    db: Annotated[Session, Depends(get_db)],
    rol: Rol | None = None,
    activo: bool | None = None,
) -> Pagina[UsuarioSalida]:
    filas, total = servicio.listar(db, params, rol, activo)
    return Pagina(
        items=[UsuarioSalida.model_validate(u) for u in filas],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=UsuarioSalida, status_code=201)
def crear(datos: UsuarioCrear, actor: Admin, db: Annotated[Session, Depends(get_db)]) -> Usuario:
    return servicio.crear(db, datos, actor.id)


@router.patch("/{usuario_id}", response_model=UsuarioSalida)
def actualizar(
    usuario_id: int,
    datos: UsuarioActualizar,
    actor: Admin,
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    return servicio.actualizar(db, usuario_id, datos, actor)
