from logging.config import fileConfig

from alembic import context
from app import registro_modelos  # noqa: F401
from app.config import get_settings
from app.db import Base, crear_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = crear_engine(_url())
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            # El modo batch recrea las tablas (DROP + RENAME). Con las claves foráneas activas, el
            # DROP de una tabla padre borraría en cascada a las hijas (p. ej. `campanas`).
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()  # termina el autobegin: Alembic gestiona su propia transacción
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
