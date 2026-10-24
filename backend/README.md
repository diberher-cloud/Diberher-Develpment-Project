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
│   ├── reloj.py             # ahora() inyectable (get_reloj; los tests lo sustituyen)
│   ├── logging_seguro.py    # enmascara token= y ticket= en los logs de uvicorn
│   ├── catalogos.py         # resultados, estados de agente y de llamada (enumeraciones)
│   ├── cli.py               # crear-admin, generar-festivos, liberar-gestion
│   ├── integraciones/       # 2A: firma de Twilio (pura) y proveedor de telefonía (twilio | falso)
│   ├── tiempo_real/         # 2A: bus de eventos, conexiones WebSocket, escucha LISTEN, tickets
│   └── modulos/
│       ├── auth/            # login y me
│       ├── usuarios/        # alta, edición y roles
│       ├── campanas/        # campañas, máquina de estados y asignación de agentes (2A)
│       ├── clientes/        # listado de clientes de una campaña
│       ├── importacion/     # CSV y XLSX: lectores, normalización, teléfonos (funciones puras) + servicio
│       ├── exclusiones/     # números excluidos y carga masiva
│       ├── cumplimiento/    # políticas, festivos, motor de horario (puro), frecuencia (puro, 2A)
│       ├── consola/         # 2A: estados del agente, reservas, ficha, tipificaciones y efectos (puros)
│       ├── telefonia/       # 2A: TwiML saliente, webhooks, finalización y simulación
│       ├── supervision/     # 2A: estado de agentes en vivo
│       └── auditoria/       # registro de acciones sensibles
├── alembic/                 # env.py y versions/0001_esquema_inicial.py, 0002_consola_y_voz.py
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
`normalizacion.py`, `lector_csv.py`, `lector_xlsx.py`, `politica.py`, `festivos.py`, `motor.py`) no accede a BD ni a red.
En 2A, también son puras: `cumplimiento/frecuencia.py`, `consola/estados.py`, `consola/efectos.py`,
`consola/guion.py`, `telefonia/twiml.py` e `integraciones/twilio_firma.py`.

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
- `liberar-gestion --llamada-id N --resultado no_contesta|numero_errado|contactado` es un procedimiento de soporte.
  Tipifica como sistema una llamada que el agente no tipificó y libera su reserva. Comportamiento y límites en
  [`docs/consola-agente.md`](../docs/consola-agente.md), sección 10.
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
| `EMPRESA_NOMBRE` | `Mi Empresa S.A.S.` | Nombre que sustituye `{{empresa}}` en el guion. |
| `TELEFONIA_PROVEEDOR` | `falso` | `falso` (sin red ni credenciales) o `twilio`. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL pública **exacta** de la API, sin barra final. Con `twilio` debe ser `https://`. La firma de los webhooks depende de ella. |
| `TWILIO_ACCOUNT_SID` | vacío | Obligatoria con `twilio`. |
| `TWILIO_AUTH_TOKEN` | `token-falso-solo-desarrollo` | Valida las firmas. Obligatoria con `twilio`. En `ENTORNO=produccion` no puede ser el valor de ejemplo ni vacío. |
| `TWILIO_API_KEY_SID` | vacío | Obligatoria con `twilio`. |
| `TWILIO_API_KEY_SECRET` | vacío | Obligatoria con `twilio`. |
| `TWILIO_TWIML_APP_SID` | vacío | Obligatoria con `twilio`. |
| `TWILIO_NUMERO_SALIENTE` | vacío | Número de voz en E.164 (`+57…`). Obligatoria con `twilio`. |
| `TELEFONIA_TOKEN_TTL_SEGUNDOS` | `3600` | Vida del token del softphone. |
| `TELEFONIA_GRABAR` | `true` | Graba la llamada y reproduce el aviso. Con `false`, no hay aviso. |
| `TELEFONIA_AVISO_GRABACION` | texto de ejemplo | Aviso que oye el cliente. Pendiente de aprobación jurídica. |
| `TELEFONIA_IDIOMA_VOZ` | `es-MX` | Idioma de los `<Say>`. |
| `TELEFONIA_MENSAJE_BLOQUEO` | texto de ejemplo | Mensaje de las llamadas bloqueadas. |
| `CONSOLA_RESERVA_MINUTOS` | `15` | Duración de la reserva de un registro (se renueva con la llamada). |
| `CONSOLA_DESCONEXION_SEGUNDOS` | `60` | Segundos sin WebSocket tras los que un agente `disponible` o en `pausa` pasa a `desconectado`. |
| `PROMESA_MAX_DIAS` | `60` | Días máximos para la fecha de una promesa de pago. |
| `IMPORTACION_MAX_BYTES_DESCOMPRIMIDO` | `104857600` (100 MiB) | Tamaño descomprimido máximo de un `.xlsx`. |
| `WS_REVALIDAR_SEGUNDOS` | `60` | Cada cuánto se revalida en un WebSocket que el usuario sigue activo y con el mismo rol. |
| `BUS_EVENTOS` | `auto` | `auto` (PostgreSQL si `DATABASE_URL` es PostgreSQL; si no, memoria), `memoria` o `postgres`. |
| `TEST_DATABASE_URL` | — | Solo para `pytest -m postgres`. |

Con `TELEFONIA_PROVEEDOR=twilio` se exige: las variables `TWILIO_*` no vacías, `TWILIO_NUMERO_SALIENTE` en E.164 y
`PUBLIC_BASE_URL` con `https://` (salvo `ENTORNO=test`). Ningún valor puede terminar en barra. Detalle en
[`docs/telefonia-twilio.md`](../docs/telefonia-twilio.md#variables-de-entorno). Los cambios en el `.env` requieren
reiniciar el proceso (la configuración está en caché).

## Endpoints

Todos bajo `/api/v1`. Salvo `GET /salud` y `POST /auth/login`, requieren `Authorization: Bearer <jwt>`.
Contratos completos en `docs/arquitectura/fase-1.md` (§4) y, para la subfase 2A, en `docs/arquitectura/fase-2.md` (§4).

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
| `POST /cumplimiento/evaluar` | cualquier usuario activo; con `cliente_id`, solo administrador y supervisor |
| `GET /festivos?anio=`, `POST /festivos`, `PATCH /festivos/{id}` | lectura: todos; escritura: administrador |
| `POST /festivos/generar` | administrador |
| `GET/PUT /campanas/{id}/agentes` (2A) | administrador, supervisor |
| `GET /campanas/{id}/tipificaciones` (2A) | administrador, supervisor |
| `GET/PUT /consola/estado`, `GET /consola/campanas`, `GET /consola/registros`, `GET /consola/registros/{id}` (2A) | agente |
| `POST /consola/registros/{id}/tomar`, `POST /consola/registros/{id}/soltar` (2A) | agente |
| `GET /consola/llamadas/{id}`, `POST /consola/tipificaciones` (2A) | agente |
| `POST /telefonia/token` (2A) | agente |
| `POST /telefonia/twiml/saliente`, `POST /telefonia/twiml/aviso-grabacion`, `POST /telefonia/twiml/dial-terminado` (2A) | firma de Twilio (sin JWT) |
| `POST /telefonia/webhooks/estado`, `POST /telefonia/webhooks/grabacion` (2A) | firma de Twilio (sin JWT) |
| `POST /telefonia/simulacion/llamadas`, `POST /telefonia/simulacion/llamadas/{id}/eventos` (2A) | agente; solo con `TELEFONIA_PROVEEDOR=falso` y `ENTORNO` distinto de `produccion`; si no, 404 |
| `GET /supervision/agentes` (2A) | administrador, supervisor |
| `POST /ws/ticket` (2A) | cualquier usuario activo |
| `GET /ws?ticket=<ticket>` (WebSocket, 2A) | ticket de un solo uso (30 s) |

`POST /campanas/{id}/importaciones` y `POST /exclusiones/importar` aceptan `.csv` y `.xlsx` desde 2A.

### Tiempo real (WebSocket, 2A)

1. El cliente llama a `POST /api/v1/ws/ticket` con su Bearer → `200 {"ticket": "<aleatorio>", "expira_en": 30}`.
   El ticket dura 30 s, es de un solo uso y se guarda su hash SHA-256 en `tickets_ws`.
2. Abre `GET /api/v1/ws?ticket=<ticket>`. Un ticket inválido, caducado o ya usado cierra la conexión con **4401**.
   También se cierra con 4401 al vencer el JWT con el que se pidió el ticket, o si el usuario deja de estar activo o
   cambia de rol (revalidación cada `WS_REVALIDAR_SEGUNDOS`). La cola por conexión admite 1000 eventos; al
   desbordarla, la conexión se cierra con **1013**.
3. Primer mensaje: `{"tipo":"conexion.lista","datos":{"usuario_id":5,"rol":"agente"},"emitido_en":"…Z"}`.
   El cliente envía `{"tipo":"ping"}` cada 30 s y recibe `{"tipo":"pong",…}`. Otros mensajes del cliente se ignoran.
4. Todos los eventos tienen la forma `{"tipo", "datos", "emitido_en"}`:
   - `agente.estado`, `llamada.estado`: a administradores, supervisores y al propio agente.
   - `consola.registro`: a todos los conectados (solo ids).
5. Los eventos se publican **dentro de la transacción** y se entregan solo tras confirmarla. Un rollback no emite nada.
   Con PostgreSQL usan `pg_notify` y `LISTEN`. Con SQLite o en tests, un bus en memoria.
6. El estado autoritativo está en la base de datos. Al reconectar, el cliente recarga por REST.

Con varias instancias de la API, la desconexión por inactividad no es multiinstancia (ver
[`docs/pendientes.md`](../docs/pendientes.md), sección 5).

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

**Importación.** Reglas de archivo (CSV y XLSX), teléfonos y códigos de fila en `docs/importacion-csv.md`.

**Telefonía, consola y cumplimiento (2A).**
- Los webhooks y TwiML de Twilio validan `X-Twilio-Signature` antes de procesar nada. Firma ausente o incorrecta →
  `403 FIRMA_INVALIDA`. La firma depende de `PUBLIC_BASE_URL`, que debe ser exacta.
- Códigos de negocio nuevos (409, 422, 403): `REGISTRO_RESERVADO`, `REGISTRO_NO_DISPONIBLE`, `REGISTRO_NO_RESERVADO`,
  `TIPIFICACION_PENDIENTE`, `AGENTE_EN_LLAMADA`, `LLAMADA_EN_CURSO`, `LLAMADA_YA_TIPIFICADA`, `LLAMADA_BLOQUEADA`,
  `RESULTADO_INCOHERENTE`, `RESULTADO_NO_PERMITIDO`, `VOLVER_A_LLAMAR_FUERA_DE_FRANJA`, `CAMPANA_NO_ASIGNADA`,
  `USUARIO_CON_GESTION_PENDIENTE`. La lista completa y sus casos, en `docs/arquitectura/fase-2.md` §4 y
  `docs/consola-agente.md`.
- Los teléfonos de `/consola/*` se devuelven enmascarados (`numero_mascara`). Nunca se devuelve un E.164 completo.
- Las llamadas se comprueban con `evaluar_contacto` (horario y frecuencia) en el servidor, antes de cada `<Dial>`.
  Ver [`docs/cumplimiento-frecuencia.md`](../docs/cumplimiento-frecuencia.md).
