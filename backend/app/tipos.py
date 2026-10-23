"""Tipos compartidos de esquemas (serialización de fechas-hora en UTC con sufijo Z)."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import PlainSerializer


def a_utc_z(valor: datetime) -> str:
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC).isoformat().replace("+00:00", "Z")


FechaHoraZ = Annotated[datetime, PlainSerializer(a_utc_z, return_type=str, when_used="json")]
