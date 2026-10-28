"""Cumplimiento de WhatsApp: exclusiones por canal, autorizaciones (opt-in), opt-out posterior y
motivos de bloqueo de plantillas (ADR-0012, fase-2b.md §4.6)."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.campanas.modelos import Campana
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.cumplimiento.politica import PoliticaCumplimiento as PoliticaModelo
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal

TIPOS_CAMPANA = ("venta", "cobranza")


@dataclass
class MotivosPlantilla:
    motivos: list[tuple[str, str]] = field(default_factory=list)
    proxima_ventana_inicio: datetime | None = None
    politica_version: int | None = None

    @property
    def permitido(self) -> bool:
        return not self.motivos


def mensaje_excluido(motivo: str) -> str:
    return f"El número está excluido para WhatsApp ({motivo})."


def mensaje_sin_autorizacion(tipo_campana: str) -> str:
    return f"El número no tiene autorización vigente para WhatsApp ({tipo_campana})."


def exclusion_aplicable(db: Session, numero: str, tipo_campana: str | None) -> Exclusion | None:
    """Primera exclusión aplicable a WhatsApp (`canal IN ('todos','whatsapp')`). Sin campaña
    (`tipo_campana` nulo) cuenta cualquier finalidad."""
    consulta = select(Exclusion).where(
        Exclusion.numero_e164 == numero, Exclusion.canal.in_(("todos", "whatsapp"))
    )
    if tipo_campana is not None:
        consulta = consulta.where(Exclusion.aplica_a.in_((tipo_campana, "todas")))
    return db.scalar(consulta.order_by(Exclusion.id).limit(1))


def opt_out_posterior(db: Session, conv: Conversacion) -> bool:
    """Solicitud del titular (para WhatsApp) posterior al último mensaje del cliente."""
    if conv.ultimo_entrante_en is None:
        return False
    return (
        db.scalar(
            select(Exclusion.id)
            .where(
                Exclusion.numero_e164 == conv.numero_cliente_e164,
                Exclusion.motivo == "solicitud_titular",
                Exclusion.canal.in_(("todos", "whatsapp")),
                Exclusion.creado_en > conv.ultimo_entrante_en,
            )
            .limit(1)
        )
        is not None
    )


def autorizacion_vigente(db: Session, numero: str, tipo_campana: str) -> bool:
    return (
        db.scalar(
            select(AutorizacionCanal.id)
            .where(
                AutorizacionCanal.numero_e164 == numero,
                AutorizacionCanal.canal == "whatsapp",
                AutorizacionCanal.clave_vigente.is_not(None),
                AutorizacionCanal.finalidad.in_((tipo_campana, "todas")),
            )
            .limit(1)
        )
        is not None
    )


def motivos_plantilla(
    db: Session, cliente_id: int, numero: str, tipo_campana: str, ahora: datetime
) -> MotivosPlantilla:
    """`EXCLUIDO`, `SIN_AUTORIZACION` y los de horario/frecuencia del canal `whatsapp_mensaje`."""
    resultado = MotivosPlantilla()
    exc = exclusion_aplicable(db, numero, tipo_campana)
    if exc is not None:
        resultado.motivos.append(
            ("EXCLUIDO", f"El número está excluido para WhatsApp ({exc.motivo}).")
        )
    if not autorizacion_vigente(db, numero, tipo_campana):
        resultado.motivos.append(("SIN_AUTORIZACION", mensaje_sin_autorizacion(tipo_campana)))
    evaluacion, version = cumplimiento.evaluar_para_cliente(
        db, cliente_id, tipo_campana, "whatsapp_mensaje", ahora
    )
    resultado.politica_version = version
    resultado.motivos.extend((m.codigo, m.mensaje) for m in evaluacion.motivos)
    if not evaluacion.permitido:
        resultado.proxima_ventana_inicio = evaluacion.proxima_ventana_inicio
    return resultado


def politicas_aplicables(db: Session, campana_id: int | None) -> list[PoliticaModelo]:
    """Política del tipo de la campaña; sin campaña, las dos activas (la más restrictiva manda)."""
    if campana_id is not None:
        campana = db.get(Campana, campana_id)
        if campana is not None:
            return [cumplimiento.cargar_politica(db, campana.tipo)[0]]
    return [cumplimiento.cargar_politica(db, tipo)[0] for tipo in TIPOS_CAMPANA]


def festivos_para(db: Session, momento: datetime, politica: PoliticaModelo):
    return cumplimiento.cargar_festivos(db, momento, politica)


def hay_agente_disponible(db: Session, campana_id: int | None) -> bool:
    """¿Hay algún agente `disponible` asignado a la campaña con WhatsApp (o, sin campaña, a
    alguna campaña activa con WhatsApp)?"""
    from app.modulos.campanas.modelos import CampanaAgente
    from app.modulos.consola.modelos import EstadoAgente

    consulta = (
        select(EstadoAgente.usuario_id)
        .join(CampanaAgente, CampanaAgente.usuario_id == EstadoAgente.usuario_id)
        .join(Campana, Campana.id == CampanaAgente.campana_id)
        .where(
            EstadoAgente.estado == "disponible",
            Campana.estado == "activa",
            Campana.whatsapp_habilitado.is_(True),
        )
        .limit(1)
    )
    if campana_id is not None:
        consulta = consulta.where(Campana.id == campana_id)
    return db.scalar(consulta) is not None


__all__ = [
    "MotivosPlantilla",
    "autorizacion_vigente",
    "exclusion_aplicable",
    "festivos_para",
    "hay_agente_disponible",
    "motivos_plantilla",
    "opt_out_posterior",
    "politicas_aplicables",
]
