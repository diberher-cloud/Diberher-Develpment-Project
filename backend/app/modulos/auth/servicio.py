from sqlalchemy.orm import Session

from app.errores import ErrorApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.auth.esquemas import LoginRespuesta
from app.modulos.usuarios.esquemas import UsuarioResumen
from app.modulos.usuarios.servicio import obtener_por_email
from app.seguridad import crear_token, hash_password, verificar_password

_HASH_FALSO: str | None = None


def _hash_falso() -> str:
    """Hash para igualar tiempos cuando el usuario no existe."""
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = hash_password("contrasena-inexistente")
    return _HASH_FALSO


def login(db: Session, email: str, password: str) -> LoginRespuesta:
    usuario = obtener_por_email(db, email)
    if usuario is None:
        verificar_password(password, _hash_falso())
        valido = False
    else:
        valido = verificar_password(password, usuario.password_hash) and usuario.activo
    if not valido:
        auditoria.registrar(
            db, "auth.login_fallido", None, "usuario", usuario.id if usuario else None
        )
        db.commit()
        raise ErrorApp(401, "CREDENCIALES_INVALIDAS", "Credenciales inválidas.")
    assert usuario is not None
    token, expira = crear_token(usuario.id, usuario.rol)
    auditoria.registrar(db, "auth.login_ok", usuario.id, "usuario", usuario.id)
    db.commit()
    return LoginRespuesta(
        access_token=token, expires_in=expira, usuario=UsuarioResumen.model_validate(usuario)
    )
