"""Evaluación PURA de la frecuencia de contacto (Ley 2300, art. 3; ADR-0012 §2).

Sin E/S ni reloj: el historial del cliente se inyecta como lista de `IntentoPrevio`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.modulos.cumplimiento.politica import PoliticaCumplimiento

Canal = Literal["voz", "whatsapp_mensaje", "whatsapp_llamada"]
MEDIO: dict[str, str] = {
    "voz": "telefono",
    "whatsapp_mensaje": "whatsapp",
    "whatsapp_llamada": "whatsapp",
}


@dataclass(frozen=True)
class Motivo:
    codigo: Literal[
        "FESTIVO", "DIA_SIN_FRANJA", "FUERA_DE_FRANJA", "FRECUENCIA_DIA", "FRECUENCIA_MEDIOS"
    ]
    mensaje: str


@dataclass(frozen=True)
class IntentoPrevio:
    momento: datetime  # con zona
    canal: Canal
    iniciado_por: Literal["empresa", "cliente"]
    contacto_directo: bool


def _local(momento: datetime, zona: ZoneInfo) -> datetime:
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("El momento debe incluir zona horaria.")
    try:
        return momento.astimezone(zona)
    except OverflowError as exc:
        raise ValueError("El momento está fuera del rango de fechas soportado.") from exc


def _inicio_dia(local: datetime, zona: ZoneInfo, dias: int = 0) -> datetime:
    return datetime.combine(local.date() + timedelta(days=dias), time.min, tzinfo=zona)


def _inicio_semana(local: datetime, zona: ZoneInfo, semanas: int = 0) -> datetime:
    lunes = local.date() - timedelta(days=local.weekday()) + timedelta(weeks=semanas)
    return datetime.combine(lunes, time.min, tzinfo=zona)


def _ventana(
    momento: datetime, politica: PoliticaCumplimiento, historial: Sequence[IntentoPrevio]
) -> list[IntentoPrevio]:
    """Intentos de la ventana semanal de `momento` (solo los que ocurrieron hasta `momento`)."""
    zona = ZoneInfo(politica.zona_horaria)
    local = _local(momento, zona)
    if politica.frecuencia.semana == "calendario":
        inicio = _inicio_semana(local, zona)
        fin = _inicio_semana(local, zona, 1)
        return [i for i in historial if inicio <= i.momento < fin and i.momento <= momento]
    inicio = momento - timedelta(days=7)
    return [i for i in historial if inicio < i.momento <= momento]


def _es_directo(intento: IntentoPrevio, politica: PoliticaCumplimiento) -> bool:
    if not intento.contacto_directo:
        return False
    return intento.iniciado_por == "empresa" or politica.entrantes.establecen_contacto_directo


def evaluar_frecuencia(
    momento: datetime,
    canal: Canal,
    politica: PoliticaCumplimiento,
    historial: Sequence[IntentoPrevio],
) -> tuple[Motivo, ...]:
    zona = ZoneInfo(politica.zona_horaria)
    local = _local(momento, zona)
    cfg = politica.frecuencia
    ventana = _ventana(momento, politica, historial)
    if cfg.solo_tras_contacto_directo and not any(_es_directo(i, politica) for i in ventana):
        return ()
    contables = [
        i
        for i in ventana
        if i.iniciado_por == "empresa" and (i.contacto_directo or cfg.contar_intentos_sin_contacto)
    ]
    motivos: list[Motivo] = []
    hoy = sum(1 for i in contables if i.momento.astimezone(zona).date() == local.date())
    if hoy >= cfg.max_contactos_dia:
        motivos.append(
            Motivo(
                "FRECUENCIA_DIA",
                f"Ya hubo {hoy} contacto(s) con el cliente hoy (máximo {cfg.max_contactos_dia}).",
            )
        )
    medios = {MEDIO[i.canal] for i in contables} | {MEDIO[canal]}
    if len(medios) > cfg.max_canales_semana:
        motivos.append(
            Motivo(
                "FRECUENCIA_MEDIOS",
                "El cliente ya fue contactado por otro canal esta semana "
                f"(máximo {cfg.max_canales_semana} canal(es)).",
            )
        )
    return tuple(motivos)


def proximo_permitido_frecuencia(
    momento: datetime,
    canal: Canal,
    politica: PoliticaCumplimiento,
    historial: Sequence[IntentoPrevio],
    horizonte_dias: int = 14,
) -> datetime | None:
    """Menor instante t >= momento sin motivos de frecuencia, o None dentro del horizonte."""
    zona = ZoneInfo(politica.zona_horaria)
    local = _local(momento, zona)
    candidatos = {
        momento,
        _inicio_dia(local, zona, 1),
        _inicio_semana(local, zona, 1),
    }
    for intento in _ventana(momento, politica, historial):
        candidatos.add(intento.momento + timedelta(days=7))
    limite = momento + timedelta(days=horizonte_dias)
    for t in sorted(candidatos):
        if t < momento or t > limite:
            continue
        if not evaluar_frecuencia(t, canal, politica, historial):
            return t
    return None
