"""Punto de entrada FastAPI: routers bajo /api/v1, manejadores de error, CORS y tiempo real."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import (
    logging_seguro,
    registro_modelos,  # noqa: F401  (registra los modelos en Base.metadata)
)
from app.config import VERSION, Settings, get_settings
from app.errores import registrar_manejadores
from app.middleware import ProteccionMiddleware
from app.modulos.auth.router import router as auth_router
from app.modulos.campanas.router import router as campanas_router
from app.modulos.clientes.router import router as clientes_router
from app.modulos.consola.router import router as consola_router
from app.modulos.consola.router import router_campana as tipificaciones_router
from app.modulos.cumplimiento.router import router as cumplimiento_router
from app.modulos.exclusiones.router import router as exclusiones_router
from app.modulos.importacion.router import router as importacion_router
from app.modulos.supervision.router import router as supervision_router
from app.modulos.telefonia.router import router as telefonia_router
from app.modulos.telefonia.router_simulacion import router as simulacion_router
from app.modulos.usuarios.router import router as usuarios_router
from app.tiempo_real import bus
from app.tiempo_real.conexiones import gestor
from app.tiempo_real.router import router as ws_router


def crear_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        el_bus = bus.crear_bus(settings.database_url)
        if isinstance(el_bus, bus.BusMemoria):
            el_bus.suscribir(gestor.repartir)
        bus.establecer_bus(el_bus)
        tarea: asyncio.Task[None] | None = None
        if isinstance(el_bus, bus.BusPostgres):
            from app.tiempo_real.escucha import escuchar

            tarea = asyncio.create_task(escuchar(settings.database_url, gestor))
        try:
            yield
        finally:
            if tarea is not None:
                tarea.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarea
            bus.establecer_bus(None)

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    logging_seguro.instalar()
    settings = settings or get_settings()
    app = FastAPI(
        title="Plataforma de campañas outbound",
        version=VERSION,
        lifespan=crear_lifespan(settings),
    )
    app.add_middleware(ProteccionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.lista_cors,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    registrar_manejadores(app)

    api = APIRouter(prefix="/api/v1")

    @api.get("/salud", tags=["salud"])
    def salud() -> dict[str, str]:
        return {"estado": "ok", "version": VERSION}

    routers = [
        auth_router,
        usuarios_router,
        campanas_router,
        importacion_router,
        clientes_router,
        exclusiones_router,
        cumplimiento_router,
        consola_router,
        tipificaciones_router,
        telefonia_router,
        supervision_router,
        ws_router,
    ]
    if settings.telefonia_proveedor == "falso" and settings.entorno != "produccion":
        routers.append(simulacion_router)
    for router in routers:
        api.include_router(router)
    app.include_router(api)
    return app


app = create_app()
