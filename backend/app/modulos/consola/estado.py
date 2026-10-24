"""Estado del agente en BD: upsert, historial y evento `agente.estado` (§4.3)."""

from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogos import ESTADOS_LLAMADA_ACTIVAS, ESTADOS_LLAMADA_TIPIFICABLES
from app.errores import ErrorApp
from app.modulos.consola.esquemas import CambioEstado, EstadoAgenteSalida, TipificacionPendiente
from app.modulos.consola.estados import ErrorTransicion, resolver_transicion
from app.modulos.consola.modelos import EstadoAgente, HistorialEstadoAgente, Tipificacion
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.tiempo_real import bus
from app.tipos import a_utc_z


def obtener(db: Session, usuario_id: int) -> EstadoAgente | None:
    return db.get(EstadoAgente, usuario_id)


def estado_actual(db: Session, usuario_id: int) -> str:
    fila = obtener(db, usuario_id)
    return fila.estado if fila else "desconectado"


def llamada_sin_tipificar(db: Session, usuario_id: int) -> Llamada | None:
    """Llamada realizada y terminada del agente que aún no tiene tipificación."""
    return db.scalar(
        select(Llamada)
        .outerjoin(Tipificacion, Tipificacion.llamada_id == Llamada.id)
        .where(
            Llamada.usuario_id == usuario_id,
            Llamada.estado.in_(ESTADOS_LLAMADA_TIPIFICABLES),
            Tipificacion.id.is_(None),
        )
        .order_by(Llamada.id.desc())
        .limit(1)
    )


def fijar(
    db: Session,
    usuario_id: int,
    estado: str,
    ahora: datetime,
    motivo_pausa: str | None = None,
    llamada_id: int | None = None,
) -> EstadoAgente:
    """Cambia el estado, cierra/abre el historial y publica `agente.estado`. Sin commit."""
    fila = obtener(db, usuario_id)
    if fila is None:
        fila = EstadoAgente(
            usuario_id=usuario_id,
            estado=estado,
            desde=ahora,
            motivo_pausa=motivo_pausa,
            llamada_id=llamada_id,
            actualizado_en=ahora,
        )
        db.add(fila)
    else:
        fila.estado = estado
        fila.desde = ahora
        fila.motivo_pausa = motivo_pausa
        fila.llamada_id = llamada_id
        fila.actualizado_en = ahora
    db.execute(
        update(HistorialEstadoAgente)
        .where(HistorialEstadoAgente.usuario_id == usuario_id, HistorialEstadoAgente.fin.is_(None))
        .values(fin=ahora)
    )
    db.add(
        HistorialEstadoAgente(
            usuario_id=usuario_id, estado=estado, motivo_pausa=motivo_pausa, inicio=ahora
        )
    )
    db.flush()
    bus.publicar(
        db,
        "agente.estado",
        {
            "usuario_id": usuario_id,
            "estado": estado,
            "desde": a_utc_z(ahora),
            "motivo_pausa": motivo_pausa,
            "llamada_id": llamada_id,
        },
    )
    return fila


def a_salida(db: Session, usuario_id: int, ahora: datetime) -> EstadoAgenteSalida:
    fila = obtener(db, usuario_id)
    pendiente = llamada_sin_tipificar(db, usuario_id)
    return EstadoAgenteSalida(
        estado=fila.estado if fila else "desconectado",  # type: ignore[arg-type]
        desde=fila.desde if fila else ahora,
        motivo_pausa=fila.motivo_pausa if fila else None,  # type: ignore[arg-type]
        llamada_id=fila.llamada_id if fila else None,
        tipificacion_pendiente=(
            TipificacionPendiente(
                llamada_id=pendiente.id, campana_cliente_id=pendiente.campana_cliente_id
            )
            if pendiente
            else None
        ),
    )


def cambiar_manual(
    db: Session, usuario: Usuario, datos: CambioEstado, ahora: datetime
) -> EstadoAgenteSalida:
    fila = obtener(db, usuario.id)
    actual = fila.estado if fila else "desconectado"
    motivo_actual = fila.motivo_pausa if fila else None
    try:
        transicion = resolver_transicion(actual, motivo_actual, datos.estado, datos.motivo_pausa)
    except ErrorTransicion as exc:
        raise ErrorApp(exc.status, exc.codigo, exc.mensaje) from exc
    if transicion == "cambia":
        try:
            fijar(db, usuario.id, datos.estado, ahora, datos.motivo_pausa)
            db.commit()
        except IntegrityError as exc:  # dos primeras escrituras simultáneas del mismo agente
            db.rollback()
            raise ErrorApp(
                409, "ESTADO_CONCURRENTE", "El estado cambió a la vez; vuelva a intentarlo."
            ) from exc
    return a_salida(db, usuario.id, ahora)


def desconectar_por_inactividad(db: Session, usuario_id: int, ahora: datetime) -> bool:
    """Pasa a `desconectado` a un agente `disponible`/`pausa` sin sockets. True si cambió."""
    fila = obtener(db, usuario_id)
    if fila is None or fila.estado not in ("disponible", "pausa"):
        return False
    fijar(db, usuario_id, "desconectado", ahora)
    db.commit()
    return True


def bloquear(db: Session, usuario_id: int) -> None:
    """`FOR UPDATE` sobre la fila de estado del agente (si existe), con datos frescos.
    Primer eslabón del orden de bloqueo estados_agente -> clientes."""
    db.scalars(
        select(EstadoAgente)
        .where(EstadoAgente.usuario_id == usuario_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()


def gestion_pendiente(db: Session, usuario_id: int) -> Llamada | None:
    """Llamada del agente activa o terminada (realizada) sin tipificar."""
    return db.scalar(
        select(Llamada)
        .outerjoin(Tipificacion, Tipificacion.llamada_id == Llamada.id)
        .where(
            Llamada.usuario_id == usuario_id,
            or_(
                Llamada.estado.in_(ESTADOS_LLAMADA_ACTIVAS),
                and_(Llamada.estado.in_(ESTADOS_LLAMADA_TIPIFICABLES), Tipificacion.id.is_(None)),
            ),
        )
        .order_by(Llamada.id.desc())
        .limit(1)
    )
