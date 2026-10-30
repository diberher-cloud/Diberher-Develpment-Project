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
│   │                        # 2B: twilio_webhook.py (firma común voz/WhatsApp) y whatsapp/ (proveedor, twilio, falso, parseo)
│   ├── trabajos/            # 2B: cola de trabajos (cola, registro, periódicos, mantenimiento) y modelos
│   ├── worker.py            # 2B: `python -m app.worker` (bucle, latido, señales, `--healthcheck`)
│   ├── saneamiento.py       # 2B: texto hostil (NUL y sustitutos Unicode) en la API y en los webhooks
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
│       ├── whatsapp/        # 2B: webhooks, configuración, plantillas, autorizaciones, envíos, estados, medios, opt-out, ventana
│       ├── conversaciones/  # 2B: conversaciones, mensajes, dueño, resolución del registro, cola de atención, cierre
│       ├── supervision/     # 2A: estado de agentes en vivo; 2B: estado de los trabajos y del worker
│       └── auditoria/       # registro de acciones sensibles
├── alembic/                 # env.py y versions/0001_esquema_inicial.py, 0002_consola_y_voz.py, 0003_whatsapp_bandeja.py
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
python -m app.worker                                    # 2B: worker de trabajos, en otra terminal
```

- `python -m app.worker --healthcheck` sale con `0` si hay un latido de los últimos 60 s, y con `1` si no. Detalle del
  worker, reintentos y `ENVIO_INCIERTO` en [`docs/whatsapp-twilio.md`](../docs/whatsapp-twilio.md), sección 4.

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
| `WHATSAPP_PROVEEDOR` | `falso` | `falso` (sin red) o `twilio`. Con `twilio` exige las `TWILIO_*` no vacías y `PUBLIC_BASE_URL` con `https://` (salvo `ENTORNO=test`). |
| `WHATSAPP_NUMERO_EMPRESA` | `+573000000001` | Remitente de WhatsApp en E.164. Solo se aceptan los entrantes dirigidos a este número. |
| `WHATSAPP_MARGEN_VENTANA_SEGUNDOS` | `60` | Margen antes del cierre de la ventana de 24 h (0 a 3600). |
| `WHATSAPP_MEDIA_MAX_BYTES` | `16777216` | Tamaño máximo de un adjunto que se descarga (1 KiB a 64 MiB). |
| `WHATSAPP_MEDIA_CONCURRENCIA` | `4` | Descargas de adjuntos simultáneas por proceso. Si se exceden: `429 DEMASIADAS_DESCARGAS`. |
| `WHATSAPP_MEDIA_DURACION_SEGUNDOS` | `30` | Duración total máxima de una descarga (5 a 300). |
| `WHATSAPP_HOSTS_MEDIOS` | `media.twiliocdn.com` | Hosts adicionales permitidos en las redirecciones de medios. **Sin verificar con cuenta real** (ver `docs/whatsapp-twilio.md`, sección 1.7). |
| `WHATSAPP_DIAS_RESOLUCION_PLANTILLA` | `30` | Días en los que una plantilla enviada decide el registro de un número (1 a 365). |
| `WHATSAPP_PAYLOAD_BAJA` | `BAJA` | `payload` del botón de baja. Un botón con ese `payload` equivale a baja de WhatsApp. |
| `WHATSAPP_FRASES_OPT_OUT` · `WHATSAPP_FRASES_OPT_OUT_TODOS` | vacío | Listas propias de frases de baja, separadas por `\|`. Vacío = listas por defecto. Si se definen, se desactivan los patrones de WhatsApp y de todos los canales. |
| `WHATSAPP_MENSAJE_OPT_OUT` · `WHATSAPP_MENSAJE_OPT_OUT_TODOS` | texto de ejemplo | Confirmación de baja por canal (máximo 1000 caracteres; vacío = no se envía). |
| `WHATSAPP_MENSAJE_ESPERA` | texto de ejemplo | Aviso de espera cuando no hay agentes disponibles (vacío = no se envía). |
| `WHATSAPP_MENSAJE_FUERA_DE_FRANJA` | texto de ejemplo | Aviso al retener una respuesta fuera de franja (vacío = no se envía). |
| `CONVERSACION_INACTIVIDAD_HORAS` | `24` | Horas sin mensajes tras las que se cierra una conversación (1 a 168). |
| `ATENCION_MAX_CONVERSACIONES_AGENTE` | `5` | Conversaciones abiertas simultáneas por agente (1 a 50). |
| `WORKER_INTERVALO_SEGUNDOS` | `1` | Espera del worker cuando no hay trabajos (0.1 a 60). |
| `WORKER_LOTE` | `10` | Trabajos que toma el worker en cada vuelta (1 a 100). |
| `WORKER_BLOQUEO_SEGUNDOS` | `300` | Reserva de un trabajo por un worker antes de poder retomarlo (30 a 3600). |
| `PURGA_EVENTOS_HUERFANOS_DIAS` | `7` | Días tras los que se borran los estados que no se enlazaron a un mensaje (1 a 365). |
| `TEST_DATABASE_URL` | — | Solo para `pytest -m postgres`. |

Con `TELEFONIA_PROVEEDOR=twilio` se exige: las variables `TWILIO_*` no vacías, `TWILIO_NUMERO_SALIENTE` en E.164 y
`PUBLIC_BASE_URL` con `https://` (salvo `ENTORNO=test`). Ningún valor puede terminar en barra. Detalle en
[`docs/telefonia-twilio.md`](../docs/telefonia-twilio.md#variables-de-entorno). Los cambios en el `.env` requieren
reiniciar el proceso (la configuración está en caché).

## Endpoints

Todos bajo `/api/v1`. Salvo `GET /salud` y `POST /auth/login`, requieren `Authorization: Bearer <jwt>`.
Contratos completos en `docs/arquitectura/fase-1.md` (§4), para la subfase 2A en `docs/arquitectura/fase-2.md` (§4) y
para la 2B en `docs/arquitectura/fase-2b.md` (§4).

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
| `POST /whatsapp/webhooks/entrante`, `POST /whatsapp/webhooks/estado` (2B) | firma de Twilio (sin JWT) |
| `GET /whatsapp/configuracion` (2B) | cualquier usuario activo |
| `GET /whatsapp/plantillas` (2B) | administrador, supervisor; agente solo con `campana_id` asignada y solo plantillas enviables |
| `POST /whatsapp/plantillas/sincronizar` (2B) | administrador |
| `PUT /whatsapp/plantillas/{id}` (2B) | administrador, supervisor |
| `GET/POST /autorizaciones`, `DELETE /autorizaciones/{id}` (2B) | administrador, supervisor |
| `GET /conversaciones` (2B) | todos; el agente solo ve las suyas |
| `GET /conversaciones/{id}`, `GET /conversaciones/{id}/mensajes` (2B) | dueño, administrador y supervisor |
| `POST /conversaciones/{id}/mensajes`, `POST /conversaciones/{id}/plantillas` (2B) | dueño (cualquier rol) |
| `POST /conversaciones/{id}/leida`, `POST /conversaciones/{id}/opt-out`, `POST /conversaciones/{id}/autorizacion` (2B) | dueño (cualquier rol) |
| `GET /conversaciones/{id}/mensajes/{mensaje_id}/media/{indice}` (2B) | dueño, administrador y supervisor |
| `GET /conversaciones/{id}/ficha`, `GET /conversaciones/{id}/registros-candidatos`, `PUT /conversaciones/{id}/registro` (2B) | ver: dueño, administrador y supervisor; vincular: dueño (agente) o cualquier A/S |
| `POST /conversaciones/{id}/tomar` (2B) | agente con campaña asignada y estado disponible; administrador y supervisor sin restricción de campaña |
| `POST /conversaciones/{id}/asignar` (2B) | administrador, supervisor |
| `POST /conversaciones/{id}/liberar` (2B) | dueño, administrador y supervisor |
| `POST /conversaciones/{id}/cerrar` (2B) | dueño (agente); administrador y supervisor sin ser dueños |
| `GET /atencion/cola` (2B) | todos; el agente solo ve las campañas asignadas con WhatsApp |
| `POST /atencion/tomar-siguiente` (2B) | agente |
| `POST /consola/registros/{id}/whatsapp/plantilla` (2B) | agente con el registro reservado |
| `GET /supervision/trabajos` (2B) | administrador, supervisor |
| `POST /whatsapp/simulacion/entrante`, `POST /whatsapp/simulacion/mensajes/{id}/estado` (2B) | cualquier usuario activo; solo con `WHATSAPP_PROVEEDOR=falso` y `ENTORNO` distinto de `produccion`; si no, 404 |
| `GET /exclusiones?canal=` (2B) | administrador, supervisor (filtro por canal `todos`, `voz` o `whatsapp`) |

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
   - `conversacion.mensaje` y `conversacion.estado` (2B): a administradores y supervisores siempre; al agente solo si
     la conversación es suya o lo era (`usuario_anterior_id`).
   - `atencion.cola` (2B): a todos los conectados, con solo ids (`cola_id`, `conversacion_id`, `campana_id`, `motivo`,
     `accion`). El filtrado por campañas asignadas llega en 2G.
   - `trabajo.fallido` (2B): solo a administradores y supervisores (`trabajo_id`, `tipo`, `codigo`).
   - Ningún evento contiene texto de mensajes ni números de teléfono.
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

**WhatsApp, conversaciones y trabajos (2B).**
- Los webhooks de WhatsApp validan `X-Twilio-Signature` con la URL `PUBLIC_BASE_URL + ruta + query`. Firma inválida →
  `403 FIRMA_INVALIDA`. El entrante persiste y encola; el procesamiento lo hace el worker. Un `MessageSid` repetido no
  crea nada.
- Los envíos aceptan una `idempotencia_clave` (UUID v4) para no duplicar un mensaje si se repite la petición: en
  `POST .../mensajes` y en `POST .../plantillas`. Repetirla devuelve el resultado existente (`200`) o `409 IDEMPOTENCIA_CONFLICTO`.
- Una plantilla bloqueada por cumplimiento responde `200` con `permitido=false` y sus motivos. No es un error HTTP.
- Códigos de negocio nuevos (2B): `CONVERSACION_NO_ASIGNADA` (403), `CAMPANA_NO_ASIGNADA` (403),
  `CONVERSACION_ASIGNADA`, `CONVERSACION_CERRADA`, `CONVERSACION_YA_VINCULADA`, `CONVERSACION_ABIERTA_OTRO_REGISTRO`,
  `VENTANA_CERRADA`, `VENTANA_ABIERTA`, `RESPUESTA_FUERA_DE_FRANJA`, `CLIENTE_OPT_OUT`, `WHATSAPP_NO_HABILITADO`,
  `CAPACIDAD_MAXIMA`, `AGENTE_NO_DISPONIBLE`, `AUTORIZACION_DUPLICADA`, `AUTORIZACION_REVOCADA_POR_OPT_OUT`,
  `PLANTILLA_NO_DISPONIBLE`, `PLANTILLA_VARIABLE_VACIA`, `PLANTILLA_MAPEO_INVALIDO`, `PLANTILLA_SIN_BAJA`,
  `TELEFONO_NO_VALIDO`, `REGISTRO_NO_COINCIDE`, `RESULTADO_INCOHERENTE`, `REGISTRO_NO_RESERVADO` (409, 422, 403 según el
  caso), `MEDIA_DEMASIADO_GRANDE` (413), `MEDIA_NO_DISPONIBLE` (404), `DEMASIADAS_DESCARGAS` (429) y
  `PROVEEDOR_NO_DISPONIBLE` (502). Tabla completa en [`docs/whatsapp-twilio.md`](../docs/whatsapp-twilio.md) y
  `docs/arquitectura/fase-2b.md`, sección 4.1.
- Los medios entrantes no se guardan: se descargan por un proxy autenticado, con validación de la URL (prefijo exacto
  de la cuenta), límite de tamaño y de concurrencia y cabeceras de seguridad.
- El texto hostil (NUL o sustitutos Unicode) se rechaza en toda la API con `422 VALIDACION` y se limpia en los webhooks.
- Los trabajos (`trabajos`) solo guardan ids y catálogos, nunca texto ni números. Ver
  [`docs/whatsapp-twilio.md`](../docs/whatsapp-twilio.md), sección 4.
