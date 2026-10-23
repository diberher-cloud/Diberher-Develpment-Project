"""Modelos Pydantic de la política de cumplimiento (§4.8). Módulo puro."""

import re
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_HORA = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def parsear_hora(valor: str) -> time:
    m = _HORA.fullmatch(valor)
    if not m:
        raise ValueError("Debe tener formato HH:MM de 24 horas.")
    return time(int(m[1]), int(m[2]))


class Franja(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inicio: str
    fin: str

    @field_validator("inicio", "fin")
    @classmethod
    def _hora_valida(cls, v: str) -> str:
        parsear_hora(v)
        return v

    @model_validator(mode="after")
    def _orden(self) -> "Franja":
        if parsear_hora(self.inicio) >= parsear_hora(self.fin):
            raise ValueError("inicio debe ser anterior a fin.")
        return self

    @property
    def hora_inicio(self) -> time:
        return parsear_hora(self.inicio)

    @property
    def hora_fin(self) -> time:
        return parsear_hora(self.fin)


class Franjas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lunes: list[Franja]
    martes: list[Franja]
    miercoles: list[Franja]
    jueves: list[Franja]
    viernes: list[Franja]
    sabado: list[Franja]
    domingo: list[Franja]

    @model_validator(mode="after")
    def _sin_solapes(self) -> "Franjas":
        for dia in DIAS:
            franjas = getattr(self, dia)
            for anterior, actual in zip(franjas, franjas[1:], strict=False):
                if actual.hora_inicio < anterior.hora_fin:
                    raise ValueError(
                        f"Las franjas de '{dia}' deben estar ordenadas y no solaparse."
                    )
        return self


class Frecuencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_contactos_dia: int = Field(ge=1, le=10)
    max_canales_semana: int = Field(ge=1, le=10)
    semana: Literal["calendario", "movil_7_dias"]
    solo_tras_contacto_directo: bool
    contar_intentos_sin_contacto: bool = True


class Entrantes(BaseModel):
    """Tratamiento de los contactos iniciados por el cliente (ADR-0012 §3)."""

    model_config = ConfigDict(extra="forbid")

    responder_fuera_de_franja: bool = True
    establecen_contacto_directo: bool = True


class PoliticaCumplimiento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zona_horaria: str
    franjas: Franjas
    permitir_festivos: bool
    frecuencia: Frecuencia
    entrantes: Entrantes = Field(default_factory=Entrantes)

    @field_validator("zona_horaria")
    @classmethod
    def _zona(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("Zona horaria inexistente.") from exc
        return v

    def franjas_del_dia(self, dia: str) -> list[Franja]:
        return getattr(self.franjas, dia)


def politica_por_defecto() -> dict:
    """Configuración por defecto (Fase 1 + campos nuevos de la Fase 2A, ADR-0012)."""
    semana = [{"inicio": "07:00", "fin": "19:00"}]
    return {
        "zona_horaria": "America/Bogota",
        "franjas": {
            "lunes": semana,
            "martes": semana,
            "miercoles": semana,
            "jueves": semana,
            "viernes": semana,
            "sabado": [{"inicio": "08:00", "fin": "15:00"}],
            "domingo": [],
        },
        "permitir_festivos": False,
        "frecuencia": {
            "max_contactos_dia": 1,
            "max_canales_semana": 1,
            "semana": "calendario",
            "solo_tras_contacto_directo": True,
            "contar_intentos_sin_contacto": True,
        },
        "entrantes": {
            "responder_fuera_de_franja": True,
            "establecen_contacto_directo": True,
        },
    }
