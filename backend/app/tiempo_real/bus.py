"""Bus de eventos en tiempo real (ADR-0004, ADR-0017).

`publicar(db, tipo, datos)` NO entrega el evento al instante: lo ata a la transacción de `db`.
- PostgreSQL: `SELECT pg_notify('eventos', json)` dentro de la transacción (PostgreSQL lo entrega
  solo al confirmar; un rollback lo descarta). Cada instancia lo recibe por LISTEN (escucha.py).
- Memoria (SQLite/tests): el evento se acumula en la sesión y se despacha en `after_commit`;
  se descarta en rollback.

El payload solo contiene ids y valores de catálogo, nunca datos personales (< 8000 bytes).
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger("app")
CANAL_PG = "eventos"
MAX_PAYLOAD_BYTES = 7900
_CLAVE = "eventos_pendientes"

Receptor = Callable[[dict[str, Any]], None]


def sobre(tipo: str, datos: dict[str, Any], emitido_en: datetime | None = None) -> dict[str, Any]:
    ahora = (emitido_en or datetime.now(UTC)).astimezone(UTC)
    return {
        "tipo": tipo,
        "datos": datos,
        "emitido_en": ahora.isoformat().replace("+00:00", "Z"),
    }


class BusEventos(Protocol):
    nombre: str

    def publicar(self, db: Session, evento: dict[str, Any]) -> None: ...


class BusMemoria:
    """Acumula en la sesión y despacha a los receptores locales tras el commit."""

    nombre = "memoria"

    def __init__(self) -> None:
        self.receptores: list[Receptor] = []

    def suscribir(self, receptor: Receptor) -> Callable[[], None]:
        self.receptores.append(receptor)
        return lambda: self.receptores.remove(receptor) if receptor in self.receptores else None

    def publicar(self, db: Session, evento: dict[str, Any]) -> None:
        db.info.setdefault(_CLAVE, []).append(evento)

    def despachar(self, evento: dict[str, Any]) -> None:
        for receptor in list(self.receptores):
            try:
                receptor(evento)
            except Exception:  # un receptor roto no debe afectar a la transacción confirmada
                logger.exception("Error al despachar un evento de tiempo real.")


class BusPostgres:
    """`pg_notify` dentro de la transacción; la entrega la hace PostgreSQL al confirmar."""

    nombre = "postgres"

    def publicar(self, db: Session, evento: dict[str, Any]) -> None:
        carga = json.dumps(evento, separators=(",", ":"), ensure_ascii=False)
        if len(carga.encode()) > MAX_PAYLOAD_BYTES:
            logger.error("Evento %s descartado: payload demasiado grande.", evento.get("tipo"))
            return
        db.execute(text("SELECT pg_notify(:canal, :carga)"), {"canal": CANAL_PG, "carga": carga})


_bus: BusEventos | None = None
_ganchos_instalados = False


def _instalar_ganchos() -> None:
    global _ganchos_instalados
    if _ganchos_instalados:
        return

    @event.listens_for(Session, "after_commit")
    def _tras_commit(sesion: Session) -> None:
        eventos = sesion.info.pop(_CLAVE, None)
        bus = _bus
        if eventos and isinstance(bus, BusMemoria):
            for ev in eventos:
                bus.despachar(ev)

    @event.listens_for(Session, "after_soft_rollback")
    def _tras_rollback(sesion: Session, transaccion_previa: Any) -> None:
        # Incluye rollbacks "blandos" (sin transacción DBAPI activa); ignora los de SAVEPOINT.
        if not getattr(transaccion_previa, "nested", False):
            sesion.info.pop(_CLAVE, None)

    _ganchos_instalados = True


def crear_bus(url_bd: str | None = None) -> BusEventos:
    settings = get_settings()
    modo = settings.bus_eventos
    if modo == "auto":
        modo = (
            "postgres" if (url_bd or settings.database_url).startswith("postgresql") else "memoria"
        )
    return BusPostgres() if modo == "postgres" else BusMemoria()


def obtener_bus() -> BusEventos:
    global _bus
    if _bus is None:
        _bus = crear_bus()
        _instalar_ganchos()
    return _bus


def establecer_bus(bus: BusEventos | None) -> None:
    """Sustituye el bus (tests y `lifespan`)."""
    global _bus
    _bus = bus
    if bus is not None:
        _instalar_ganchos()


def publicar(db: Session, tipo: str, datos: dict[str, Any]) -> None:
    obtener_bus().publicar(db, sobre(tipo, datos))
