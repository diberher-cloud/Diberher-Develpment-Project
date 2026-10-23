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
