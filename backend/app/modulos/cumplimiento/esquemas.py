from datetime import UTC, date
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.tipos import FechaHoraZ

TipoCampana = Literal["venta", "cobranza"]


class PoliticaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo_campana: TipoCampana
    version: int
    activa: bool
    configuracion: dict[str, Any]
    creado_por: int | None
    creado_en: FechaHoraZ


class FestivoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    nombre: str
    origen: Literal["calculado", "manual"]
    activo: bool


Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class FestivoCrear(BaseModel):
    fecha: date
    nombre: Nombre


class FestivoActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activo: bool | None = None
    nombre: Nombre | None = None


class GenerarFestivosPeticion(BaseModel):
    anio: Annotated[int, Field(ge=1984, le=2100)]


class GenerarFestivosRespuesta(BaseModel):
    anio: int
    creados: int
    existentes: int


class EvaluarPeticion(BaseModel):
    tipo_campana: TipoCampana
    momento: AwareDatetime | None = None

    @field_validator("momento")
    @classmethod
    def _rango(cls, v):
        if v is not None:
            try:
                anio = v.astimezone(UTC).year
            except (OverflowError, ValueError):
                anio = 0
            if not 1984 <= anio <= 2100:
                raise ValueError("El momento debe estar entre los años 1984 y 2100.")
        return v


class MotivoSalida(BaseModel):
    codigo: Literal["FESTIVO", "DIA_SIN_FRANJA", "FUERA_DE_FRANJA"]
    mensaje: str


class EvaluarRespuesta(BaseModel):
    permitido: bool
    motivos: list[MotivoSalida]
    momento_local: str
    proxima_ventana_inicio: str | None
    politica_version: int
