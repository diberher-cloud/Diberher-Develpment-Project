from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import usuario_actual
from app.modulos.auth import servicio
from app.modulos.auth.esquemas import LoginPeticion, LoginRespuesta
from app.modulos.usuarios.esquemas import UsuarioResumen
from app.modulos.usuarios.modelos import Usuario

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginRespuesta)
def login(datos: LoginPeticion, db: Annotated[Session, Depends(get_db)]) -> LoginRespuesta:
    return servicio.login(db, datos.email, datos.password)


@router.get("/me", response_model=UsuarioResumen)
def me(usuario: Annotated[Usuario, Depends(usuario_actual)]) -> Usuario:
    return usuario
