"""Motor de cumplimiento PURO: franjas horarias + festivos (ADR-0002).

Sin E/S ni reloj: el llamador inyecta el momento.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.modulos.cumplimiento.politica import DIAS, PoliticaCumplimiento

DiaSemana = Literal["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


@dataclass(frozen=True)
class Motivo:
    codigo: Literal["FESTIVO", "DIA_SIN_FRANJA", "FUERA_DE_FRANJA"]
    mensaje: str


@dataclass(frozen=True)
class ResultadoEvaluacion:
    permitido: bool
    motivos: tuple[Motivo, ...]
    momento_local: datetime
    proxima_ventana_inicio: datetime | None


def _a_local(momento: datetime, politica: PoliticaCumplimiento) -> datetime:
    if momento.tzinfo is None or momento.utcoffset() is None:
        raise ValueError("El momento debe incluir zona horaria.")
    try:
        return momento.astimezone(ZoneInfo(politica.zona_horaria))
    except OverflowError as exc:
        raise ValueError("El momento está fuera del rango de fechas soportado.") from exc


def _es_festivo_bloqueante(
    dia: date, politica: PoliticaCumplimiento, festivos: Mapping[date, str]
) -> bool:
    return dia in festivos and not politica.permitir_festivos


def evaluar_horario(
    momento: datetime, politica: PoliticaCumplimiento, festivos: Mapping[date, str]
) -> ResultadoEvaluacion:
    local = _a_local(momento, politica)
    dia = DIAS[local.weekday()]
    motivos: list[Motivo] = []

    if _es_festivo_bloqueante(local.date(), politica, festivos):
        motivos.append(
            Motivo("FESTIVO", f"{local.date().isoformat()} es festivo ({festivos[local.date()]}).")
        )
    franjas = politica.franjas_del_dia(dia)
    if not franjas:
        motivos.append(Motivo("DIA_SIN_FRANJA", f"El día '{dia}' no tiene franjas habilitadas."))
    elif not any(f.hora_inicio <= local.time() < f.hora_fin for f in franjas):
        motivos.append(
            Motivo(
                "FUERA_DE_FRANJA",
                f"{local.strftime('%H:%M')} está fuera de las franjas permitidas para '{dia}'.",
            )
        )

    permitido = not motivos
    proxima = None if permitido else proxima_ventana(momento, politica, festivos)
    return ResultadoEvaluacion(permitido, tuple(motivos), local, proxima)


def proxima_ventana(
    momento: datetime,
    politica: PoliticaCumplimiento,
    festivos: Mapping[date, str],
    horizonte_dias: int = 14,
) -> datetime | None:
    """Instante más temprano >= momento en que la evaluación sería permitida, o None."""
    local = _a_local(momento, politica)
    zona = ZoneInfo(politica.zona_horaria)
    for desplazamiento in range(horizonte_dias + 1):
        try:
            dia = local.date() + timedelta(days=desplazamiento)
        except OverflowError:
            return None
        if _es_festivo_bloqueante(dia, politica, festivos):
            continue
        for franja in politica.franjas_del_dia(DIAS[dia.weekday()]):
            inicio = datetime.combine(dia, franja.hora_inicio, tzinfo=zona)
            fin = datetime.combine(dia, franja.hora_fin, tzinfo=zona)
            if inicio >= local:
                return inicio
            if inicio <= local < fin:
                return local
    return None
