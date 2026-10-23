from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.tipos import FechaHoraZ

Severidad = Literal["error", "advertencia"]


class ErrorImportacionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fila: int
    campo: str | None
    codigo: str
    mensaje: str
    severidad: Severidad


class ImportacionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campana_id: int
    nombre_archivo: str
    estado: Literal["completada", "fallida"]
    total_filas: int
    filas_importadas: int
    filas_duplicadas: int
    filas_invalidas: int
    filas_excluidas: int
    creado_por: int
    creado_en: FechaHoraZ


class ImportacionDetalleSalida(ImportacionSalida):
    errores: list[ErrorImportacionSalida]
    errores_truncados: bool
