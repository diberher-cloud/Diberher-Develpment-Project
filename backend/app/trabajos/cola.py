"""Cola de trabajos en BD (ADR-0013 §4): `encolar`, `tomar` (SKIP LOCKED en PostgreSQL),
`ejecutar` y `ejecutar_pendientes` (síncrono, para tests)."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.auditoria import servicio as auditoria
from app.reloj import Reloj
from app.reloj import ahora as ahora_real
from app.tiempo_real import bus
from app.trabajos import registro
from app.trabajos.modelos import Trabajo
from app.trabajos.registro import ErrorTrabajo, ReprogramarTrabajo

logger = logging.getLogger("app")
BACKOFF_BASE_SEGUNDOS = 5
BACKOFF_MAX_SEGUNDOS = 600


def backoff(intentos: int) -> timedelta:
    """5 s · 2^(intentos-1), máximo 600 s."""
    return timedelta(
        seconds=min(BACKOFF_BASE_SEGUNDOS * 2 ** max(intentos - 1, 0), BACKOFF_MAX_SEGUNDOS)
    )


def encolar(
    db: Session,
    tipo: str,
    payload: dict[str, Any],
    *,
    clave_unica: str | None = None,
    disponible_desde: datetime | None = None,
    max_intentos: int = 5,
    ahora: datetime | None = None,
) -> Trabajo:
    """Encola un trabajo (sin commit). Con `clave_unica` ya presente (pendiente) devuelve el
    existente. El payload lleva SOLO ids y catálogos."""
    if clave_unica is not None:
        existente = db.scalar(select(Trabajo).where(Trabajo.clave_unica == clave_unica))
        if existente is not None:
            return existente
    momento = ahora or datetime.now(UTC)
    trabajo = Trabajo(
        tipo=tipo,
        clave_unica=clave_unica,
        payload=payload,
        estado="pendiente",
        intentos=0,
        max_intentos=max_intentos,
        disponible_desde=disponible_desde or momento,
        creado_en=momento,
        actualizado_en=momento,
    )
    try:
        with db.begin_nested():
            db.add(trabajo)
            db.flush()
    except IntegrityError:
        if clave_unica is None:
            raise
        existente = db.scalar(select(Trabajo).where(Trabajo.clave_unica == clave_unica))
        if existente is None:
            raise
        return existente
    return trabajo


def tomar(db: Session, trabajador: str, ahora: datetime, limite: int) -> list[Trabajo]:
    """Toma hasta `limite` trabajos disponibles (o con bloqueo caducado) y confirma.

    PostgreSQL: `FOR UPDATE SKIP LOCKED` (varios workers no se pisan); SQLite ignora la cláusula.
    Libera `clave_unica` para que lleguen trabajos nuevos mientras este se ejecuta.
    """
    filas = list(
        db.scalars(
            select(Trabajo)
            .where(
                or_(
                    and_(Trabajo.estado == "pendiente", Trabajo.disponible_desde <= ahora),
                    and_(Trabajo.estado == "en_proceso", Trabajo.bloqueado_hasta < ahora),
                )
            )
            .order_by(Trabajo.disponible_desde, Trabajo.id)
            .limit(limite)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    bloqueo = timedelta(seconds=get_settings().worker_bloqueo_segundos)
    tomados: list[Trabajo] = []
    for t in filas:
        recuperado = t.estado == "en_proceso"
        t.intentos += 1
        t.clave_unica = None
        t.actualizado_en = ahora
        if recuperado and t.intentos > t.max_intentos:
            # Un bloqueo caducado más veces de las permitidas: el trabajo mata al worker.
            t.ultimo_error = "BloqueoCaducado:AGOTADO"
            registro.cargar_manejadores()
            gancho = registro.AL_AGOTAR.get(t.tipo)
            if gancho is not None:
                try:
                    gancho(db, dict(t.payload or {}), "AGOTADO", ahora)
                except Exception as exc_gancho:
                    logger.error("Gancho de agotamiento falló: %s", type(exc_gancho).__name__)
            _marcar_fallido(db, t, "AGOTADO", ahora)
            continue
        t.estado = "en_proceso"
        t.bloqueado_hasta = ahora + bloqueo
        t.bloqueado_por = trabajador[:80]
        tomados.append(t)
    db.commit()
    return tomados


def _marcar_fallido(db: Session, t: Trabajo, codigo: str, ahora: datetime) -> None:
    t.estado = "fallido"
    t.bloqueado_hasta = None
    t.bloqueado_por = None
    t.actualizado_en = ahora
    auditoria.registrar(
        db,
        "trabajo.fallido",
        None,
        "trabajo",
        t.id,
        {"trabajo_id": t.id, "tipo": t.tipo, "codigo": codigo},
    )
    bus.publicar(db, "trabajo.fallido", {"trabajo_id": t.id, "tipo": t.tipo, "codigo": codigo})


def ejecutar(db_factory: Callable[[], Session], trabajo_id: int, reloj: Reloj) -> None:
    """Ejecuta un trabajo ya tomado en una sesión nueva (reintentos, fallo y auditoría)."""
    registro.cargar_manejadores()
    with db_factory() as db:
        trabajo = db.get(Trabajo, trabajo_id)
        if trabajo is None or trabajo.estado != "en_proceso":
            return
        tipo, payload = trabajo.tipo, dict(trabajo.payload or {})
        ahora = reloj()
        # El bloqueo se renueva al EMPEZAR cada trabajo del lote: otro worker no retoma uno
        # que sigue en curso aunque el lote haya tardado más que `WORKER_BLOQUEO_SEGUNDOS`.
        trabajo.bloqueado_hasta = ahora + timedelta(seconds=get_settings().worker_bloqueo_segundos)
        db.commit()
        manejador = registro.MANEJADORES.get(tipo)
        try:
            if manejador is None:
                raise ErrorTrabajo("TIPO_DESCONOCIDO", transitorio=False)
            manejador(db, payload, ahora)
            trabajo = db.get(Trabajo, trabajo_id)
            assert trabajo is not None
            trabajo.estado = "completado"
            trabajo.completado_en = ahora
            trabajo.actualizado_en = ahora
            trabajo.bloqueado_hasta = None
            trabajo.bloqueado_por = None
            db.commit()
        except ReprogramarTrabajo as rp:
            db.rollback()
            _reprogramar(db, trabajo_id, rp.disponible_desde, ahora)
        except Exception as exc:
            db.rollback()
            _registrar_fallo(db, trabajo_id, exc, payload, ahora)


def restaurar_clave(db: Session, t: Trabajo) -> None:
    """Un trabajo que vuelve a `pendiente` recupera su `clave_unica` (se anuló al tomarlo) salvo
    que ya haya otro pendiente con esa clave."""
    clave = registro.clave_unica_de(t.tipo, t.payload or {})
    if clave is None or t.clave_unica is not None:
        return
    if db.scalar(select(Trabajo.id).where(Trabajo.clave_unica == clave)) is None:
        t.clave_unica = clave


def _reprogramar(db: Session, trabajo_id: int, desde: datetime, ahora: datetime) -> None:
    t = db.get(Trabajo, trabajo_id)
    assert t is not None
    restaurar_clave(db, t)
    t.estado = "pendiente"
    t.disponible_desde = desde
    t.intentos = max(t.intentos - 1, 0)  # no cuenta como intento
    t.bloqueado_hasta = None
    t.bloqueado_por = None
    t.actualizado_en = ahora
    db.commit()


def _registrar_fallo(
    db: Session, trabajo_id: int, exc: Exception, payload: dict[str, Any], ahora: datetime
) -> None:
    t = db.get(Trabajo, trabajo_id)
    assert t is not None
    if isinstance(exc, ErrorTrabajo):
        codigo, transitorio = exc.codigo, exc.transitorio
    else:
        codigo, transitorio = (
            "INESPERADO",
            True,
        )  # excepciones no previstas cuentan como transitorias
    t.ultimo_error = f"{type(exc).__name__}:{codigo}"[:300]
    if not isinstance(exc, ErrorTrabajo):
        logger.error("Trabajo %s (%s) falló: %s", t.id, t.tipo, type(exc).__name__)
    if not transitorio or t.intentos >= t.max_intentos:
        gancho = registro.AL_AGOTAR.get(t.tipo)
        if gancho is not None:
            try:
                gancho(db, payload, codigo, ahora)
            except Exception as exc_gancho:
                db.rollback()
                t = db.get(Trabajo, trabajo_id)
                assert t is not None
                t.ultimo_error = f"{type(exc).__name__}:{codigo}"[:300]
                logger.error("Gancho de agotamiento falló: %s", type(exc_gancho).__name__)
        _marcar_fallido(db, t, codigo, ahora)
    else:
        restaurar_clave(db, t)
        t.estado = "pendiente"
        t.disponible_desde = ahora + backoff(t.intentos)
        t.bloqueado_hasta = None
        t.bloqueado_por = None
        t.actualizado_en = ahora
    db.commit()


def ejecutar_pendientes(db: Session, ahora: datetime | None = None, max_trabajos: int = 100) -> int:
    """Ejecuta de forma síncrona los trabajos disponibles (tests). Devuelve cuántos ejecutó.

    Toma de uno en uno para ver los trabajos que encolan los propios manejadores."""
    from sqlalchemy.orm import sessionmaker

    momento = ahora or ahora_real()
    fabrica = sessionmaker(bind=db.get_bind(), autoflush=True, expire_on_commit=False)
    ejecutados = 0
    while ejecutados < max_trabajos:
        db.commit()  # cierra la transacción de lectura del llamador
        tomados = tomar(db, "ejecutar_pendientes", momento, 1)
        if not tomados:
            break
        for t in tomados:
            ejecutar(fabrica, t.id, lambda: momento)
            ejecutados += 1
    db.commit()
    return ejecutados
