"""Registro de auditoría. No hace commit: forma parte de la transacción del llamador.

El `detalle` NUNCA debe contener datos personales (documentos, teléfonos, emails): solo ids,
contadores y valores de catálogo (ADR-0008).
"""

from typing import Any

from sqlalchemy.orm import Session

from app.modulos.auditoria.modelos import Auditoria


def registrar(
    db: Session,
    accion: str,
    usuario_id: int | None = None,
    entidad: str | None = None,
    entidad_id: int | str | None = None,
    detalle: dict[str, Any] | None = None,
) -> Auditoria:
    fila = Auditoria(
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=None if entidad_id is None else str(entidad_id),
        detalle=detalle or {},
    )
    db.add(fila)
    return fila
