# Diberher Development Project

Plataforma web de **campañas outbound** para contact center en Colombia, de **venta** y de **cobranza**.
Incorpora el cumplimiento normativo colombiano como configuración: Ley 2300 de 2023 (horarios y frecuencia
de contacto), Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008, Registro de Números Excluidos (RNE) de la
CRC y festivos de Colombia (Ley 51 de 1983).

Este repositorio también contiene el equipo de agentes de IA con el que se desarrolla el proyecto. Está
resumido al final.

## Estado

**Fase 1 y subfase 2A terminadas**: probadas y aprobadas por la revisión. La subfase 2A es la consola del agente
humano con voz Twilio. Las subfases 2B a 2F están pendientes. Ver [`docs/arquitectura/fase-2.md`](docs/arquitectura/fase-2.md) §0.

**Fase 1** incluye:

- Autenticación con JWT y roles `administrador`, `supervisor` y `agente`; gestión de usuarios.
- Campañas `venta` y `cobranza` con máquina de estados.
- Importación de clientes desde CSV: normalización de teléfonos a E.164 (+57), deduplicación, exclusiones
  y resumen de errores. Ver [`docs/importacion-csv.md`](docs/importacion-csv.md).
- Exclusiones de números por finalidad, con carga masiva (RNE).
- Motor de cumplimiento: políticas versionadas, franjas horarias y festivos de Colombia con endpoint de
  evaluación.
- Auditoría de acciones sensibles.

**Subfase 2A** incluye:

- Asignación de agentes a campañas, estado del agente con historial y lista de trabajo con reservas de 15 minutos.
- Llamadas manuales desde el navegador (softphone de Twilio o falso). El servidor aplica horario, festivos,
  exclusiones y frecuencia antes de marcar. Guía: [`docs/telefonia-twilio.md`](docs/telefonia-twilio.md).
- Tipificaciones con sus efectos: promesas, ventas, exclusión por número errado y rellamadas. Guía:
  [`docs/consola-agente.md`](docs/consola-agente.md).
- Frecuencia de contacto de la Ley 2300 evaluada en cada llamada. Las lecturas jurídicas están pendientes de
  validación: [`docs/cumplimiento-frecuencia.md`](docs/cumplimiento-frecuencia.md).
- Supervisión en vivo por WebSocket (con tickets de un solo uso).
- Importación de clientes y de exclusiones desde `.csv` y `.xlsx`.

**Pendiente de validar con Twilio real**: la llamada a un móvil, la firma a través de un túnel y el aviso de
grabación. Sin credenciales, toda la consola se prueba con el proveedor falso. No hay marcador automático ni
reintentos (Fase 3). Ver [`docs/pendientes.md`](docs/pendientes.md), sección 5.

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

> **Telefonía con Docker.** `docker-compose.yml` no pasa las variables de telefonía (`TELEFONIA_*`, `TWILIO_*`,
> `PUBLIC_BASE_URL`, `CONSOLA_*`, etc.) al servicio `backend`. Con el proveedor falso no hace falta nada. Para usar
> Twilio con Docker, añádalas a `environment` del servicio `backend` o copie el `.env` a `backend/`. Ver
> [`docs/telefonia-twilio.md`](docs/telefonia-twilio.md#variables-de-entorno).

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

Variables nuevas de la subfase 2A (todas en `.env.example`): `TELEFONIA_PROVEEDOR` (por defecto `falso`),
`PUBLIC_BASE_URL`, las `TWILIO_*`, las `TELEFONIA_*`, `CONSOLA_RESERVA_MINUTOS`, `CONSOLA_DESCONEXION_SEGUNDOS`,
`PROMESA_MAX_DIAS`, `IMPORTACION_MAX_BYTES_DESCOMPRIMIDO`, `WS_REVALIDAR_SEGUNDOS` y `BUS_EVENTOS`. Con el proveedor
falso no hace falta configurar ninguna de ellas. Para Twilio real, ver [`docs/telefonia-twilio.md`](docs/telefonia-twilio.md).

## Probar la consola con el proveedor falso

Sin Twilio, sin credenciales y sin red. Es el modo por defecto (`TELEFONIA_PROVEEDOR=falso`) y no funciona con
`ENTORNO=produccion`, porque los endpoints de simulación no existen allí.

1. Arranque el sistema (con Docker o sin Docker, según la sección anterior) y cree el administrador.
2. Como administrador, en **Usuarios**, cree un usuario con rol `agente`.
3. Cree una campaña `venta` o `cobranza`. Importe un `.csv` o `.xlsx` con clientes y teléfonos móviles válidos.
   Active la campaña con `PATCH /api/v1/campanas/{id}` y el cuerpo `{"estado": "activa"}`. Activar exige al menos
   un cliente.
4. En el detalle de la campaña, pestaña **Agentes**, seleccione el agente y guarde.
5. Inicie sesión como agente. En **Consola**, cambie el estado a **Disponible**.
6. En la lista de trabajo, pulse **Tomar** en un registro. Aparece la ficha.
7. Pulse **Llamar a +57…** junto al teléfono. El servidor evalúa horario y frecuencia:
   - Dentro de franja (lunes a viernes de 07:00 a 19:00, sábado de 08:00 a 15:00, hora de Bogotá, sin festivo),
     la llamada se permite. Aparecen **Contesta**, **No contesta** y **Ocupado**.
   - Fuera de franja, la llamada queda **bloqueada** y la barra muestra `FUERA_DE_FRANJA`. Es el comportamiento
     esperado, no un error. Pruebe otra hora para la llamada permitida.
8. Pulse **Contesta** y después **Colgar**. Aparece el formulario de tipificación.
9. Tipifique, por ejemplo, **Promesa de pago** (cobranza) o **Contactado**. El registro queda gestionado y el
   agente vuelve a **Disponible**.
10. Como supervisor o administrador, abra **Supervisión** para ver el estado en vivo de los agentes.

Mismo flujo por API: `POST /api/v1/telefonia/simulacion/llamadas` con `{"campana_cliente_id": 15, "telefono_id": 21}`,
y después `POST /api/v1/telefonia/simulacion/llamadas/{id}/eventos` con `{"evento": "contestada"}`. Documentación
interactiva en `http://localhost:8000/docs`.

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

- [`docs/telefonia-twilio.md`](docs/telefonia-twilio.md): cómo funciona la voz, configuración de Twilio paso a paso,
  variables, proveedor falso y firma de webhooks.
- [`docs/consola-agente.md`](docs/consola-agente.md): guía de la consola para agentes y supervisores, tipificaciones,
  supervisión y procedimiento de soporte `liberar-gestion`.
- [`docs/cumplimiento-frecuencia.md`](docs/cumplimiento-frecuencia.md): horario, festivos y frecuencia de la Ley 2300
  (documento para el área jurídica).
- [`docs/importacion-csv.md`](docs/importacion-csv.md): formato de importación (CSV y Excel), reglas, límites y códigos de error.
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
  - [ADR-0010](docs/arquitectura/adr-0010-proveedor-whatsapp-twilio.md): proveedor de WhatsApp con Twilio (2B).
  - [ADR-0011](docs/arquitectura/adr-0011-modelo-omnicanal.md): modelo omnicanal (2B).
  - [ADR-0012](docs/arquitectura/adr-0012-cumplimiento-omnicanal.md): cumplimiento omnicanal, frecuencia y canales (2A y 2B-2E).
  - [ADR-0013](docs/arquitectura/adr-0013-webhooks-y-cola-de-trabajos.md): webhooks firmados, idempotencia y cola de trabajos.
  - [ADR-0014](docs/arquitectura/adr-0014-agente-ia-arquitectura-claude.md): arquitectura del agente IA con Claude (2C).
  - [ADR-0015](docs/arquitectura/adr-0015-agente-ia-autonomia-y-salvaguardas.md): autonomía y salvaguardas del agente IA (2C).
  - [ADR-0016](docs/arquitectura/adr-0016-traspaso-humano-y-supervision.md): traspaso a humano y supervisión (2C).
  - [ADR-0017](docs/arquitectura/adr-0017-consola-agente-y-tipificaciones.md): consola del agente, reservas y tipificaciones (2A).
  - [ADR-0018](docs/arquitectura/adr-0018-evaluacion-agente-ia.md): evaluación del agente IA (2C).

## Plan por fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Cimientos sin telefonía: auth con roles, campañas, importación CSV, exclusiones, cumplimiento (franjas y festivos) y auditoría. | Terminada |
| 2A | Consola del agente, llamada manual con Twilio (o falsa), tipificaciones, frecuencia de la Ley 2300, WebSocket e importación Excel. Ver [`fase-2.md`](docs/arquitectura/fase-2.md) §1-§6. | Terminada |
| 2B | WhatsApp base y bandeja humana (webhooks firmados, cola de trabajos, plantillas, opt-in). Ver [`fase-2.md`](docs/arquitectura/fase-2.md) §7.1. | Pendiente |
| 2C | Agente IA en WhatsApp con Claude: negociación dentro de límites, traspaso a humano, kill switch. Ver §7.2. | Pendiente |
| 2D | Campañas outbound de WhatsApp con cumplimiento por destinatario. Ver §7.3. | Pendiente |
| 2E | Llamadas de voz por WhatsApp (permiso de llamada, entrantes). Ver §7.4. | Pendiente |
| 2F | Operación y endurecimiento: retención, evaluación programada, reportes de IA y seguridad. Ver §7.5. | Pendiente |
| 3 | Marcador automático (preview y progresivo) y reintentos. | Pendiente |
| 4 | Reportes y exportación CSV, supervisión avanzada, escucha de grabaciones. | Pendiente |
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
