# Diberher Development Project

Plataforma web de **campañas outbound** para contact center en Colombia, de **venta** y de **cobranza**.
Incorpora el cumplimiento normativo colombiano como configuración: Ley 2300 de 2023 (horarios y frecuencia
de contacto), Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008, Registro de Números Excluidos (RNE) de la
CRC y festivos de Colombia (Ley 51 de 1983).

Este repositorio también contiene el equipo de agentes de IA con el que se desarrolla el proyecto. Está
resumido al final.

## Estado

**Fase 1, subfase 2A y subfase 2B terminadas**: probadas y aprobadas por la revisión.

- La subfase 2A es la consola del agente humano con voz Twilio.
- La subfase 2B es WhatsApp con Twilio y la bandeja humana. Se probó con el proveedor falso sobre SQLite y
  PostgreSQL 16. **La integración con una cuenta real de Twilio y de Meta no está verificada**: ver
  [`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md), sección 2.7, y [`docs/pendientes.md`](docs/pendientes.md), sección 7.

Las subfases 2C a 2G están pendientes (agente de IA en chat y voz, envíos masivos, llamadas de WhatsApp y
operación). Ver el [plan por fases](#plan-por-fases) y [`docs/arquitectura/fase-2.md`](docs/arquitectura/fase-2.md) §0.

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

**Subfase 2B** incluye:

- Proveedor de WhatsApp con Twilio o falso, tras una misma interfaz. Webhooks firmados, y descarga de medios
  con anti-SSRF.
- Webhooks de mensajes entrantes y de estado, idempotentes. Los entrantes se procesan con una cola de trabajos
  en la base de datos y un worker (`python -m app.worker`), con reintentos, recuperación de bloqueos y purgas.
- Conversaciones con ventana de 24 h, resolución del registro de campaña y bandeja humana: cola de atención,
  tomar, asignar, liberar, responder, vincular, cerrar con tipificación y registrar autorización o baja.
- Plantillas sincronizadas desde Twilio, con variables de una lista blanca y activación por administrador o
  supervisor.
- Autorizaciones (opt-in) y bajas (opt-out) por canal. Exclusiones con canal (voz, WhatsApp o todos).
- Medios entrantes por proxy autenticado, sin almacenarlos.
- Simulador de WhatsApp para desarrollo, fuera de producción.

Guías: [`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md) (configuración, worker y solución de problemas) y
[`docs/bandeja-whatsapp.md`](docs/bandeja-whatsapp.md) (uso de la bandeja).

**Pendiente de validar con Twilio real** (2A y 2B): la llamada a un móvil, la firma de los webhooks a través de un
túnel, el aviso de grabación y el entrante y los estados de WhatsApp. Sin credenciales, toda la consola y la
bandeja se prueban con el proveedor falso. Ver [`docs/pendientes.md`](docs/pendientes.md), secciones 5 y 7.

## Requisitos

- Python 3.12 o superior.
- Node.js 22 LTS.
- Docker y Docker Compose (opcional). Compose levanta PostgreSQL 16 y necesita la versión 2.24 o superior para
  leer el `.env`. Sin Docker, el backend usa SQLite por defecto.

## Arranque con Docker Compose

```bash
# 1. Configuración: copie la plantilla y defina JWT_SECRETO (mínimo 32 caracteres)
cp .env.example .env
#    Edite .env. Compose no arranca si JWT_SECRETO falta. No use el valor de ejemplo.
#    Opcional: defina ADMIN_PASSWORD para crear el administrador sin preguntar.

# 2. Levante los servicios (db, backend, worker y frontend)
docker compose up --build -d

# 3. Espere a que el backend termine las migraciones y arranque
docker compose logs -f backend      # Ctrl+C cuando aparezca "Application startup complete"

# 4. Cree el primer administrador (no hay usuarios por defecto)
docker compose exec backend python -m app.cli crear-admin --email admin@empresa.co --nombre "Ana Admin"
```

Al arrancar, el backend ejecuta `alembic upgrade head` y `generar-festivos` (2025 a 2028) y después
`uvicorn` con recarga automática. El servicio `worker` espera a que el backend esté sano.

| Servicio | URL | Notas |
|---|---|---|
| Interfaz | http://localhost:5173 | Inicie sesión con el administrador creado. |
| API | http://localhost:8000/api/v1/salud | Documentación interactiva en `/docs`. |
| PostgreSQL | `127.0.0.1:5432` | Publicado solo en localhost. |
| Worker | — | Sin puerto. Su estado: `docker compose ps` (healthcheck). |

Las variables del `.env` llegan a `backend` y a `worker` a través de `env_file`. Así, `TELEFONIA_*`, `TWILIO_*`,
`WHATSAPP_*`, `WORKER_*` y las demás se pasan a los dos contenedores. Para Twilio, ver
[`docs/telefonia-twilio.md`](docs/telefonia-twilio.md#variables-de-entorno) y
[`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md#3-variables-de-entorno).

Para reiniciar la base de datos desde cero (incluidos los datos): `docker compose down -v`.

## Arranque sin Docker

Use SQLite (por defecto) o PostgreSQL local. Hacen falta tres terminales: la API, el worker y el frontend.

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
# Worker (desde backend/, en otra terminal, con el mismo .env y la misma base de datos que la API)
cd backend && source .venv/bin/activate
python -m app.worker                    # Ctrl+C o SIGTERM para parar
python -m app.worker --healthcheck      # sale 0 si hay latido de los últimos 60 s, si no 1
```

Sin el worker, los mensajes entrantes quedan en `recibido` y los salientes en `pendiente`. Con SQLite, los eventos
del worker no llegan al navegador en tiempo real: recargue la página. Con PostgreSQL sí llegan.

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

Variables nuevas de la subfase 2B (todas en `.env.example`): `WHATSAPP_PROVEEDOR` (por defecto `falso`),
`WHATSAPP_NUMERO_EMPRESA`, `WHATSAPP_HOSTS_MEDIOS`, los textos automáticos (`WHATSAPP_MENSAJE_*`), las listas de baja
(`WHATSAPP_FRASES_OPT_OUT*`), los límites de medios y de ventana, `CONVERSACION_INACTIVIDAD_HORAS`,
`ATENCION_MAX_CONVERSACIONES_AGENTE`, `WORKER_INTERVALO_SEGUNDOS`, `WORKER_LOTE`, `WORKER_BLOQUEO_SEGUNDOS` y
`PURGA_EVENTOS_HUERFANOS_DIAS`. Con el proveedor falso no hace falta configurar ninguna. La tabla completa está en
[`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md#3-variables-de-entorno).

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

## Probar WhatsApp con el simulador

Sin Twilio y sin red. Requiere `WHATSAPP_PROVEEDOR=falso` (es el valor por defecto) y `ENTORNO` distinto de
`produccion`. Con el proveedor falso, los mensajes se quedan en memoria del proceso; nada sale a la red. Hace falta
el worker en marcha (con Docker, ya está; sin Docker, véase la sección "Arranque sin Docker").

1. Arranque el sistema y cree el administrador. Con Docker, el worker ya funciona.
2. **Campaña con WhatsApp.** En la ficha de la campaña, marque **Habilitar WhatsApp en esta campaña**. Importe
   clientes con un móvil (por ejemplo, `3001234567`) y actívela. Asigne el agente en la pestaña **Agentes**.
3. **Plantillas.** Como administrador, en **Plantillas de WhatsApp** (`/whatsapp/plantillas`), pulse **Sincronizar**.
   Aparecen cuatro plantillas fijas (`HXfalso0001` a `HXfalso0004`). Edite `HXfalso0001` (`recordatorio_cobranza`):
   finalidad `cobranza`, mapeo `1 → primer_nombre` y `2 → empresa`, y actívela.
4. **Autorización.** En **Autorizaciones** (administrador o supervisor), registre una autorización para el móvil del
   cliente: finalidad `cobranza` y una evidencia de al menos 5 caracteres. Sin ella, las plantillas se bloquean
   (`SIN_AUTORIZACION`).
5. **Entrante.** En **Simulador WhatsApp** (`/whatsapp/simulador`), en *Enviar como cliente*, escriba el número del
   cliente y un texto, y envíe. La conversación aparece en la cola de **Bandeja**: con motivo `entrante` si el número
   está en una campaña activa con WhatsApp, o con motivo `sin_campana` si no (solo la ven supervisores y
   administradores). Si el worker no está en marcha, no aparece.
6. **Atender.** Como agente (asignado a la campaña y en estado disponible), pulse **Tomar siguiente** en la bandeja,
   responda con texto y observe el estado del mensaje (`pendiente`, `enviado`).
7. **Estados.** En el simulador, en *Cambiar el estado de los mensajes salientes*, elija la conversación y el estado
   `delivered` o `read`. La bandeja muestra el cambio.
8. **Baja.** Desde el simulador, envíe un texto de baja como `STOP`, o marque la casilla del botón de baja. La
   conversación se cierra y el número queda excluido para WhatsApp.
9. **Plantilla fuera de ventana.** Un cliente que no ha escrito no tiene ventana abierta. Como agente, en la consola,
   tome un registro de la campaña y, en su ficha, pulse **Enviar plantilla** junto al teléfono. Si el cliente tiene
   baja (paso 8), la plantilla se bloquea con el motivo `EXCLUIDO`.

Documentación del flujo y de sus errores: [`docs/bandeja-whatsapp.md`](docs/bandeja-whatsapp.md) y
[`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md), secciones 5 y 6. Los números que terminan en `0000` simulan un
error permanente del proveedor (`63003`), y los que terminan en `9999`, un error transitorio (`429`).

## Tests y lint

| Parte | Comando | Notas |
|---|---|---|
| Backend | `cd backend && pytest` | Sin Docker ni PostgreSQL (SQLite en memoria). |
| Backend | `cd backend && ruff check .` | Lint con `line-length = 100`. |
| Backend, PostgreSQL | `TEST_DATABASE_URL=… pytest -m postgres` | Migraciones y concurrencia contra una base vacía y dedicada. |
| Frontend | `cd frontend && npm test -- --run` | Vitest y Testing Library. |
| Frontend | `cd frontend && npm run lint` | ESLint. |
| Frontend | `cd frontend && npm run build` | `tsc -b` y build de Vite. |

## Documentación

- [`docs/whatsapp-twilio.md`](docs/whatsapp-twilio.md): cómo funciona WhatsApp, configuración de Twilio y Meta paso a
  paso, variables, worker, simulación y solución de problemas.
- [`docs/bandeja-whatsapp.md`](docs/bandeja-whatsapp.md): guía de la bandeja para agentes y supervisores.
- [`docs/telefonia-twilio.md`](docs/telefonia-twilio.md): cómo funciona la voz, configuración de Twilio paso a paso,
  variables, proveedor falso y firma de webhooks.
- [`docs/consola-agente.md`](docs/consola-agente.md): guía de la consola para agentes y supervisores, tipificaciones,
  supervisión y procedimiento de soporte `liberar-gestion`.
- [`docs/cumplimiento-frecuencia.md`](docs/cumplimiento-frecuencia.md): horario, festivos, frecuencia, autorización,
  bajas y exclusiones por canal de la Ley 2300 (documento para el área jurídica).
- [`docs/importacion-csv.md`](docs/importacion-csv.md): formato de importación (CSV y Excel), autorización de WhatsApp,
  reglas, límites y códigos de error.
- [`docs/pendientes.md`](docs/pendientes.md): validación legal pendiente, supuestos a confirmar y deuda para próximas fases.
- [`backend/README.md`](backend/README.md) y [`frontend/README.md`](frontend/README.md): estructura, comandos,
  endpoints, eventos y convenciones.
- [`CHANGELOG.md`](CHANGELOG.md): cambios por versión.

### Arquitectura

- [`docs/arquitectura/README.md`](docs/arquitectura/README.md): visión general, componentes, modelo de datos y plan por fases.
- [`docs/arquitectura/fase-1.md`](docs/arquitectura/fase-1.md): alcance, esquema de base de datos, contratos de API y tareas de la Fase 1.
- [`docs/arquitectura/fase-2.md`](docs/arquitectura/fase-2.md): plan de la Fase 2 (subfases 2A a 2G, y revisión de alcance de la IA en voz).
- [`docs/arquitectura/fase-2b.md`](docs/arquitectura/fase-2b.md): diseño de la subfase 2B (esquema, contratos, tareas y QA).
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
  - [ADR-0014](docs/arquitectura/adr-0014-agente-ia-arquitectura-claude.md): arquitectura del agente IA con Claude (2C-2D).
  - [ADR-0015](docs/arquitectura/adr-0015-agente-ia-autonomia-y-salvaguardas.md): autonomía y salvaguardas del agente IA (2C-2D).
  - [ADR-0016](docs/arquitectura/adr-0016-traspaso-humano-y-supervision.md): traspaso a humano y supervisión (2C-2D).
  - [ADR-0017](docs/arquitectura/adr-0017-consola-agente-y-tipificaciones.md): consola del agente, reservas y tipificaciones (2A).
  - [ADR-0018](docs/arquitectura/adr-0018-evaluacion-agente-ia.md): evaluación del agente IA.
  - [ADR-0019](docs/arquitectura/adr-0019-whatsapp-bandeja-humana.md): WhatsApp base y bandeja humana (2B).
  - [ADR-0020](docs/arquitectura/adr-0020-agente-ia-voz-conversationrelay.md): agente IA de voz con ConversationRelay (2D).
  - [ADR-0021](docs/arquitectura/adr-0021-marcador-automatico-voz-ia.md): marcador automático con IA (2D).

## Plan por fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Cimientos sin telefonía: auth con roles, campañas, importación CSV, exclusiones, cumplimiento (franjas y festivos) y auditoría. | Terminada |
| 2A | Consola del agente y voz: asignación, reservas, softphone de Twilio (o falso), tipificaciones, frecuencia de la Ley 2300, WebSocket e importación Excel. | Terminada |
| 2B | WhatsApp base y bandeja humana: `ProveedorWhatsApp` (Twilio y falso), webhooks firmados, cola de trabajos y worker, conversaciones con ventana de 24 h, plantillas, opt-in y opt-out, exclusiones por canal y plantilla individual. | Terminada (probada con el proveedor falso; Twilio real pendiente) |
| 2C | Núcleo del agente IA y chat de WhatsApp: agente con Claude que atiende el chat con límites de negocio, verificación de identidad, traspaso a humano, kill switch, presupuesto y evaluación. | Pendiente |
| 2D | Agente IA de voz telefónica y marcador IA: sesiones con ConversationRelay, AMD, aviso legal, transferencia a la consola, entrantes y marcador con concurrencia y reintentos. | Pendiente |
| 2E | Campañas masivas de WhatsApp: envíos de plantillas con ritmo y cumplimiento por destinatario, con las respuestas atendidas por la IA. | Pendiente |
| 2F | Llamadas de WhatsApp atendidas por IA, con permiso de llamada, salientes por el marcador IA y entrantes a la IA. | Pendiente |
| 2G | Operación y endurecimiento: retención y anonimización, evaluación programada, reportes, costes por canal, alertas y pruebas de carga. | Pendiente |
| 3 | Marcador para campañas humanas (preview y progresivo, opcional). | Pendiente |
| 4 | Supervisión y reportes: panel completo, reportes de contactabilidad y promesas, exportación CSV y escucha de grabaciones. | Pendiente |
| 5 | Posterior (opcional): predictivo, escucha y susurro, STT y TTS propios, SSO y proveedor directo de WhatsApp. | Opcional |

Detalle en [`docs/arquitectura/README.md`](docs/arquitectura/README.md) (§8) y [`docs/arquitectura/fase-2.md`](docs/arquitectura/fase-2.md) (§0).

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
