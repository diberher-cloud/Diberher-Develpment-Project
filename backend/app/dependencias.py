"""Dependencias de autenticación y autorización (ADR-0005)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.errores import ErrorApp
from app.modulos.usuarios.modelos import Usuario
from app.seguridad import decodificar_token

_bearer = HTTPBearer(auto_error=False)


def usuario_actual(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    no_autenticado = ErrorApp(401, "NO_AUTENTICADO", "No autenticado.")
    if credenciales is None:
        raise no_autenticado
    usuario_id = decodificar_token(credenciales.credentials)
    if usuario_id is None:
        raise no_autenticado
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.activo:
        raise no_autenticado
    return usuario


def requiere_rol(*roles: str) -> Callable[..., Usuario]:
    """Dependencia que exige uno de `roles` (rol efectivo leído de la BD)."""

    def _dependencia(usuario: Annotated[Usuario, Depends(usuario_actual)]) -> Usuario:
        if usuario.rol not in roles:
            raise ErrorApp(403, "PERMISO_DENEGADO", "No tiene permiso para esta operación.")
        return usuario

    return _dependencia


ADMIN = "administrador"
SUPERVISOR = "supervisor"
AGENTE = "agente"
