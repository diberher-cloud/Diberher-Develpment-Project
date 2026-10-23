# Backend — API de la plataforma outbound

API REST en FastAPI (monolito modular, ADR-0001) con SQLAlchemy 2, Alembic y PostgreSQL 16 en Docker.
Sin Docker usa SQLite por defecto. La visión general está en el [README raíz](../README.md) y el diseño
en `docs/arquitectura/`.

Requisitos: Python 3.12 o superior.

## Estructura

```
backend/
├── app/
│   ├── main.py              # create_app(): routers bajo /api/v1, CORS, manejadores de error
│   ├── config.py            # Settings (pydantic-settings): variables de entorno
│   ├── db.py                # engine, SessionLocal, Base, get_db, FechaHoraUTC
│   ├── errores.py           # ErrorApp, manejadores y formato de error común
│   ├── middleware.py        # límite de cuerpo (413) y captura de excepciones
│   ├── seguridad.py         # bcrypt y JWT HS256
│   ├── dependencias.py      # usuario_actual, requiere_rol(...)
│   ├── paginacion.py        # parámetros y respuesta paginada
│   ├── cli.py               # crear-admin, generar-festivos
│   └── modulos/
│       ├── auth/            # login y me
│       ├── usuarios/        # alta, edición y roles
│       ├── campanas/        # campañas y máquina de estados
│       ├── clientes/        # listado de clientes de una campaña
│       ├── importacion/     # CSV: lector, normalización, teléfonos (funciones puras) + servicio
│       ├── exclusiones/     # números excluidos y carga masiva
│       ├── cumplimiento/    # políticas, festivos, motor de horario (puro)
│       └── auditoria/       # registro de acciones sensibles
├── alembic/                 # env.py y versions/0001_esquema_inicial.py
├── tests/
│   ├── unit/                # lógica pura, sin BD
│   ├── api/                 # endpoints con SQLite en memoria
│   ├── fixtures/            # CSV de ejemplo
│   ├── conftest.py
│   └── test_migraciones.py
├── Dockerfile
├── pyproject.toml           # dependencias, pytest y ruff
├── requirements.lock        # versiones exactas usadas por la imagen Docker
└── alembic.ini
```

Cada módulo de dominio sigue la misma forma: `modelos.py` (SQLAlchemy), `esquemas.py` (Pydantic),
`servicio.py` (lógica con E/S) y `router.py` (FastAPI). La lógica pura (`telefonos.py`,
`normalizacion.py`, `lector_csv.py`, `politica.py`, `festivos.py`, `motor.py`) no accede a BD ni a red.

## Comandos

Ejecútelos desde `backend/`. Con Docker, use `docker compose exec backend …` (ver el README raíz).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head                                    # esquema y políticas iniciales
python -m app.cli crear-admin --email admin@empresa.co --nombre "Ana Admin"
python -m app.cli generar-festivos --desde 2025 --hasta 2028
uvicorn app.main:app --reload --port 8000               # http://localhost:8000/api/v1/salud
```

- `crear-admin` pide la contraseña (10 a 128 caracteres) si `ADMIN_PASSWORD` está vacío.
- `generar-festivos` es idempotente: no modifica fechas que ya existen (manuales, calculadas o desactivadas).
- La documentación interactiva de FastAPI está en `http://localhost:8000/docs`.

Tests y lint:

```bash
pytest                       # unitarios y API; no requiere Docker ni PostgreSQL
ruff check .                 # lint (line-length 100)
TEST_DATABASE_URL=postgresql+psycopg://outbound:outbound@localhost:5432/outbound pytest -m postgres
```

El último comando ejecuta `upgrade head`, `check` y `downgrade base` sobre la base indicada. Use una base
vacía y dedicada, porque el downgrade elimina las tablas.

## Variables de entorno

Se leen con `app/config.py` desde el entorno del proceso o desde `.env` en el directorio de trabajo
(`backend/.env` al ejecutar sin Docker). Con Docker, Compose lee el `.env` de la raíz del repositorio.
Plantilla completa: `.env.example`.

| Variable | Por defecto | Descripción |
|---|---|---|
| `ENTORNO` | `desarrollo` | `desarrollo`, `test` o `produccion`. En `produccion` rechaza el `JWT_SECRETO` de ejemplo. |
| `DATABASE_URL` | `sqlite:///./outbound.db` | URL de SQLAlchemy. Ejemplo PostgreSQL: `postgresql+psycopg://usuario:clave@host:5432/bd`. |
| `JWT_SECRETO` | — | **Obligatoria** fuera de `ENTORNO=test`, de al menos 32 caracteres. Sin ella o con menos caracteres, la aplicación no arranca. |
| `JWT_EXPIRACION_MINUTOS` | `480` | Caducidad del token de acceso (8 horas). |
| `BCRYPT_COSTE` | `12` | Coste (rondas) de bcrypt. |
| `CORS_ORIGENES` | `http://localhost:5173` | Orígenes permitidos, separados por comas. |
| `IMPORTACION_MAX_BYTES` | `10485760` | Tamaño máximo de un CSV de importación (10 MiB). |
| `IMPORTACION_MAX_FILAS` | `50000` | Filas de datos máximas de una importación de clientes. |
| `EXCLUSIONES_MAX_FILAS` | `200000` | Filas de datos máximas de una carga masiva de exclusiones. |
| `ADMIN_PASSWORD` | vacío | Contraseña para `crear-admin` sin pedirla por consola. |
| `TEST_DATABASE_URL` | — | Solo para `pytest -m postgres`. |

## Endpoints

Todos bajo `/api/v1`. Salvo `GET /salud` y `POST /auth/login`, requieren `Authorization: Bearer <jwt>`.
Contratos completos en `docs/arquitectura/fase-1.md` (§4).

| Método y ruta | Roles |
|---|---|
| `GET /salud` | público |
| `POST /auth/login`, `GET /auth/me` | cualquier usuario activo |
| `GET/POST /usuarios`, `PATCH /usuarios/{id}` | administrador |
| `GET/POST /campanas`, `GET/PATCH/DELETE /campanas/{id}` | lectura: todos (agente solo `activa`); escritura: administrador, supervisor |
| `POST/GET /campanas/{id}/importaciones` | administrador, supervisor |
| `GET /campanas/{id}/clientes` | administrador, supervisor |
| `GET /importaciones/{id}`, `GET /importaciones/{id}/errores` | administrador, supervisor |
| `GET/POST /exclusiones`, `POST /exclusiones/importar`, `DELETE /exclusiones/{id}` | administrador, supervisor |
| `GET /cumplimiento/politicas` | cualquier usuario activo |
| `GET /cumplimiento/politicas/{tipo}/versiones` | administrador, supervisor |
| `PUT /cumplimiento/politicas/{tipo}` | administrador |
| `POST /cumplimiento/evaluar` | cualquier usuario activo |
| `GET /festivos?anio=`, `POST /festivos`, `PATCH /festivos/{id}` | lectura: todos; escritura: administrador |
| `POST /festivos/generar` | administrador |

## Convenciones

**Formato de error único.** Todas las respuestas 4xx y 5xx tienen esta forma, incluidos los 404 de ruta y
los 422 de validación:

```json
{
  "error": {
    "codigo": "VALIDACION",
    "mensaje": "Los datos enviados no son válidos.",
    "detalles": [ { "campo": "nombre", "mensaje": "Campo obligatorio." } ]
  }
}
```

- `detalles` es siempre una lista (vacía si no aplica). `campo` usa la ruta con puntos
  (`configuracion.franjas.lunes.0.inicio`).
- Códigos genéricos: `NO_AUTENTICADO` (401), `CREDENCIALES_INVALIDAS` (401), `PERMISO_DENEGADO` (403),
  `NO_ENCONTRADO` (404), `VALIDACION` (422), `ARCHIVO_DEMASIADO_GRANDE` (413), `ERROR_INTERNO` (500).
  Los conflictos de negocio usan 409 con un código específico (`NOMBRE_DUPLICADO`, `EMAIL_DUPLICADO`,
  `CAMPANA_FINALIZADA`, `*_CONCURRENTE`, etc.).
- En el código, una excepción de negocio es `ErrorApp(status, codigo, mensaje, detalles)`. Un error de
  validación de campo se construye con `error_validacion(campo, mensaje)`.

**Datos personales.** Ni los logs ni la auditoría ni los mensajes de error contienen documentos ni
teléfonos completos. Los errores no controlados se registran con `registrar_error_interno`, que solo
guarda el tipo de excepción y las líneas del traceback, nunca `str(exc)` (ADR-0008).

**Paginación.** Query `page` (≥ 1, por defecto 1) y `page_size` (1 a 100, por defecto 20). Respuesta
`{ "items": [], "total": 0, "page": 1, "page_size": 20 }`.

**Nombres.** Identificadores de dominio en español sin tildes ni `ñ`; la API usa `snake_case`.

**Fechas.** Se guardan en UTC (`timestamptz`) y se responden con sufijo `Z`. Los campos `*_local`
del evaluador de cumplimiento van en `America/Bogota` (`-05:00`).

**Importación.** Reglas de archivo, teléfonos y códigos de fila en `docs/importacion-csv.md`.
