import os

# Debe fijarse antes de importar la aplicación.
os.environ["ENTORNO"] = "test"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["BCRYPT_COSTE"] = "4"
os.environ.pop("JWT_SECRETO", None)

from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app import registro_modelos  # noqa: E402,F401
from app.db import Base, crear_engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modulos.usuarios.modelos import Usuario  # noqa: E402
from app.seguridad import crear_token, hash_password  # noqa: E402

PASSWORD = "ClaveSegura123"


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = crear_engine("sqlite+pysqlite://")
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
    engine.dispose()


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as sesion:
        yield sesion


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        with session_factory() as sesion:
            yield sesion

    app.dependency_overrides[get_db] = _get_db
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
