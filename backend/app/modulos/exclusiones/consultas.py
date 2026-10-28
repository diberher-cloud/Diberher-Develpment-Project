"""Consultas de exclusiones aplicables por canal (ADR-0012).

Aplicabilidad: voz → `canal IN ('todos','voz')`; WhatsApp → `canal IN ('todos','whatsapp')`;
siempre `aplica_a IN (tipo_campana, 'todas')`.
"""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.exclusiones.modelos import Exclusion

CanalConsulta = Literal["voz", "whatsapp"]


def canales_aplicables(canal: CanalConsulta) -> tuple[str, str]:
    return ("todos", canal)


def exclusiones_aplicables(
    db: Session, numeros: set[str], tipo_campana: str, canal: CanalConsulta = "voz"
) -> dict[str, Exclusion]:
    """Primera exclusión (por id) aplicable a cada número."""
    if not numeros:
        return {}
    filas = db.scalars(
        select(Exclusion)
        .where(
            Exclusion.numero_e164.in_(numeros),
            Exclusion.aplica_a.in_((tipo_campana, "todas")),
            Exclusion.canal.in_(canales_aplicables(canal)),
        )
        .order_by(Exclusion.id)
    )
    resultado: dict[str, Exclusion] = {}
    for f in filas:
        resultado.setdefault(f.numero_e164, f)
    return resultado
