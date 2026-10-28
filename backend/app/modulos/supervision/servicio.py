"""Supervisión mínima de agentes (§4.7)."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.esquemas import EstadoAgenteValor, MotivoPausa
from app.modulos.consola.modelos import EstadoAgente
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.tipos import FechaHoraZ


class LlamadaActual(BaseModel):
    id: int
    estado: str
    campana_id: int
    campana_nombre: str


class AgenteSupervision(BaseModel):
    usuario_id: int
    nombre: str
    estado: EstadoAgenteValor
    desde: FechaHoraZ
    motivo_pausa: MotivoPausa | None
    campanas: list[int]
    llamada: LlamadaActual | None


def listar_agentes(db: Session, ahora: datetime) -> list[AgenteSupervision]:
    agentes = db.execute(
        select(Usuario, EstadoAgente)
        .outerjoin(EstadoAgente, EstadoAgente.usuario_id == Usuario.id)
        .where(Usuario.rol == "agente", Usuario.activo.is_(True))
        .order_by(func.lower(Usuario.nombre), Usuario.id)
    ).all()
    campanas: dict[int, list[int]] = {}
    for uid, cid in db.execute(
        select(CampanaAgente.usuario_id, CampanaAgente.campana_id).order_by(
            CampanaAgente.campana_id
        )
    ):
        campanas.setdefault(uid, []).append(cid)
    llamadas_ids = [e.llamada_id for _, e in agentes if e is not None and e.llamada_id]
    llamadas: dict[int, LlamadaActual] = {}
    if llamadas_ids:
        for ll, camp in db.execute(
            select(Llamada, Campana)
            .join(CampanaCliente, CampanaCliente.id == Llamada.campana_cliente_id)
            .join(Campana, Campana.id == CampanaCliente.campana_id)
            .where(Llamada.id.in_(llamadas_ids))
        ):
            llamadas[ll.id] = LlamadaActual(
                id=ll.id, estado=ll.estado, campana_id=camp.id, campana_nombre=camp.nombre
            )
    return [
        AgenteSupervision(
            usuario_id=u.id,
            nombre=u.nombre,
            estado=e.estado if e else "desconectado",  # type: ignore[arg-type]
            desde=e.desde if e else ahora,
            motivo_pausa=e.motivo_pausa if e else None,  # type: ignore[arg-type]
            campanas=campanas.get(u.id, []),
            llamada=llamadas.get(e.llamada_id) if e is not None and e.llamada_id else None,
        )
        for u, e in agentes
    ]


# ---- Estado de la cola de trabajos y del worker (fase-2b.md §4.7) --------------------------------
LATIDO_ACTIVO_SEGUNDOS = 60


class TrabajadorEstado(BaseModel):
    trabajador: str
    ultimo_latido: FechaHoraZ
    activo: bool


class TrabajosPorEstado(BaseModel):
    tipo: str
    estado: str
    total: int


class TrabajoFallido(BaseModel):
    id: int
    tipo: str
    ultimo_error: str | None
    intentos: int
    actualizado_en: FechaHoraZ


class EstadoTrabajos(BaseModel):
    trabajadores: list[TrabajadorEstado]
    por_estado: list[TrabajosPorEstado]
    fallidos_recientes: list[TrabajoFallido]


def estado_trabajos(db: Session, ahora: datetime) -> EstadoTrabajos:
    from datetime import timedelta

    from app.trabajos.modelos import LatidoWorker, Trabajo

    activo_desde = ahora - timedelta(seconds=LATIDO_ACTIVO_SEGUNDOS)
    latidos = db.scalars(select(LatidoWorker).order_by(LatidoWorker.trabajador))
    grupos = db.execute(
        select(Trabajo.tipo, Trabajo.estado, func.count(Trabajo.id))
        .group_by(Trabajo.tipo, Trabajo.estado)
        .order_by(Trabajo.tipo, Trabajo.estado)
    )
    fallidos = db.scalars(
        select(Trabajo)
        .where(Trabajo.estado == "fallido", Trabajo.actualizado_en >= ahora - timedelta(hours=24))
        .order_by(Trabajo.actualizado_en.desc(), Trabajo.id.desc())
        .limit(20)
    )
    return EstadoTrabajos(
        trabajadores=[
            TrabajadorEstado(
                trabajador=latido.trabajador,
                ultimo_latido=latido.ultimo_latido,
                activo=latido.ultimo_latido >= activo_desde,
            )
            for latido in latidos
        ],
        por_estado=[TrabajosPorEstado(tipo=t, estado=e, total=n) for t, e, n in grupos],
        fallidos_recientes=[
            TrabajoFallido(
                id=t.id,
                tipo=t.tipo,
                ultimo_error=t.ultimo_error,
                intentos=t.intentos,
                actualizado_en=t.actualizado_en,
            )
            for t in fallidos
        ],
    )
