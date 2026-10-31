"""Agregado de resultados de la evaluación (fase-2c.md §7.5)."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.config import get_settings
from app.modulos.agente_ia.evaluacion.casos import es_categoria_estricta


@dataclass
class ResultadoCaso:
    id: str
    categoria: str
    aprobado: bool
    fallos: list[str] = field(default_factory=list)
    costo_usd: Decimal = Decimal(0)
    input_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    duracion_ms: int = 0

    def como_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "categoria": self.categoria,
            "aprobado": self.aprobado,
            "fallos": self.fallos,
        }


def agregar(resultados: list[ResultadoCaso], modo: str) -> dict[str, Any]:
    por_categoria: dict[str, dict[str, int]] = {}
    for r in resultados:
        c = por_categoria.setdefault(r.categoria, {"total": 0, "aprobados": 0})
        c["total"] += 1
        c["aprobados"] += int(r.aprobado)
    costo = sum((r.costo_usd for r in resultados), Decimal(0))
    entrada = sum(r.input_tokens for r in resultados)
    lectura = sum(r.cache_read for r in resultados)
    escritura = sum(r.cache_creation for r in resultados)
    total = entrada + lectura + escritura
    return {
        "total": len(resultados),
        "aprobados": sum(r.aprobado for r in resultados),
        "por_categoria": por_categoria,
        "costo_usd": f"{costo:.6f}",
        "tasa_cache": round(lectura / total, 4) if modo == "online" and total else None,
        "duracion_ms": sum(r.duracion_ms for r in resultados),
    }


def aprobada(resultados: list[ResultadoCaso], modo: str, completa: bool = True) -> bool:
    """Offline: 100 %. Online: 100 % en las categorías estrictas y >= umbral en el resto."""
    if not resultados:
        return False
    if modo == "offline":
        return all(r.aprobado for r in resultados)
    estrictos = [r for r in resultados if es_categoria_estricta(r.categoria)]
    resto = [r for r in resultados if not es_categoria_estricta(r.categoria)]
    if not all(r.aprobado for r in estrictos):
        return False
    umbral = get_settings().ia_umbral_online_negociacion
    return not resto or sum(r.aprobado for r in resto) / len(resto) >= umbral
