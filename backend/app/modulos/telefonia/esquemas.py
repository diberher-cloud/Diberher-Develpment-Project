from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.tipos import FechaHoraZ


class TokenSalida(BaseModel):
    proveedor: Literal["twilio", "falso"]
    token: str
    identity: str
    expira_en: FechaHoraZ


IdEntrada = Annotated[int, Field(ge=1, le=2**31 - 1)]


class MotivoLlamada(BaseModel):
    codigo: str
    mensaje: str


class SimularLlamada(BaseModel):
    campana_cliente_id: IdEntrada
    telefono_id: IdEntrada


class ResultadoSimulacion(BaseModel):
    llamada_id: int | None
    permitida: bool
    motivos: list[MotivoLlamada]


class EventoSimulacion(BaseModel):
    evento: Literal["contestada", "finalizada"]
    resultado: Literal["completed", "busy", "no-answer", "failed", "canceled"] | None = None
    duracion_segundos: Annotated[int, Field(ge=0, le=86400)] | None = None
