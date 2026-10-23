"""Hash de contraseñas (bcrypt) y JWT HS256 (ADR-0005)."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import get_settings

_ALGORITMO = "HS256"
_MAX_BYTES_BCRYPT = 72


def _bytes(password: str) -> bytes:
    # bcrypt solo considera los primeros 72 bytes; se trunca de forma explícita y consistente.
    return password.encode("utf-8")[:_MAX_BYTES_BCRYPT]


def hash_password(password: str) -> str:
    sal = bcrypt.gensalt(rounds=get_settings().bcrypt_coste)
    return bcrypt.hashpw(_bytes(password), sal).decode("ascii")


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bytes(password), password_hash.encode("ascii"))
    except ValueError:
        return False


def crear_token(usuario_id: int, rol: str, ahora: datetime | None = None) -> tuple[str, int]:
    """Devuelve (jwt, expires_in en segundos)."""
    settings = get_settings()
    ahora = ahora or datetime.now(UTC)
    expira = ahora + timedelta(minutes=settings.jwt_expiracion_minutos)
    claims = {"sub": str(usuario_id), "rol": rol, "iat": ahora, "exp": expira}
    token = jwt.encode(claims, settings.jwt_secreto, algorithm=_ALGORITMO)
    return token, settings.jwt_expiracion_minutos * 60


def decodificar_token(token: str) -> int | None:
    """Devuelve el id de usuario si el token es válido; None en cualquier otro caso."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secreto,
            algorithms=[_ALGORITMO],
            options={"require": ["exp", "sub"]},
        )
        return int(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
