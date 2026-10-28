"""Worker de trabajos: `python -m app.worker [--healthcheck]` (ADR-0013, fase-2b.md §4.7).

Bucle: latido → trabajos periódicos → tomar un lote → ejecutar en serie → dormir si no hubo
trabajo. SIGTERM/SIGINT: termina el trabajo en curso, devuelve a la cola los ya tomados y sale
con 0. Con SQLite el bus en memoria del worker no llega a la API (sin tiempo real desde el
worker); con PostgreSQL publica con `pg_notify`.
"""

import argparse
import logging
import os
import signal
import socket
import sys
import threading
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import (
    logging_seguro,
    registro_modelos,  # noqa: F401  (registra los modelos)
)
from app.config import VERSION, get_settings
from app.db import SessionLocal
from app.reloj import Reloj, ahora
from app.tiempo_real import bus
from app.trabajos import cola, periodicos, registro
from app.trabajos.modelos import LatidoWorker, Trabajo

logger = logging.getLogger("app.worker")
LATIDO_MAX_SEGUNDOS = 60


def identificador() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"[:80]


def registrar_latido(db: Session, trabajador: str, momento) -> None:
    """Upsert del latido (una fila por trabajador). Confirma."""
    fila = db.get(LatidoWorker, trabajador)
    if fila is None:
        db.add(
            LatidoWorker(
                trabajador=trabajador, iniciado_en=momento, ultimo_latido=momento, version=VERSION
            )
        )
    else:
        fila.ultimo_latido = momento
    db.commit()


def hay_latido_reciente(db: Session, momento) -> bool:
    ultimo = db.scalar(select(func.max(LatidoWorker.ultimo_latido)))
    return ultimo is not None and ultimo >= momento - timedelta(seconds=LATIDO_MAX_SEGUNDOS)


def healthcheck(reloj: Reloj = ahora, fabrica: Callable[[], Session] = SessionLocal) -> int:
    try:
        with fabrica() as db:
            return 0 if hay_latido_reciente(db, reloj()) else 1
    except Exception as exc:
        logger.error("Healthcheck del worker falló: %s", type(exc).__name__)
        return 1


def devolver_a_la_cola(db: Session, ids: list[int], momento) -> None:
    """Los trabajos tomados que no se ejecutaron vuelven a `pendiente` sin gastar intento."""
    for t in db.scalars(select(Trabajo).where(Trabajo.id.in_(ids), Trabajo.estado == "en_proceso")):
        t.estado = "pendiente"
        t.intentos = max(t.intentos - 1, 0)
        t.bloqueado_hasta = None
        t.bloqueado_por = None
        t.actualizado_en = momento
    db.commit()


class Trabajador:
    def __init__(
        self,
        fabrica: Callable[[], Session] = SessionLocal,
        reloj: Reloj = ahora,
        nombre: str | None = None,
    ) -> None:
        self.fabrica = fabrica
        self.reloj = reloj
        self.nombre = nombre or identificador()
        self.parar = threading.Event()
        self.settings = get_settings()

    def vuelta(self) -> int:
        """Una iteración del bucle. Devuelve cuántos trabajos ejecutó."""
        momento = self.reloj()
        with self.fabrica() as db:
            registrar_latido(db, self.nombre, momento)
            periodicos.programar(db, momento)
            db.commit()
        with self.fabrica() as db:
            ids = [t.id for t in cola.tomar(db, self.nombre, momento, self.settings.worker_lote)]
        ejecutados = 0
        for posicion, trabajo_id in enumerate(ids):
            if self.parar.is_set():
                with self.fabrica() as db:
                    devolver_a_la_cola(db, ids[posicion:], self.reloj())
                break
            cola.ejecutar(self.fabrica, trabajo_id, self.reloj)
            ejecutados += 1
        return ejecutados

    def liberar_propios(self) -> int:
        """Al arrancar: los trabajos `en_proceso` bloqueados por un worker con mi mismo id
        (reinicio del contenedor con el mismo pid) vuelven a `pendiente` sin esperar al bloqueo."""
        with self.fabrica() as db:
            propios = list(
                db.scalars(
                    select(Trabajo).where(
                        Trabajo.estado == "en_proceso", Trabajo.bloqueado_por == self.nombre
                    )
                )
            )
            for t in propios:
                cola.restaurar_clave(db, t)
                t.estado = "pendiente"
                t.bloqueado_hasta = None
                t.bloqueado_por = None
                t.actualizado_en = self.reloj()
            db.commit()
            return len(propios)

    def ejecutar(self) -> None:
        registro.cargar_manejadores()
        self.liberar_propios()
        logger.info("Worker %s iniciado.", self.nombre)
        while not self.parar.is_set():
            try:
                hubo = self.vuelta()
            except Exception as exc:  # BD caída, etc.: se reintenta tras la espera
                logger.error("Error en la vuelta del worker: %s", type(exc).__name__)
                hubo = 0
            if not hubo:
                self.parar.wait(self.settings.worker_intervalo_segundos)
        logger.info("Worker %s detenido.", self.nombre)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--healthcheck", action="store_true", help="sale 0 si hay latido reciente")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return healthcheck()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging_seguro.instalar()
    bus.establecer_bus(bus.crear_bus())
    trabajador = Trabajador()

    def _senal(_numero: int, _marco: object) -> None:
        trabajador.parar.set()

    signal.signal(signal.SIGTERM, _senal)
    signal.signal(signal.SIGINT, _senal)
    trabajador.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
