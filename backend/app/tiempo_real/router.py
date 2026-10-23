"""WebSocket `GET /api/v1/ws?token=<jwt>` (§4.10)."""

import asyncio
import contextlib
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI, WebSocket
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_db
from app.modulos.usuarios.modelos import Usuario
from app.reloj import Reloj, get_reloj
from app.seguridad import decodificar_token_con_exp
from app.tiempo_real.bus import sobre
from app.tiempo_real.conexiones import gestor

router = APIRouter(tags=["tiempo real"])
CIERRE_NO_AUTENTICADO = 4401


@contextlib.contextmanager
def sesion_de(app: FastAPI) -> Iterator[Any]:
    """Sesión de BD respetando `dependency_overrides[get_db]` (los tests la sustituyen)."""
    proveedor = app.dependency_overrides.get(get_db, get_db)
    generador = proveedor()
    db = next(generador)
    try:
        yield db
    finally:
        generador.close()


def reloj_de(app: FastAPI) -> Reloj:
    return app.dependency_overrides.get(get_reloj, get_reloj)()


def _cargar(app: FastAPI, usuario_id: int) -> tuple[int, str] | None:
    with sesion_de(app) as db:
        usuario = db.get(Usuario, usuario_id)
        if usuario is None or not usuario.activo:
            return None
        return usuario.id, usuario.rol


def _marcar_desconectado(app: FastAPI, usuario_id: int) -> None:
    from app.modulos.consola import estado as estado_agente

    with sesion_de(app) as db:
        estado_agente.desconectar_por_inactividad(db, usuario_id, reloj_de(app)())


@router.websocket("/ws")
async def ws(websocket: WebSocket, token: str | None = None) -> None:
    await websocket.accept()
    decodificado = decodificar_token_con_exp(token) if token else None
    cargado = (
        await run_in_threadpool(_cargar, websocket.app, decodificado[0]) if decodificado else None
    )
    if decodificado is None or cargado is None:
        await websocket.close(code=CIERRE_NO_AUTENTICADO)
        return
    usuario_id, rol = cargado
    expira = decodificado[1]

    conexion = gestor.conectar(usuario_id, rol)
    recibir: asyncio.Task[Any] | None = None
    entregar: asyncio.Task[Any] | None = None
    try:
        await websocket.send_json(sobre("conexion.lista", {"usuario_id": usuario_id, "rol": rol}))
        recibir = asyncio.ensure_future(websocket.receive())
        entregar = asyncio.ensure_future(conexion.cola.get())
        while True:
            restante = max(expira - time.time(), 0)
            hechas, _ = await asyncio.wait(
                {recibir, entregar}, timeout=restante, return_when=asyncio.FIRST_COMPLETED
            )
            if not hechas:  # el token venció
                await websocket.close(code=CIERRE_NO_AUTENTICADO)
                break
            if recibir in hechas:
                mensaje = recibir.result()
                if mensaje["type"] == "websocket.disconnect":
                    break
                if _es_ping(mensaje.get("text")):
                    await websocket.send_json(sobre("pong", {}))
                recibir = asyncio.ensure_future(websocket.receive())
            if entregar in hechas:
                await websocket.send_json(entregar.result())
                entregar = asyncio.ensure_future(conexion.cola.get())
    except Exception:  # cliente caído a mitad de envío, etc.
        pass
    finally:
        for tarea in (recibir, entregar):
            if tarea is not None and not tarea.done():
                tarea.cancel()
        ultima = gestor.desconectar(conexion)
        if ultima and rol == "agente":
            gestor.programar_desconexion(
                usuario_id,
                get_settings().consola_desconexion_segundos,
                lambda uid: _marcar_desconectado(websocket.app, uid),
            )


def _es_ping(texto: str | None) -> bool:
    if not texto:
        return False
    import json

    try:
        cuerpo = json.loads(texto)
    except ValueError:
        return False
    return isinstance(cuerpo, dict) and cuerpo.get("tipo") == "ping"
