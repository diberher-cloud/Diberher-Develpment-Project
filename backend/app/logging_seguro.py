"""Filtro de logging que enmascara credenciales y datos personales en URLs (`token=`,
`ticket=`, `numero=`, `q=`...) — defensa en
profundidad: el WebSocket ya no recibe el JWT, pero un cliente antiguo podría enviarlo."""

import logging
import re

# Credenciales y parámetros de query con datos personales (la query aparece en el log de acceso).
_PATRON = re.compile(
    r"(?i)\b(token|ticket|access_token|numero|telefono|q|documento|numero_documento|email)"
    r"=[^&\s\"']+"
)


class MascaraCredencialesFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensaje = record.getMessage()
        except Exception:  # formato inválido: no se pierde el registro
            return True
        enmascarado = _PATRON.sub(r"\1=***", mensaje)
        if enmascarado != mensaje:
            record.msg = enmascarado
            record.args = ()
        return True


def instalar() -> None:
    for nombre in ("uvicorn.error", "uvicorn.access", "uvicorn"):
        logger = logging.getLogger(nombre)
        if not any(isinstance(f, MascaraCredencialesFilter) for f in logger.filters):
            logger.addFilter(MascaraCredencialesFilter())
