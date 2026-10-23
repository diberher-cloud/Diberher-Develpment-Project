"""Parámetros y respuesta paginada (§4.1)."""

from typing import Annotated, Any

from fastapi import Depends, Path, Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class Pagina[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ParamsPaginacion:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


Paginacion = Annotated[ParamsPaginacion, Depends()]


def paginar(
    db: Session, consulta: Select[Any], params: ParamsPaginacion, escalares: bool = True
) -> tuple[list[Any], int]:
    """Ejecuta `consulta` paginada. Devuelve (filas, total)."""
    total = db.scalar(select(func.count()).select_from(consulta.order_by(None).subquery())) or 0
    paginada = consulta.offset(params.offset).limit(params.page_size)
    if escalares:
        filas = list(db.scalars(paginada))
    else:
        filas = list(db.execute(paginada).all())
    return filas, total


IdRuta = Annotated[int, Path(ge=1, le=2**31 - 1)]
