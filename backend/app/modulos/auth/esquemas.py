from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.modulos.usuarios.esquemas import UsuarioResumen


class LoginPeticion(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginRespuesta(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    usuario: UsuarioResumen
