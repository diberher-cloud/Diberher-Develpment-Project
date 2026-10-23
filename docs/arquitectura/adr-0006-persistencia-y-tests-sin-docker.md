# ADR-0006: SQLAlchemy 2 síncrono + Alembic, con tests sin Docker

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
Producción y desarrollo usan PostgreSQL 16 (Docker Compose). Requisito: los tests del backend deben
poder correr **sin Docker** (CI simple, agentes sin demonio Docker).

## Decisión
- **SQLAlchemy 2.0 síncrono** (estilo `Mapped[...]`) con driver `psycopg` 3 en PostgreSQL. Endpoints
  FastAPI `def` (se ejecutan en el threadpool). Más simple de probar que async y suficiente para la carga.
  El WebSocket/LISTEN de fase 3 usa async de forma localizada.
- **Alembic** para migraciones; `render_as_batch=True` para que también apliquen en SQLite.
- **SQL portable en fase 1**: tipos genéricos (`Integer`, `String`, `Text`, `Numeric`, `Boolean`, `Date`,
  `JSON`, `DateTime(timezone=True)`), restricciones `CHECK` con SQL estándar, sin `ARRAY`, `ENUM` nativo ni
  funciones específicas. Enumeraciones como `String` + `CHECK`.
- Columnas de fecha-hora mediante un `TypeDecorator` `FechaHoraUTC` que exige datetimes con zona, guarda
  en UTC y devuelve con `tzinfo=UTC` también en SQLite (que no conserva zona).
- Tests:
  - **Unitarios puros** (motor de cumplimiento, festivos, teléfonos, CSV): sin BD.
  - **API**: `TestClient` + SQLite en memoria (`sqlite+pysqlite://`, `StaticPool`), `Base.metadata.create_all`,
    sobrescribiendo la dependencia `get_db`. `PRAGMA foreign_keys=ON`.
  - **Migraciones**: un test aplica `alembic upgrade head` sobre un SQLite temporal y comprueba tablas
    y semillas.
  - **Opcional PostgreSQL**: tests marcados `@pytest.mark.postgres` que se ejecutan solo si existe
    `TEST_DATABASE_URL` (no son necesarios para dar la fase por buena).
- Fase 3 introducirá SQL específico de PostgreSQL (`FOR UPDATE SKIP LOCKED`, `LISTEN/NOTIFY`); esas partes
  se aíslan en el módulo `marcador`/`tiempo_real` y se prueban con dobles o con el marcador `postgres`.

## Alternativas consideradas
- **SQLAlchemy async + asyncpg**: más complejidad en tests y sesiones; sin beneficio a esta escala.
- **Testcontainers**: fiel a producción pero exige Docker (contradice el requisito).
- **SQLModel**: capa adicional; Pydantic + SQLAlchemy por separado es más explícito.

## Consecuencias
- + `pytest` funciona con solo `pip install -e ".[dev]"`.
- − Diferencias SQLite/PostgreSQL (p. ej. comparación de mayúsculas en `LIKE`, `JSON`): se mitigan con
  búsquedas normalizadas (`lower(...)`) y el test de migraciones; los tests `postgres` cubren el resto.
