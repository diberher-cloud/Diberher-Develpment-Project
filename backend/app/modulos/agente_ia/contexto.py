"""Contexto de una interacción del agente (fase-2c.md §4.1): lo fija SIEMPRE el servidor; el
modelo nunca elige cliente, campaña, registro ni teléfono."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.modulos.agente_ia.modelos import ConfiguracionIACampana
from app.modulos.campanas.modelos import Campana
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.cumplimiento import servicio as cumplimiento


class SinContextoIA(Exception):
    """La interacción no tiene registro vinculado, campaña o configuración IA."""


@dataclass(frozen=True)
class RefInteraccion:
    tipo: Literal["conversacion", "llamada"]
    id: int

    @property
    def clave(self) -> str:
        return f"{self.tipo}:{self.id}"


@dataclass(frozen=True)
class ContextoInteraccion:
    ref: RefInteraccion
    canal: Literal["chat", "voz"]
    canal_gestion: Literal["whatsapp_mensaje", "voz", "whatsapp_llamada"]
    cliente_id: int
    campana_id: int
    campana_cliente_id: int
    tipo_campana: Literal["venta", "cobranza"]
    telefono_id: int | None
    modelo: str
    esfuerzo: str
    prompt_version: int
    tratamiento: Literal["usted", "tu"]
    zona_horaria: str


def cargar_contexto(db: Session, ref: RefInteraccion) -> ContextoInteraccion:
    """Chat: de `conversaciones` (exige registro vinculado). Si `modelo_ia`, `esfuerzo_ia` y
    `prompt_version` son nulos los fija desde la configuración de la campaña (y hace flush):
    después no cambian. Lanza `SinContextoIA` si falta algún dato."""
    if ref.tipo != "conversacion":
        raise SinContextoIA("Solo hay contexto de chat en 2C.")
    conv = db.get(Conversacion, ref.id)
    if (
        conv is None
        or conv.campana_cliente_id is None
        or conv.campana_id is None
        or conv.cliente_id is None
    ):
        raise SinContextoIA("La conversación no tiene registro vinculado.")
    campana = db.get(Campana, conv.campana_id)
    cfg = db.get(ConfiguracionIACampana, conv.campana_id)
    if campana is None or cfg is None:
        raise SinContextoIA("La campaña no tiene configuración de IA.")
    if conv.modelo_ia is None or conv.esfuerzo_ia is None or conv.prompt_version is None:
        conv.modelo_ia = cfg.modelo
        conv.esfuerzo_ia = cfg.esfuerzo
        conv.prompt_version = cfg.prompt_version
        db.flush()
    politica, _ = cumplimiento.cargar_politica(db, campana.tipo)
    return ContextoInteraccion(
        ref=ref,
        canal="chat",
        canal_gestion="whatsapp_mensaje",
        cliente_id=conv.cliente_id,
        campana_id=campana.id,
        campana_cliente_id=conv.campana_cliente_id,
        tipo_campana=campana.tipo,  # type: ignore[arg-type]
        telefono_id=conv.telefono_id,
        modelo=conv.modelo_ia,
        esfuerzo=conv.esfuerzo_ia,
        prompt_version=conv.prompt_version,
        tratamiento=cfg.tratamiento,  # type: ignore[arg-type]
        zona_horaria=politica.zona_horaria,
    )
