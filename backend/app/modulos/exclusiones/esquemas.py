from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errores import ErrorApp, detalle
from app.tipos import FechaHoraZ

Motivo = Literal["rne", "solicitud_titular", "numero_errado", "manual"]
AplicaA = Literal["venta", "cobranza", "todas"]


class ExclusionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_e164: str
    motivo: Motivo
    aplica_a: AplicaA
    observacion: str | None
    creado_por: int
    creado_en: FechaHoraZ


class ExclusionCrear(BaseModel):
    telefono: Annotated[str, Field(max_length=40)]
    motivo: Motivo
    aplica_a: AplicaA | None = None
    observacion: Annotated[str, Field(max_length=300)] | None = None


class ResultadoImportacionExclusiones(BaseModel):
    total_filas: int
    creadas: int
    duplicadas: int
    invalidas: int
    errores: list[dict]
    errores_truncados: bool


def resolver_aplica_a(motivo: str, aplica_a: str | None) -> str:
    """`rne` sin aplica_a → `venta`; el resto lo exige."""
    if aplica_a is not None:
        return aplica_a
    if motivo == "rne":
        return "venta"
    raise ErrorApp(
        422, "VALIDACION", "Los datos enviados no son válidos.",
        [detalle("aplica_a", "Es obligatorio salvo cuando el motivo es 'rne'.")],
    )  # fmt: skip
