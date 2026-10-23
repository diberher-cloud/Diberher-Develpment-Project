from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, PlainSerializer

from app.tipos import FechaHoraZ

Monto = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json")]


class ClienteSalida(BaseModel):
    id: int
    tipo_documento: str
    numero_documento: str
    nombre: str
    email: str | None
    ciudad: str | None


class TelefonoSalida(BaseModel):
    id: int
    numero_e164: str
    tipo_linea: Literal["movil", "fijo"]
    prioridad: int
    excluido: bool


class CampanaClienteSalida(BaseModel):
    id: int
    estado: Literal["pendiente", "en_gestion", "gestionado", "descartado"]
    intentos: int
    cliente: ClienteSalida
    telefonos: list[TelefonoSalida]
    numero_obligacion: str | None
    saldo_total: Monto | None
    saldo_mora: Monto | None
    dias_mora: int | None
    fecha_vencimiento: date | None
    producto: str | None
    oferta: str | None
    datos_adicionales: dict[str, Any]
    importacion_id: int | None
    creado_en: FechaHoraZ
