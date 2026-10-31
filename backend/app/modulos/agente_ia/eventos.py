"""Eventos de tiempo real `ia.*` (fase-2c.md §6.10). Solo ids y valores de catálogo: nunca
textos, montos de clientes ni números. Los reciben solo administradores y supervisores."""

from sqlalchemy.orm import Session

from app.tiempo_real import bus


def publicar_turno(
    db: Session,
    ref_tipo: str,
    ref_id: int,
    campana_id: int,
    estado: str,
    iteraciones: int = 0,
) -> None:
    bus.publicar(
        db,
        "ia.turno",
        {
            "conversacion_id": ref_id if ref_tipo == "conversacion" else None,
            "llamada_id": ref_id if ref_tipo == "llamada" else None,
            "campana_id": campana_id,
            "estado": estado,
            "iteraciones": iteraciones,
        },
    )


def publicar_accion(
    db: Session,
    ref_tipo: str,
    ref_id: int,
    campana_id: int,
    accion_id: int,
    herramienta: str,
    es_error: bool,
    codigo_error: str | None,
) -> None:
    bus.publicar(
        db,
        "ia.accion",
        {
            "conversacion_id": ref_id if ref_tipo == "conversacion" else None,
            "llamada_id": ref_id if ref_tipo == "llamada" else None,
            "campana_id": campana_id,
            "accion_id": accion_id,
            "herramienta": herramienta,
            "es_error": es_error,
            "codigo_error": codigo_error,
        },
    )


def publicar_alerta(
    db: Session,
    tipo: str,
    nivel: str,
    campana_id: int | None,
    conversacion_id: int | None = None,
) -> None:
    bus.publicar(
        db,
        "ia.alerta",
        {
            "tipo": tipo,
            "nivel": nivel,
            "campana_id": campana_id,
            "conversacion_id": conversacion_id,
        },
    )


def publicar_configuracion(
    db: Session,
    campana_id: int | None,
    activa: bool,
    version: int | None,
    desactivada_motivo: str | None,
) -> None:
    bus.publicar(
        db,
        "ia.configuracion",
        {
            "campana_id": campana_id,
            "activa": activa,
            "version": version,
            "desactivada_motivo": desactivada_motivo,
        },
    )


def publicar_evaluacion(
    db: Session, evaluacion_id: int, estado: str, aprobada: bool | None
) -> None:
    bus.publicar(
        db,
        "ia.evaluacion",
        {"evaluacion_id": evaluacion_id, "estado": estado, "aprobada": aprobada},
    )
