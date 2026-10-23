from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.tipos import FechaHoraZ

TipoCampana = Literal["venta", "cobranza"]
EstadoCampana = Literal["borrador", "activa", "pausada", "finalizada"]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
Guion = Annotated[str, Field(max_length=20000)]
MaxIntentos = Annotated[int, Field(ge=1, le=10)]
Intervalo = Annotated[int, Field(ge=5, le=10080)]


class CampanaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: TipoCampana
    descripcion: str | None
    estado: EstadoCampana
    fecha_inicio: date | None
    fecha_fin: date | None
    guion: str | None
    max_intentos: int
    intervalo_reintento_minutos: int
    total_clientes: int = 0
    creado_por: int
    creado_en: FechaHoraZ
    actualizado_en: FechaHoraZ


def _validar_fechas(inicio: date | None, fin: date | None) -> None:
    if inicio and fin and fin < inicio:
        raise ValueError("fecha_fin no puede ser anterior a fecha_inicio.")


class CampanaCrear(BaseModel):
    nombre: Nombre
    tipo: TipoCampana
    descripcion: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    guion: Guion | None = None
    max_intentos: MaxIntentos = 3
    intervalo_reintento_minutos: Intervalo = 60

    @model_validator(mode="after")
    def _fechas(self) -> "CampanaCrear":
        _validar_fechas(self.fecha_inicio, self.fecha_fin)
        return self


class CampanaActualizar(BaseModel):
    """`tipo` no es editable: al ser `extra=forbid`, enviarlo produce 422 con detalle en `tipo`."""

    model_config = ConfigDict(extra="forbid")

    nombre: Nombre | None = None
    descripcion: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    guion: Guion | None = None
    max_intentos: MaxIntentos | None = None
    intervalo_reintento_minutos: Intervalo | None = None
    estado: EstadoCampana | None = None
