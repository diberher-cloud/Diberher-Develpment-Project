"""Reloj inyectable: toda decisión que depende de la hora usa `ahora()` (UTC con zona).

Los endpoints reciben el reloj con `Depends(get_reloj)`; los tests lo sobrescriben con
`app.dependency_overrides[get_reloj] = lambda: lambda: datetime(...)`.
"""

from collections.abc import Callable
from datetime import UTC, datetime

Reloj = Callable[[], datetime]


def ahora() -> datetime:
    return datetime.now(UTC)


def get_reloj() -> Reloj:
    return ahora
