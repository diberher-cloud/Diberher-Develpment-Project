"""Supervisión en vivo, acciones, uso, instrucciones, traspaso y vuelta a la IA (§6.5, §6.6)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol, usuario_actual
from app.modulos.agente_ia import derivacion, supervision
from app.modulos.agente_ia.esquemas import (
    AccionIA,
    ConversacionIAResumen,
    FilaHistorialSalida,
    Instruccion,
    InstruccionCrear,
    MetricasIA,
    TraspasarEntrada,
    UsoIAConversacion,
)
from app.modulos.conversaciones import salidas, servicio
from app.modulos.conversaciones.esquemas import Conversacion
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta, Pagina, Paginacion
from app.reloj import Reloj, get_reloj

router = APIRouter(tags=["agente ia"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Admin = Annotated[Usuario, Depends(requiere_rol("administrador"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]
IdOpc = Annotated[int | None, Query(ge=1, le=2**31 - 1)]


@router.get("/supervision/ia/conversaciones", response_model=Pagina[ConversacionIAResumen])
def conversaciones_ia(
    usuario: Gestor,
    db: Db,
    reloj: RelojDep,
    params: Paginacion,
    campana_id: IdOpc = None,
    estado: Literal["abierta", "cerrada"] = "abierta",
    atendida_por: Literal["sin_asignar", "humano", "ia", "todas"] = "ia",
    con_gestion: bool | None = None,
    identidad: Literal["verificada", "no_verificada"] | None = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> Pagina[ConversacionIAResumen]:
    items, total = supervision.listar_conversaciones(
        db, usuario, params, reloj(),
        campana_id=campana_id, estado=estado, atendida_por=atendida_por,
        con_gestion=con_gestion, identidad=identidad, desde=desde, hasta=hasta,
    )  # fmt: skip
    return Pagina(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/supervision/ia/metricas", response_model=MetricasIA)
def metricas(
    _u: Gestor,
    db: Db,
    reloj: RelojDep,
    campana_id: IdOpc = None,
    desde: date | None = None,
    hasta: date | None = None,
) -> MetricasIA:
    return supervision.metricas(db, campana_id, desde, hasta, reloj())


@router.get("/conversaciones/{conversacion_id}/acciones-ia", response_model=list[AccionIA])
def acciones(conversacion_id: IdRuta, usuario: Cualquiera, db: Db) -> list[AccionIA]:
    conv = servicio.cargar(db, conversacion_id)
    return supervision.acciones(db, usuario, conv)


@router.get("/conversaciones/{conversacion_id}/uso-ia", response_model=UsoIAConversacion)
def uso(conversacion_id: IdRuta, _u: Gestor, db: Db) -> UsoIAConversacion:
    return supervision.uso(db, servicio.cargar(db, conversacion_id))


@router.get("/conversaciones/{conversacion_id}/instrucciones", response_model=list[Instruccion])
def listar_instrucciones(conversacion_id: IdRuta, _u: Gestor, db: Db) -> list[Instruccion]:
    return supervision.listar_instrucciones(db, servicio.cargar(db, conversacion_id))


@router.post(
    "/conversaciones/{conversacion_id}/instrucciones", response_model=Instruccion, status_code=201
)
def instruir(
    conversacion_id: IdRuta, datos: InstruccionCrear, usuario: Gestor, db: Db, reloj: RelojDep
) -> Instruccion:
    return supervision.instruir(db, usuario, conversacion_id, datos.texto, reloj())


@router.post("/conversaciones/{conversacion_id}/traspasar", response_model=Conversacion)
def traspasar(
    conversacion_id: IdRuta, datos: TraspasarEntrada, usuario: Gestor, db: Db, reloj: RelojDep
) -> Conversacion:
    ahora = reloj()
    conv = derivacion.traspasar(db, usuario, conversacion_id, datos.resumen, ahora)
    return salidas.conversacion_salida(db, conv, usuario, ahora)


@router.post("/conversaciones/{conversacion_id}/devolver-ia", response_model=Conversacion)
def devolver_ia(
    conversacion_id: IdRuta,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
    _cuerpo: dict | None = None,
) -> Conversacion:
    ahora = reloj()
    conv = derivacion.devolver_a_ia(db, usuario, conversacion_id, ahora)
    return salidas.conversacion_salida(db, conv, usuario, ahora)


@router.get(
    "/conversaciones/{conversacion_id}/historial-ia", response_model=list[FilaHistorialSalida]
)
def historial_ia(conversacion_id: IdRuta, usuario: Admin, db: Db) -> list[FilaHistorialSalida]:
    return supervision.ver_historial(db, usuario, servicio.cargar(db, conversacion_id))
