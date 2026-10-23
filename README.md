# Diberher Development Project

Plataforma web de **campañas outbound** para contact center en Colombia, de **venta** y de **cobranza**.
Incorpora el cumplimiento normativo colombiano como configuración: Ley 2300 de 2023 (horarios y frecuencia
de contacto), Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008, Registro de Números Excluidos (RNE) de la
CRC y festivos de Colombia (Ley 51 de 1983).

Este repositorio también contiene el equipo de agentes de IA con el que se desarrolla el proyecto. Está
resumido al final.

## Estado

**Fase 1 terminada**: probada y aprobada por la revisión. Incluye:

- Autenticación con JWT y roles `administrador`, `supervisor` y `agente`; gestión de usuarios.
- Campañas `venta` y `cobranza` con máquina de estados.
- Importación de clientes desde CSV: normalización de teléfonos a E.164 (+57), deduplicación, exclusiones
  y resumen de errores. Ver [`docs/importacion-csv.md`](docs/importacion-csv.md).
- Exclusiones de números por finalidad, con carga masiva (RNE).
- Motor de cumplimiento: políticas versionadas, franjas horarias y festivos de Colombia con endpoint de
  evaluación.
- Auditoría de acciones sensibles.

**Sin telefonía todavía**: no hay Twilio, consola del agente, marcador, WebSocket ni reportes. La frecuencia
de contacto (Ley 2300) se guarda en la política, pero no se evalúa. Ver [`docs/pendientes.md`](docs/pendientes.md).

## Requisitos

- Python 3.12 o superior.
- Node.js 22 LTS.
- Docker y Docker Compose (opcional). Compose levanta PostgreSQL 16. Sin Docker, el backend usa SQLite por defecto.

## Arranque con Docker Compose

```bash
# 1. Configuración: copie la plantilla y defina JWT_SECRETO (mínimo 32 caracteres)
cp .env.example .env
#    Edite .env. Compose no arranca si JWT_SECRETO falta. No use el valor de ejemplo.
#    Opcional: defina ADMIN_PASSWORD para crear el administrador sin preguntar.

# 2. Levante los servicios (db, backend y frontend)
docker compose up --build -d

# 3. Espere a que el backend termine las migraciones y arranque
docker compose logs -f backend      # Ctrl+C cuando aparezca "Application startup complete"

# 4. Cree el primer administrador (no hay usuarios por defecto)
docker compose exec backend python -m app.cli crear-admin --email admin@empresa.co --nombre "Ana Admin"
```

Al arrancar, el backend ejecuta `alembic upgrade head` y `generar-festivos` (2025 a 2028) y después
`uvicorn` con recarga automática.

| Servicio | URL | Notas |
|---|---|---|
| Interfaz | http://localhost:5173 | Inicie sesión con el administrador creado. |
| API | http://localhost:8000/api/v1/salud | Documentación interactiva en `/docs`. |
| PostgreSQL | `127.0.0.1:5432` | Publicado solo en localhost. |

Para reiniciar la base de datos desde cero (incluidos los datos): `docker compose down -v`.

## Arranque sin Docker

Use SQLite (por defecto) o PostgreSQL local.

```bash
# Backend (desde backend/)
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp ../.env.example .env          # en backend/.env, para que lo lea la aplicación
#    Edite JWT_SECRETO. Para SQLite, quite la línea DATABASE_URL o use:
#    DATABASE_URL=sqlite:///./outbound.db
#    Para PostgreSQL local, levante solo la base con docker compose up -d db
#    (Compose necesita el .env de la raíz con JWT_SECRETO, como en la sección anterior)
#    y use DATABASE_URL=postgresql+psycopg://outbound:outbound@localhost:5432/outbound

alembic upgrade head
python -m app.cli crear-admin --email admin@empresa.co --nombre "Ana Admin"
python -m app.cli generar-festivos --desde 2025 --hasta 2028
uvicorn app.main:app --reload --port 8000
```

```bash
# Frontend (desde frontend/), en otra terminal
cd frontend
npm ci
npm run dev                      # http://localhost:5173
```

El proxy de `/api` apunta a `http://localhost:8000` por defecto. Si el backend escucha en otro puerto o
host, exporte `VITE_PROXY_TARGET` en la shell (`VITE_PROXY_TARGET=http://localhost:8001 npm run dev`).
Un `.env` no basta, porque `vite.config.ts` lee el valor de `process.env`.

Variables de entorno del backend: [`backend/README.md`](backend/README.md#variables-de-entorno).

## Tests y lint

| Parte | Comando | Notas |
|---|---|---|
| Backend | `cd backend && pytest` | Sin Docker ni PostgreSQL (SQLite en memoria). |
| Backend | `cd backend && ruff check .` | Lint con `line-length = 100`. |
| Backend, PostgreSQL | `TEST_DATABASE_URL=… pytest -m postgres` | Migraciones contra una base vacía y dedicada. |
| Frontend | `cd frontend && npm test -- --run` | Vitest y Testing Library. |
| Frontend | `cd frontend && npm run lint` | ESLint. |
| Frontend | `cd frontend && npm run build` | `tsc -b` y build de Vite. |

## Documentación

- [`docs/importacion-csv.md`](docs/importacion-csv.md): formato del CSV de importación, reglas, límites y códigos de error.
- [`docs/pendientes.md`](docs/pendientes.md): validación legal pendiente, supuestos a confirmar y deuda para próximas fases.
- [`backend/README.md`](backend/README.md) y [`frontend/README.md`](frontend/README.md): estructura, comandos y convenciones.
- [`CHANGELOG.md`](CHANGELOG.md): cambios por versión.

### Arquitectura

- [`docs/arquitectura/README.md`](docs/arquitectura/README.md): visión general, componentes, modelo de datos y plan por fases.
- [`docs/arquitectura/fase-1.md`](docs/arquitectura/fase-1.md): alcance, esquema de base de datos, contratos de API y tareas de la Fase 1.
- Decisiones de arquitectura (ADR):
  - [ADR-0001](docs/arquitectura/adr-0001-monolito-modular.md): monolito modular.
  - [ADR-0002](docs/arquitectura/adr-0002-motor-cumplimiento-configurable.md): motor de cumplimiento configurable.
  - [ADR-0003](docs/arquitectura/adr-0003-integracion-twilio.md): integración con Twilio.
  - [ADR-0004](docs/arquitectura/adr-0004-tiempo-real-websocket-listen-notify.md): tiempo real con WebSocket y `LISTEN/NOTIFY`.
  - [ADR-0005](docs/arquitectura/adr-0005-autenticacion-jwt-roles.md): autenticación JWT y roles.
  - [ADR-0006](docs/arquitectura/adr-0006-persistencia-y-tests-sin-docker.md): persistencia y tests sin Docker.
  - [ADR-0007](docs/arquitectura/adr-0007-normalizacion-telefonos-e164.md): normalización de teléfonos a E.164.
  - [ADR-0008](docs/arquitectura/adr-0008-proteccion-datos-personales.md): protección de datos personales.
  - [ADR-0009](docs/arquitectura/adr-0009-marcador-preview-progresivo.md): marcador preview y progresivo.

## Plan por fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Cimientos sin telefonía: auth con roles, campañas, importación CSV, exclusiones, cumplimiento (franjas y festivos) y auditoría. | Terminada |
| 2 | Consola del agente, llamada manual (preview básico) con Twilio, importación desde Excel y tipificaciones. | Pendiente |
| 3 | Marcador automático (preview y progresivo), reintentos, frecuencia de la Ley 2300 y WebSocket. | Pendiente |
| 4 | Supervisión en tiempo real, reportes y exportación CSV, escucha de grabaciones. | Pendiente |
| 5 | Predictivo, multicanal, webservice del RNE, retención de datos y SSO. | Opcional |

Detalle en [`docs/arquitectura/README.md`](docs/arquitectura/README.md) (§8).

---

## Equipo de agentes

El repositorio define un equipo de subagentes de IA para Claude Code en `.claude/agents/`. Cada rol tiene
su prompt, sus herramientas y su modelo:

| Agente | Rol | Puede escribir |
|---|---|---|
| `arquitecto` | Diseño, contratos, plan y ADR | solo `docs/arquitectura/` |
| `backend` | API, lógica de negocio y datos | código de servidor y sus tests |
| `frontend` | UI e integración con la API | código de cliente y sus tests |
| `qa` | Diseño y ejecución de tests | tests y fixtures |
| `revisor` | Revisión de bugs, seguridad y calidad | nada (solo lectura) |
| `documentacion` | README, docs y CHANGELOG | documentación |

Para una funcionalidad completa, use `/equipo <tarea>` (`.claude/skills/equipo/SKILL.md`). El flujo es
arquitecto, después backend y frontend en paralelo, después qa, revisor y documentación. Ningún cambio de
código se da por terminado sin pasar por `qa` y `revisor`.
