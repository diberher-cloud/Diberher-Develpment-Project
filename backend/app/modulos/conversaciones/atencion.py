"""Cola de atención de la bandeja humana (fase-2b.md §3.3, §4.8)."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion
from app.modulos.usuarios.modelos import Usuario
from app.tiempo_real import bus

PRIORIDAD_ALTA = (
    "solicitud_cliente",
    "queja",
    "identidad_bloqueada",
    "ia_no_resuelve",
    "ia_rechazo",
    "ia_max_tokens",
    "ia_iteraciones",
    "ia_stop_inesperado",
    "ia_monto_no_respaldado",
    "ia_error",
    "presupuesto_excedido",
    "ia_desactivada",
)
# 1 = urgente; 2 = el resto (entrante, sin_campana, liberada, agente_desconectado, supervisor).
PRIORIDAD: dict[str, int] = {motivo: 1 for motivo in PRIORIDAD_ALTA}
MAX_INTENTOS_TOMAR_SIGUIENTE = 5


def prioridad_de(motivo: str) -> int:
    return PRIORIDAD.get(motivo, 2)


def _publicar(db: Session, fila: ColaAtencion, accion: str) -> None:
    bus.publicar(
        db,
        "atencion.cola",
        {
            "cola_id": fila.id,
            "conversacion_id": fila.conversacion_id,
            "campana_id": fila.campana_id,
            "motivo": fila.motivo,
            "accion": accion,
        },
    )


def fila_activa(db: Session, conversacion_id: int, bloquear: bool = True) -> ColaAtencion | None:
    consulta = select(ColaAtencion).where(
        ColaAtencion.conversacion_id == conversacion_id,
        ColaAtencion.estado.in_(("pendiente", "asignada")),
    )
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.scalar(consulta)


def abrir(
    db: Session,
    conv: Conversacion,
    motivo: str,
    ahora: datetime,
    creado_en: datetime | None = None,
) -> ColaAtencion:
    fila = ColaAtencion(
        conversacion_id=conv.id,
        campana_id=conv.campana_id,
        motivo=motivo,
        prioridad=prioridad_de(motivo),
        estado="pendiente",
        clave_activa=str(conv.id),
        creado_en=creado_en or ahora,
    )
    db.add(fila)
    db.flush()
    _publicar(db, fila, "encolada")
    return fila


def asignar(db: Session, fila: ColaAtencion, usuario_id: int, ahora: datetime) -> None:
    primera = fila.estado == "pendiente"
    fila.estado = "asignada"
    fila.asignada_a = usuario_id
    if primera:
        fila.asignada_en = ahora
    db.flush()
    _publicar(db, fila, "asignada")


def cerrar(db: Session, fila: ColaAtencion, ahora: datetime) -> None:
    fila.estado = "cerrada"
    fila.clave_activa = None
    fila.cerrada_en = ahora
    db.flush()
    _publicar(db, fila, "cerrada")


def cerrar_activa(db: Session, conversacion_id: int, ahora: datetime) -> None:
    fila = fila_activa(db, conversacion_id)
    if fila is not None:
        cerrar(db, fila, ahora)


# ---- Capacidad ---------------------------------------------------------------------------------
def conversaciones_abiertas_de(db: Session, usuario_id: int) -> int:
    return (
        db.scalar(
            select(func.count(Conversacion.id)).where(
                Conversacion.estado == "abierta",
                Conversacion.atendida_por == "humano",
                Conversacion.usuario_asignado_id == usuario_id,
            )
        )
        or 0
    )


def exigir_capacidad(db: Session, usuario: Usuario) -> None:
    """Los agentes no pueden superar `ATENCION_MAX_CONVERSACIONES_AGENTE` (A/S sin límite)."""
    if usuario.rol != "agente":
        return
    if (
        conversaciones_abiertas_de(db, usuario.id)
        >= get_settings().atencion_max_conversaciones_agente
    ):
        raise ErrorApp(
            409, "CAPACIDAD_MAXIMA", "Alcanzó el máximo de conversaciones abiertas simultáneas."
        )


def campanas_atendibles_por(db: Session, usuario_id: int) -> list[int]:
    """Campañas activas con WhatsApp a las que está asignado el agente."""
    return list(
        db.scalars(
            select(Campana.id)
            .join(CampanaAgente, CampanaAgente.campana_id == Campana.id)
            .where(
                CampanaAgente.usuario_id == usuario_id,
                Campana.estado == "activa",
                Campana.whatsapp_habilitado.is_(True),
            )
        )
    )


# ---- Tomar siguiente ---------------------------------------------------------------------------
def tomar_siguiente(db: Session, usuario: Usuario, ahora: datetime) -> Conversacion | None:
    """Excepción documentada al orden de bloqueos (fase-2b.md §3.4): la fila de cola y la
    conversación se toman con `SKIP LOCKED`, así que este camino nunca espera por ellas."""
    from app.modulos.consola import estado as estado_agente
    from app.modulos.conversaciones import servicio

    estado_agente.bloquear(db, usuario.id)
    if estado_agente.estado_actual(db, usuario.id) != "disponible":
        raise ErrorApp(409, "AGENTE_NO_DISPONIBLE", "El agente debe estar en estado 'disponible'.")
    exigir_capacidad(db, usuario)
    campanas = campanas_atendibles_por(db, usuario.id)
    descartadas: list[int] = []
    if campanas:
        for _ in range(MAX_INTENTOS_TOMAR_SIGUIENTE):
            consulta = (
                select(ColaAtencion)
                .where(ColaAtencion.estado == "pendiente", ColaAtencion.campana_id.in_(campanas))
                .order_by(ColaAtencion.prioridad, ColaAtencion.creado_en, ColaAtencion.id)
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if descartadas:
                consulta = consulta.where(ColaAtencion.id.not_in(descartadas))
            fila = db.scalar(consulta)
            if fila is None:
                break
            conv = db.scalar(
                select(Conversacion)
                .where(Conversacion.id == fila.conversacion_id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if conv is None or conv.estado != "abierta" or conv.atendida_por != "sin_asignar":
                descartadas.append(fila.id)
                continue
            try:
                servicio.cambiar_dueno(
                    db, conv, servicio.Humano(usuario.id), None, usuario.id, ahora
                )
            except servicio.ConflictoDueno:
                descartadas.append(fila.id)
                continue
            servicio.auditar_tomar(db, conv, usuario)
            db.commit()
            return conv
    db.commit()
    return None
