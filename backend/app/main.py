"""Punto de entrada FastAPI: routers bajo /api/v1, manejadores de error y CORS."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import registro_modelos  # noqa: F401  (registra los modelos en Base.metadata)
from app.config import VERSION, get_settings
from app.errores import registrar_manejadores
from app.middleware import ProteccionMiddleware
from app.modulos.auth.router import router as auth_router
from app.modulos.campanas.router import router as campanas_router
from app.modulos.clientes.router import router as clientes_router
from app.modulos.cumplimiento.router import router as cumplimiento_router
from app.modulos.exclusiones.router import router as exclusiones_router
from app.modulos.importacion.router import router as importacion_router
from app.modulos.usuarios.router import router as usuarios_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Plataforma de campañas outbound", version=VERSION)
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

    for router in (
        auth_router,
        usuarios_router,
        campanas_router,
        importacion_router,
        clientes_router,
        exclusiones_router,
        cumplimiento_router,
    ):
        api.include_router(router)
    app.include_router(api)
    return app


app = create_app()
