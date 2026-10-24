"""Filtro de logging que enmascara credenciales en URLs (`token=`, `ticket=`) — defensa en
profundidad: el WebSocket ya no recibe el JWT, pero un cliente antiguo podría enviarlo."""

import logging
import re

_PATRON = re.compile(r"(?i)\b(token|ticket|access_token)=[^&\s\"']+")


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
