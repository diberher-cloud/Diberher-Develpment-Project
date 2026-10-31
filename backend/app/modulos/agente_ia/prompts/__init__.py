"""Prompt de sistema por canal y versión (fase-2c.md §4.3). Las versiones publicadas no se
editan: un cambio de texto exige un archivo nuevo y una versión nueva."""

from functools import lru_cache
from pathlib import Path

from app.config import get_settings

VERSIONES: dict[str, tuple[int, ...]] = {"chat": (1,)}
_DIRECTORIO = Path(__file__).parent


def ultima_version(canal: str) -> int:
    return VERSIONES[canal][-1]


@lru_cache
def _plantilla(canal: str, version: int) -> str:
    if version not in VERSIONES.get(canal, ()):
        raise ValueError(f"Versión de prompt desconocida: {canal} v{version}.")
    return (_DIRECTORIO / f"sistema_{canal}_v{version}.md").read_text(encoding="utf-8")


def cargar_sistema(canal: str, version: int, empresa: str | None = None) -> str:
    """Texto fijo con `{empresa}` sustituido por el nombre de la empresa del despliegue; nada
    más varía (fechas y datos del cliente van en mensajes de contexto, no aquí)."""
    nombre = empresa if empresa is not None else get_settings().empresa_nombre
    return _plantilla(canal, version).replace("{empresa}", nombre)
