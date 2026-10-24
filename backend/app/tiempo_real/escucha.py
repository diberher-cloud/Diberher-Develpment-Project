"""Escucha de `LISTEN eventos` (solo PostgreSQL): reparte a los sockets de esta instancia."""

import asyncio
import json
import logging

import psycopg

from app.tiempo_real.bus import CANAL_PG
from app.tiempo_real.conexiones import GestorConexiones

logger = logging.getLogger("app")
BACKOFF_INICIAL = 1.0
BACKOFF_MAXIMO = 30.0
SONDEO_SEGUNDOS = 30.0
KEEPALIVES = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


def url_psycopg(url_sqlalchemy: str) -> str:
    """`postgresql+psycopg://...` -> `postgresql://...` (formato libpq)."""
    return url_sqlalchemy.replace("postgresql+psycopg://", "postgresql://", 1)


async def escuchar(url_bd: str, gestor: GestorConexiones) -> None:
    """Bucle con reconexión y backoff exponencial; se detiene al cancelarse la tarea."""
    espera = BACKOFF_INICIAL
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(
                url_psycopg(url_bd), autocommit=True, **KEEPALIVES
            ) as conexion:
                await conexion.execute(f"LISTEN {CANAL_PG}")
                espera = BACKOFF_INICIAL
                while True:
                    async for aviso in conexion.notifies(timeout=SONDEO_SEGUNDOS):
                        try:
                            gestor.repartir(json.loads(aviso.payload))
                        except ValueError:
                            logger.warning("Evento de tiempo real con JSON inválido descartado.")
                    # Sin avisos en SONDEO_SEGUNDOS: comprueba que la conexión sigue viva (si
                    # está rota, el SELECT falla y se reconecta).
                    await conexion.execute("SELECT 1")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Escucha de eventos interrumpida (%s); reintento.", type(exc).__name__)
        await asyncio.sleep(espera)
        espera = min(espera * 2, BACKOFF_MAXIMO)
