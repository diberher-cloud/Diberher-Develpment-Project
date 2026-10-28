"""Gestor de conexiones WebSocket: reparto por rol y desconexión de agentes (ADR-0004)."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app")

TIPOS_DE_AGENTE = {"agente.estado", "llamada.estado"}
TIPOS_DE_CONVERSACION = {"conversacion.mensaje", "conversacion.estado"}
MAX_COLA = 1000


@dataclass(eq=False)
class Conexion:
    usuario_id: int
    rol: str
    cola: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_COLA)
    )
    desbordada: bool = False

    def encolar(self, evento: dict[str, Any]) -> None:
        """Se ejecuta en el bucle del socket; si la cola se llena, marca la conexión para cerrarla
        (un cliente lento no puede acumular memoria sin límite)."""
        try:
            self.cola.put_nowait(evento)
        except asyncio.QueueFull:
            self.desbordada = True


def debe_recibir(conexion: Conexion, evento: dict[str, Any]) -> bool:
    """Administrador/supervisor reciben todo; el agente, lo propio, los `consola.registro` y los
    `atencion.cola` (solo ids); `trabajo.fallido` nunca llega al agente."""
    if conexion.rol in ("administrador", "supervisor"):
        return True
    tipo = evento.get("tipo")
    if tipo in ("consola.registro", "atencion.cola"):
        return True
    if tipo in TIPOS_DE_CONVERSACION:
        datos = evento.get("datos", {})
        return conexion.usuario_id in (
            datos.get("usuario_asignado_id"),
            datos.get("usuario_anterior_id"),
        )
    if tipo in TIPOS_DE_AGENTE:
        return evento.get("datos", {}).get("usuario_id") == conexion.usuario_id
    return False


class GestorConexiones:
    def __init__(self) -> None:
        self.conexiones: set[Conexion] = set()
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._pendientes_desconexion: dict[int, asyncio.Task[None]] = {}

    # ---- registro -----------------------------------------------------------------------
    def conectar(self, usuario_id: int, rol: str) -> Conexion:
        self._bucle = asyncio.get_running_loop()
        conexion = Conexion(usuario_id, rol)
        self.conexiones.add(conexion)
        tarea = self._pendientes_desconexion.pop(usuario_id, None)
        if tarea is not None:
            tarea.cancel()
        return conexion

    def desconectar(self, conexion: Conexion) -> bool:
        """Quita la conexión. Devuelve True si era la última del usuario."""
        self.conexiones.discard(conexion)
        return not self.tiene_conexion(conexion.usuario_id)

    def tiene_conexion(self, usuario_id: int) -> bool:
        return any(c.usuario_id == usuario_id for c in self.conexiones)

    # ---- reparto (seguro desde otros hilos) ---------------------------------------------
    def repartir(self, evento: dict[str, Any]) -> None:
        bucle = self._bucle
        if bucle is None or bucle.is_closed():
            return
        for conexion in list(self.conexiones):
            if debe_recibir(conexion, evento):
                try:
                    bucle.call_soon_threadsafe(conexion.encolar, evento)
                except RuntimeError:  # bucle cerrado
                    return

    # ---- desconexión prolongada ---------------------------------------------------------
    def programar_desconexion(
        self, usuario_id: int, segundos: float, accion: Callable[[int], None]
    ) -> None:
        """Si en `segundos` el usuario no reconecta, ejecuta `accion(usuario_id)` en un hilo."""
        anterior = self._pendientes_desconexion.pop(usuario_id, None)
        if anterior is not None:
            anterior.cancel()

        async def _esperar() -> None:
            try:
                await asyncio.sleep(segundos)
                if not self.tiene_conexion(usuario_id):
                    await asyncio.to_thread(accion, usuario_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error al marcar al agente como desconectado.")
            finally:
                if self._pendientes_desconexion.get(usuario_id) is asyncio.current_task():
                    self._pendientes_desconexion.pop(usuario_id, None)

        self._pendientes_desconexion[usuario_id] = asyncio.get_running_loop().create_task(
            _esperar()
        )


gestor = GestorConexiones()
