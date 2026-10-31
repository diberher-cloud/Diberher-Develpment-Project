import os

# Debe fijarse antes de importar la aplicación.
os.environ["ENTORNO"] = "test"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["BCRYPT_COSTE"] = "4"
os.environ.pop("JWT_SECRETO", None)
os.environ["PUBLIC_BASE_URL"] = "https://pruebas.example.com"
os.environ["TWILIO_AUTH_TOKEN"] = "token-de-pruebas"
os.environ["TWILIO_NUMERO_SALIENTE"] = "+576015550000"
os.environ["TELEFONIA_PROVEEDOR"] = "falso"

import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app import registro_modelos  # noqa: E402,F401
from app.db import Base, crear_engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modulos.usuarios.modelos import Usuario  # noqa: E402
from app.reloj import get_reloj  # noqa: E402
from app.seguridad import crear_token, hash_password  # noqa: E402

PASSWORD = "ClaveSegura123"


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    # Opcional: `SUITE_DATABASE_URL=postgresql+psycopg://...` ejecuta toda la batería sobre
    # PostgreSQL (se recrea el esquema en cada test). Por defecto, SQLite en memoria.
    url_suite = os.environ.get("SUITE_DATABASE_URL")
    engine = crear_engine(url_suite or "sqlite+pysqlite://")
    if url_suite:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    from app.modulos.cumplimiento.modelos import PoliticaCumplimiento
    from app.modulos.cumplimiento.politica import politica_por_defecto

    fabrica = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    with fabrica() as db:
        for tipo in ("venta", "cobranza"):
            db.add(
                PoliticaCumplimiento(
                    tipo_campana=tipo, version=1, configuracion=politica_por_defecto(), activa=True
                )
            )
        db.commit()
    yield fabrica
    if url_suite:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as sesion:
        yield sesion


class RelojFijo:
    """Reloj controlado por el test. Por defecto: viernes 2026-10-23 10:15 en Bogotá."""

    def __init__(self) -> None:
        self.actual = datetime(2026, 10, 23, 15, 15, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.actual

    def fijar(self, momento: datetime) -> None:
        self.actual = momento

    def avanzar(self, **kwargs: float) -> None:
        self.actual += timedelta(**kwargs)


@pytest.fixture()
def reloj() -> RelojFijo:
    return RelojFijo()


@pytest.fixture()
def client(session_factory: sessionmaker[Session], reloj: RelojFijo) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        with session_factory() as sesion:
            yield sesion

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_reloj] = lambda: reloj
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def crear_usuario(db: Session) -> Callable[..., Usuario]:
    contador = {"n": 0}

    def _crear(
        rol: str = "administrador", activo: bool = True, email: str | None = None
    ) -> Usuario:
        contador["n"] += 1
        usuario = Usuario(
            email=email or f"{rol}{contador['n']}@empresa.co",
            nombre=f"Usuario {rol} {contador['n']}",
            rol=rol,
            password_hash=hash_password(PASSWORD),
            activo=activo,
        )
        db.add(usuario)
        db.commit()
        return usuario

    return _crear


@pytest.fixture()
def cabeceras() -> Callable[[Usuario], dict[str, str]]:
    def _cab(usuario: Usuario) -> dict[str, str]:
        token, _ = crear_token(usuario.id, usuario.rol)
        return {"Authorization": f"Bearer {token}"}

    return _cab


@pytest.fixture()
def admin(crear_usuario: Callable[..., Usuario]) -> Usuario:
    return crear_usuario("administrador")


@pytest.fixture()
def h_admin(admin: Usuario, cabeceras: Callable[[Usuario], dict[str, str]]) -> dict[str, str]:
    return cabeceras(admin)


@pytest.fixture()
def h_supervisor(
    crear_usuario: Callable[..., Usuario], cabeceras: Callable[[Usuario], dict[str, str]]
) -> dict[str, str]:
    return cabeceras(crear_usuario("supervisor"))


@pytest.fixture()
def h_agente(
    crear_usuario: Callable[..., Usuario], cabeceras: Callable[[Usuario], dict[str, str]]
) -> dict[str, str]:
    return cabeceras(crear_usuario("agente"))


# ---- Firma de Twilio (cálculo independiente de la implementación) ------------------------------
BASE_URL = "https://pruebas.example.com"
TOKEN_TWILIO = "token-de-pruebas"


def firma_independiente(url: str, params: dict[str, str], token: str = TOKEN_TWILIO) -> str:
    texto = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), texto.encode(), hashlib.sha1).digest()
    ).decode()


@pytest.fixture()
def firmar_twilio() -> Callable[..., dict]:
    """Devuelve kwargs (`data`, `headers`) listos para `client.post(ruta, **kw)`."""

    def _firmar(ruta: str, params: dict[str, str], consulta: str = "", token: str = TOKEN_TWILIO):
        url = BASE_URL + ruta + (f"?{consulta}" if consulta else "")
        return {
            "data": params,
            "headers": {"X-Twilio-Signature": firma_independiente(url, params, token)},
        }

    return _firmar


# ---- WhatsApp (2B) -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def proveedor_whatsapp():
    """Proveedor de WhatsApp falso limpio en cada test."""
    from app.integraciones.whatsapp.fabrica import (
        obtener_proveedor_whatsapp,
        reiniciar_proveedor_whatsapp,
    )

    reiniciar_proveedor_whatsapp()
    proveedor = obtener_proveedor_whatsapp()
    proveedor.reiniciar()
    yield proveedor
    reiniciar_proveedor_whatsapp()


@pytest.fixture()
def correr_trabajos(
    session_factory: sessionmaker[Session], reloj: "RelojFijo"
) -> Callable[..., int]:
    """Ejecuta de forma síncrona los trabajos disponibles (`ejecutar_pendientes`)."""
    from app.trabajos.cola import ejecutar_pendientes

    def _correr(ahora: datetime | None = None, maximo: int = 100) -> int:
        with session_factory() as s:
            return ejecutar_pendientes(s, ahora or reloj(), maximo)

    return _correr


@pytest.fixture()
def esc(db: Session, admin: Usuario):
    from escenario import Escenario

    return Escenario(db, admin.id)


# ---- Agente IA (2C) ----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def llm_ia_limpio():
    """Sin cliente LLM compartido entre tests (cada test instala su cliente falso)."""
    from app.modulos.agente_ia.llm import establecer_cliente_llm

    establecer_cliente_llm(None)
    yield
    establecer_cliente_llm(None)
