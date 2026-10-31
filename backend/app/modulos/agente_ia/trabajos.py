"""Manejadores de los trabajos `ia.*` y ganchos `AL_AGOTAR` (fase-2c.md §4.5)."""

import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.modulos.agente_ia import bucle, derivacion, presupuesto
from app.modulos.agente_ia.canal_chat import CanalChat
from app.modulos.agente_ia.contexto import RefInteraccion
from app.modulos.agente_ia.llm import obtener_cliente_llm
from app.modulos.agente_ia.modelos import ErrorIA
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.modelos import Conversacion
from app.trabajos import cola
from app.trabajos.modelos import Trabajo

# El identificador del arrendamiento es único por ejecución (dos workers nunca comparten uno).


def encolar_turno(db: Session, conversacion_id: int, ahora: datetime) -> Trabajo:
    """*Debounce*: N mensajes seguidos producen un turno (como mucho cada
    `IA_DEBOUNCE_MAX_SEGUNDOS`). Sin commit."""
    s = get_settings()
    debounce = timedelta(seconds=s.ia_debounce_segundos)
    existente = cola.encolar(
        db,
        "ia.turno",
        {"conversacion_id": conversacion_id},
        clave_unica=f"turno_ia:{conversacion_id}",
        disponible_desde=ahora + debounce,
        max_intentos=3,
        ahora=ahora,
    )
    tope = existente.creado_en + timedelta(seconds=s.ia_debounce_max_segundos)
    cola.posponer(db, existente, min(ahora + debounce, tope))
    return existente


def turno(db: Session, payload: dict[str, Any], ahora: datetime) -> None:
    """Trabajo `ia.turno`: nunca mantiene una transacción abierta durante la llamada al modelo."""
    from app.trabajos.registro import ErrorTrabajo  # noqa: F401  (documenta las excepciones)

    conversacion_id = int(payload["conversacion_id"])
    db.commit()  # cierra la transacción del ejecutor
    fabrica = sessionmaker(bind=db.get_bind(), autoflush=True, expire_on_commit=False)
    t0 = time.monotonic()

    def reloj() -> datetime:
        return ahora + timedelta(seconds=time.monotonic() - t0)

    trabajador = f"{uuid.uuid4().hex[:12]}:{conversacion_id}"  # único por ejecución
    bucle.ejecutar_turno(
        fabrica,
        CanalChat(),
        RefInteraccion("conversacion", conversacion_id),
        obtener_cliente_llm(),
        reloj,
        trabajador,
    )


def turno_agotado(db: Session, payload: dict[str, Any], codigo: str, ahora: datetime) -> None:
    """Gancho: el turno agotó sus intentos -> `ia_error` + `errores_ia(AGOTADO)`. Sin commit."""
    conv = conversaciones.bloquear(db, int(payload["conversacion_id"]))
    if conv.campana_id is not None:
        db.add(
            ErrorIA(
                conversacion_id=conv.id,
                campana_id=conv.campana_id,
                codigo="AGOTADO",
                transitorio=False,
                creado_en=ahora,
            )
        )
        db.flush()
        presupuesto.comprobar_errores(db, conv.campana_id, ahora)
    if conv.estado == "abierta" and conv.atendida_por == "ia":
        derivacion.derivar_determinista(
            db, CanalChat(), RefInteraccion("conversacion", conv.id), "ia_error", ahora
        )


def traspasar_campana(db: Session, payload: dict[str, Any], ahora: datetime) -> None:
    quedan = derivacion.traspasar_campana(db, payload, ahora)
    if quedan:
        cola.encolar(
            db,
            "ia.traspasar_campana",
            payload,
            clave_unica=f"ia_traspaso:{payload.get('campana_id') or 'global'}",
            disponible_desde=ahora + timedelta(seconds=2),
            ahora=ahora,
        )


def evaluacion(db: Session, payload: dict[str, Any], ahora: datetime) -> None:
    from app.modulos.agente_ia.evaluacion import servicio

    servicio.ejecutar_evaluacion(db, int(payload["evaluacion_id"]), ahora)


__all__ = ["Conversacion"]
