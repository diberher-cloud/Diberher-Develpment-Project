from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.tipos import FechaHoraZ

Rol = Literal["administrador", "supervisor", "agente"]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Password = Annotated[str, Field(min_length=10, max_length=128)]


class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nombre: str
    rol: Rol
    activo: bool
    creado_en: FechaHoraZ | None = None
    actualizado_en: FechaHoraZ | None = None


class UsuarioResumen(BaseModel):
    """Versión sin fechas (login / me)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nombre: str
    rol: Rol
    activo: bool


class UsuarioCrear(BaseModel):
    email: EmailStr
    nombre: Nombre
    rol: Rol
    password: Password

    @field_validator("email")
    @classmethod
    def _minusculas(cls, v: str) -> str:
        return v.lower()


class UsuarioActualizar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: Nombre | None = None
    rol: Rol | None = None
    activo: bool | None = None
    password: Password | None = None
