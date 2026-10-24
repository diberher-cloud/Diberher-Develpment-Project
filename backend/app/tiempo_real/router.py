"""WebSocket `GET /api/v1/ws?ticket=<ticket>` y `POST /api/v1/ws/ticket` (§4.10, revisión B3)."""

import asyncio
import contextlib
import json
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db import get_db
from app.errores import ErrorApp
from app.modulos.usuarios.modelos import Usuario
from app.reloj import Reloj, get_reloj
from app.seguridad import decodificar_token_con_exp
from app.tiempo_real import tickets
from app.tiempo_real.bus import sobre
from app.tiempo_real.conexiones import gestor

router = APIRouter(tags=["tiempo real"])
CIERRE_NO_AUTENTICADO = 4401
CIERRE_DESBORDE = 1013
_bearer = HTTPBearer(auto_error=False)


class TicketSalida(BaseModel):
    ticket: str
    expira_en: int


def _sesion(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> tuple[Usuario, float]:
    """Autentica el Bearer (una sola decodificación) y devuelve (usuario, `exp` del JWT)."""
    no_autenticado = ErrorApp(401, "NO_AUTENTICADO", "No autenticado.")
    if credenciales is None:
        raise no_autenticado
    decodificado = decodificar_token_con_exp(credenciales.credentials)
    if decodificado is None:
        raise no_autenticado
    usuario = db.get(Usuario, decodificado[0])
    if usuario is None or not usuario.activo:
        raise no_autenticado
    return usuario, decodificado[1]


@router.post("/ws/ticket", response_model=TicketSalida)
def emitir_ticket(
    sesion: Annotated[tuple[Usuario, float], Depends(_sesion)],
    db: Annotated[Session, Depends(get_db)],
    reloj: Annotated[Reloj, Depends(get_reloj)],
) -> TicketSalida:
    usuario, exp = sesion
    fin_sesion = datetime.fromtimestamp(exp, tz=reloj().tzinfo)
    ticket = tickets.emitir(db, usuario.id, reloj(), fin_sesion)
    return TicketSalida(ticket=ticket, expira_en=tickets.TTL_SEGUNDOS)


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


def _abrir(app: FastAPI, ticket: str | None) -> tuple[int, str, float | None] | None:
    """Consume el ticket y devuelve (usuario_id, rol, fin de sesión epoch) o None."""
    with sesion_de(app) as db:
        consumido = tickets.consumir(db, ticket, reloj_de(app)())
        if consumido is None:
            return None
        usuario = db.get(Usuario, consumido[0])
        if usuario is None or not usuario.activo:
            return None
        fin = consumido[1].timestamp() if consumido[1] else None
        return usuario.id, usuario.rol, fin


def _vigente(app: FastAPI, usuario_id: int, rol: str) -> bool:
    """Revalidación periódica: el usuario sigue activo y con el mismo rol."""
    with sesion_de(app) as db:
        db.expire_all()
        usuario = db.get(Usuario, usuario_id)
        return usuario is not None and usuario.activo and usuario.rol == rol


def _marcar_desconectado(app: FastAPI, usuario_id: int) -> None:
    from app.modulos.consola import estado as estado_agente

    with sesion_de(app) as db:
        estado_agente.desconectar_por_inactividad(db, usuario_id, reloj_de(app)())


@router.websocket("/ws")
async def ws(websocket: WebSocket, ticket: str | None = None) -> None:
    await websocket.accept()
    abierto = await run_in_threadpool(_abrir, websocket.app, ticket)
    if abierto is None:
        await websocket.close(code=CIERRE_NO_AUTENTICADO)
        return
    usuario_id, rol, fin_sesion = abierto
    revalidar_cada = get_settings().ws_revalidar_segundos

    conexion = gestor.conectar(usuario_id, rol)
    recibir: asyncio.Task[Any] | None = None
    entregar: asyncio.Task[Any] | None = None
    try:
        await websocket.send_json(sobre("conexion.lista", {"usuario_id": usuario_id, "rol": rol}))
        recibir = asyncio.ensure_future(websocket.receive())
        entregar = asyncio.ensure_future(conexion.cola.get())
        proxima_revision = time.monotonic() + revalidar_cada
        while True:
            esperas = [proxima_revision - time.monotonic()]
            if fin_sesion is not None:
                esperas.append(fin_sesion - time.time())
            hechas, _ = await asyncio.wait(
                {recibir, entregar},
                timeout=max(min(esperas), 0),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if fin_sesion is not None and time.time() >= fin_sesion:
                await websocket.close(code=CIERRE_NO_AUTENTICADO)
                break
            if time.monotonic() >= proxima_revision:
                proxima_revision = time.monotonic() + revalidar_cada
                if not await run_in_threadpool(_vigente, websocket.app, usuario_id, rol):
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
                if conexion.desbordada:
                    await websocket.close(code=CIERRE_DESBORDE)
                    break
                await websocket.send_json(entregar.result())
                entregar = asyncio.ensure_future(conexion.cola.get())
            elif conexion.desbordada:
                await websocket.close(code=CIERRE_DESBORDE)
                break
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
    try:
        cuerpo = json.loads(texto)
    except ValueError:
        return False
    return isinstance(cuerpo, dict) and cuerpo.get("tipo") == "ping"
