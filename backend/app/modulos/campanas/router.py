from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol, usuario_actual
from app.modulos.campanas import servicio
from app.modulos.campanas.esquemas import (
    AgenteAsignadoSalida,
    AsignarAgentes,
    CampanaActualizar,
    CampanaCrear,
    CampanaSalida,
    EstadoCampana,
    TipoCampana,
)
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta, Pagina, Paginacion

router = APIRouter(prefix="/campanas", tags=["campañas"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=Pagina[CampanaSalida])
def listar(
    usuario: Cualquiera,
    params: Paginacion,
    db: Db,
    estado: EstadoCampana | None = None,
    tipo: TipoCampana | None = None,
    q: str | None = None,
) -> Pagina[CampanaSalida]:
    items, total = servicio.listar(db, params, usuario, estado, tipo, q)
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=CampanaSalida, status_code=201)
def crear(datos: CampanaCrear, usuario: Gestor, db: Db) -> CampanaSalida:
    return servicio.crear(db, datos, usuario)


@router.get("/{campana_id}", response_model=CampanaSalida)
def obtener(campana_id: IdRuta, usuario: Cualquiera, db: Db) -> CampanaSalida:
    return servicio.a_salida(db, servicio.obtener(db, campana_id, usuario))


@router.patch("/{campana_id}", response_model=CampanaSalida)
def actualizar(
    campana_id: IdRuta, datos: CampanaActualizar, usuario: Gestor, db: Db
) -> CampanaSalida:
    return servicio.actualizar(db, campana_id, datos, usuario)


@router.delete("/{campana_id}", status_code=204)
def eliminar(campana_id: IdRuta, usuario: Gestor, db: Db) -> Response:
    servicio.eliminar(db, campana_id, usuario)
    return Response(status_code=204)


@router.get("/{campana_id}/agentes", response_model=list[AgenteAsignadoSalida])
def listar_agentes(campana_id: IdRuta, _usuario: Gestor, db: Db) -> list[AgenteAsignadoSalida]:
    return servicio.listar_agentes(db, campana_id)


@router.put("/{campana_id}/agentes", response_model=list[AgenteAsignadoSalida])
def asignar_agentes(
    campana_id: IdRuta, datos: AsignarAgentes, usuario: Gestor, db: Db
) -> list[AgenteAsignadoSalida]:
    return servicio.asignar_agentes(db, campana_id, datos, usuario)
