# Arquitectura — Plataforma de campañas outbound (contact center, Colombia)

> Documento vivo del arquitecto. Fuente de verdad para el equipo junto con los ADR de esta carpeta
> y el detalle de la fase en curso (`fase-1.md`).

## 1. Objetivo

Aplicación web para ejecutar campañas **outbound** de un contact center en Colombia:

- **Venta / oferta de productos** a clientes.
- **Recuperación de cartera** (cobranza).

Con cumplimiento normativo colombiano incorporado como **configuración** (no como código fijo):
Ley 2300 de 2023 ("dejen de fregar"), Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008 (Habeas Data
financiero), Registro de Números Excluidos (RNE) de la CRC, festivos colombianos (Ley 51 de 1983,
"Ley Emiliani") y zona horaria `America/Bogota`.

Roles: **administrador**, **supervisor**, **agente**.

## 2. Vista de componentes

```
                    Navegador (React + TS + Vite)
   ┌──────────────────────────────────────────────────────────────┐
   │ Admin / Supervisor UI      Consola del agente                │
   │ (campañas, bases, reglas,  (ficha, guion, tipificación,      │
   │  panel tiempo real)         softphone Twilio Voice JS SDK)   │
   └───────┬───────────────────────────┬───────────────┬──────────┘
           │ HTTPS REST /api/v1        │ WebSocket     │ WebRTC (voz)
           ▼                           ▼ /api/v1/ws    ▼
   ┌──────────────────────────────────────────┐   ┌────────────────┐
   │ API FastAPI (monolito modular)           │◀──│ Twilio Voice   │
   │  auth · usuarios · campanas · clientes   │   │ (PSTN Colombia)│
   │  importacion · exclusiones · cumplimiento│──▶│ REST Calls API │
   │  telefonia · consola · supervision ·     │   └────────────────┘
   │  reportes · auditoria                    │     webhooks (TwiML,
   └──────────┬───────────────────────────────┘     estado, grabación)
              │ SQLAlchemy 2 / LISTEN-NOTIFY
              ▼
   ┌──────────────────────┐      ┌─────────────────────────────────┐
   │ PostgreSQL 16        │◀────▶│ Worker del marcador (fase 3)     │
   │ (datos + cola +      │      │ mismo código, otro proceso:      │
   │  bus de eventos)     │      │ `python -m app.marcador`         │
   └──────────────────────┘      └─────────────────────────────────┘
```

Decisiones clave:

| ADR | Decisión |
|---|---|
| [0001](adr-0001-monolito-modular.md) | Monolito modular FastAPI + SPA React + PostgreSQL; sin microservicios ni broker externo en el MVP |
| [0002](adr-0002-motor-cumplimiento-configurable.md) | Motor de cumplimiento puro (sin E/S) alimentado por políticas versionadas en BD y tabla de festivos |
| [0003](adr-0003-integracion-twilio.md) | Twilio: softphone WebRTC, TwiML App, webhooks firmados, adaptador `ProveedorTelefonia` con doble falso para tests |
| [0004](adr-0004-tiempo-real-websocket-listen-notify.md) | Tiempo real con WebSocket nativo de FastAPI + `LISTEN/NOTIFY` de PostgreSQL (sin Redis en el MVP) |
| [0005](adr-0005-autenticacion-jwt-roles.md) | JWT HS256 de acceso (8 h), rol y estado leídos de BD en cada petición |
| [0006](adr-0006-persistencia-y-tests-sin-docker.md) | SQLAlchemy 2 síncrono + Alembic; SQL portable para que los tests corran en SQLite sin Docker |
| [0007](adr-0007-normalizacion-telefonos-e164.md) | Teléfonos normalizados a E.164 con `phonenumbers`, solo móviles y fijos colombianos |
| [0008](adr-0008-proteccion-datos-personales.md) | Habeas Data: minimización, auditoría, grabación con aviso, exclusiones por finalidad |
| [0009](adr-0009-marcador-preview-progresivo.md) | Marcador preview + progresivo 1:1 con cola en PostgreSQL (`SKIP LOCKED`); predictivo pospuesto |

## 3. Módulos del backend

Todos bajo `backend/app/modulos/<modulo>/` con la misma forma: `modelos.py` (SQLAlchemy),
`esquemas.py` (Pydantic), `servicio.py` (lógica), `router.py` (FastAPI). La lógica pura (sin BD ni
red) vive en archivos propios y se prueba aislada.

| Módulo | Responsabilidad | Fase |
|---|---|---|
| `auth` | Login, emisión/validación de JWT, `me` | 1 |
| `usuarios` | Alta/edición/desactivación de usuarios y roles | 1 |
| `campanas` | Campañas (tipo, estado, guion, reintentos) | 1 |
| `clientes` | Cliente global (documento), teléfonos, asignación cliente↔campaña | 1 |
| `importacion` | CSV (fase 1) / Excel (fase 2): lectura, normalización, dedupe, resumen de errores | 1 |
| `exclusiones` | Números excluidos (RNE, solicitud del titular, número errado, manual) por finalidad | 1 |
| `cumplimiento` | Políticas versionadas, festivos, **motor puro** (franjas, festivos; frecuencia en fase 3) | 1 |
| `auditoria` | Registro de acciones sensibles (Habeas Data) | 1 |
| `telefonia` | Adaptador Twilio, tokens de acceso, TwiML, webhooks, grabaciones | 2 |
| `consola` | Estado del agente, ficha, tipificaciones, promesas de pago, ventas | 2 |
| `marcador` | Cola de marcación, preview/progresivo, reintentos, worker | 3 |
| `tiempo_real` | WebSocket, bus de eventos (`LISTEN/NOTIFY`) | 3 |
| `supervision` / `reportes` | Panel en vivo, KPIs, exportaciones | 4 |

## 4. Modelo de datos principal (MVP completo)

```
usuarios ─┐
          ├─< campanas ─< campana_clientes >─ clientes ─< telefonos
          │                    │     ▲
          │                    │     └── importaciones ─< importacion_errores
          │                    ├─< intentos_contacto ─── llamadas ─< eventos_llamada
          │                    │                           └── grabaciones
          │                    ├─< tipificaciones ─┬─ promesas_pago ─< pagos (conciliación)
          │                    │                   └─ ventas
          │                    └─< cola_marcacion (fase 3)
          ├─ estados_agente (fase 2)
          └─ auditoria
exclusiones (numero_e164, motivo, aplica_a)        politicas_cumplimiento (tipo, versión, JSON)
festivos (fecha, nombre, origen, activo)
```

Puntos clave:

- **`clientes` es global** (único por `tipo_documento + numero_documento`): los límites de frecuencia
  de la Ley 2300 son por consumidor y se cuentan **entre campañas**, no por campaña.
- **`campana_clientes`** guarda los datos propios de la campaña (deuda/mora u oferta, estado, intentos,
  próximo intento).
- **`intentos_contacto`** (fase 2-3) es el historial que alimenta las reglas de frecuencia: canal,
  momento, si hubo **contacto directo** y resultado.
- **Exclusiones** se evalúan **en el momento de marcar** (fuente de verdad), además de informarse en la importación.
- Fechas/horas se guardan en **UTC** (`timestamptz`); se presentan y evalúan en `America/Bogota`.
- Montos en COP como `NUMERIC(14,2)`.

## 5. Tiempo real

WebSocket `GET /api/v1/ws?token=<jwt>` (fase 3). Eventos tipados (`agente.estado`, `llamada.estado`,
`campana.metricas`, `marcador.asignacion`). Cualquier proceso (API o worker) publica con
`NOTIFY eventos, '<json corto con ids>'`; cada instancia de la API escucha y reenvía a los sockets
suscritos según rol. Ver ADR-0004.

## 6. Integración Twilio (resumen)

- **Softphone**: `@twilio/voice-sdk` 2.x en el navegador; el backend emite Access Tokens con
  `VoiceGrant` (identity `agente_<id>`), TTL corto, renovación automática.
- **Preview/manual**: el agente pulsa *Llamar* → `device.connect({params:{campana_cliente_id, telefono_id}})`
  → Twilio pide TwiML a `/api/v1/telefonia/twiml/saliente` → el backend **valida firma, cumplimiento,
  exclusiones y frecuencia** y responde `<Dial>` al número resuelto en servidor (el navegador nunca envía
  el número).
- **Progresivo**: el worker crea la llamada al cliente vía REST (`machine_detection`), y al contestar
  humano la puentea a `<Client>agente_<id></Client>` (1 llamada por agente libre: sin abandono).
- **Webhooks** de estado y grabación validados con `X-Twilio-Signature`, idempotentes por `CallSid`+estado.
- Todo detrás de la interfaz `ProveedorTelefonia`; en tests y en desarrollo sin credenciales se usa
  `ProveedorTelefoniaFalso`.

## 7. Cumplimiento normativo como configuración

| Norma | Cómo se modela | Fase |
|---|---|---|
| Ley 2300/2023 art. 3 — franjas L-V 07:00-19:00, sáb 08:00-15:00, sin domingos ni festivos | `politicas_cumplimiento.configuracion.franjas` + `permitir_festivos` por tipo de campaña | 1 |
| Ley 2300/2023 — tras contacto directo: no varios canales en la misma semana ni más de una vez el mismo día | `configuracion.frecuencia` (`max_contactos_dia`, `max_canales_semana`, `semana`, `solo_tras_contacto_directo`) | esquema en 1, evaluación en 3 |
| Ley 2300/2023 — excepción: el consumidor autoriza otros horarios por instrumento posterior al contrato | `autorizaciones_horario` por cliente (pendiente de confirmar alcance) | 3 |
| RNE (CRC, Res. 5050/2016 mod. Res. 7356/2024) — llamadas comerciales/publicitarias | `exclusiones` con `motivo=rne`, `aplica_a=venta`; carga masiva CSV; webservice CRC en fase 5 | 1 |
| Festivos (Ley 51/1983) | Cálculo puro (Pascua + traslado a lunes) que siembra la tabla `festivos`, editable (días cívicos extraordinarios) | 1 |
| Ley 1581/2012 | Finalidad por tipo de campaña, auditoría, minimización, roles, retención, aviso de grabación | 1-2 |
| Ley 1266/2008 (mod. Ley 2157/2021) | La plataforma **no reporta** a centrales; solo gestiona cobro. Campos financieros mínimos y acceso restringido | 1 |

## 8. Plan por fases

Cada fase es entregable y verificable por sí misma.

### Fase 1 — Cimientos sin telefonía (detalle en [`fase-1.md`](fase-1.md))
Esqueleto backend/frontend/docker-compose/PostgreSQL/Alembic; autenticación JWT con roles; usuarios;
CRUD de campañas; importación de clientes desde **CSV** con normalización de teléfonos +57, dedupe y
exclusiones; gestión de exclusiones; motor de cumplimiento **puro** (franjas + festivos) con políticas
versionadas, festivos y endpoint de evaluación; auditoría básica. **No necesita credenciales de Twilio.**
Tests de backend ejecutables **sin Docker** (SQLite en memoria + lógica pura).

### Fase 2 — Consola del agente y llamada manual (preview básico)
- Importación desde **Excel** (`.xlsx`, `openpyxl`).
- Módulo `telefonia`: token de acceso, TwiML App, webhooks de estado y grabación con validación de firma,
  `ProveedorTelefoniaFalso` para tests, tabla `llamadas`/`eventos_llamada`/`grabaciones`.
- Consola del agente: lista de trabajo asignada, ficha del cliente, guion con variables
  (`{{nombre}}`, `{{saldo_mora}}`), botón *Llamar*, colgar, mute, estado del agente (disponible, en llamada,
  tipificando, pausa).
- Tipificaciones: contactado, no contesta, número errado (crea exclusión `numero_errado`), promesa de pago
  (monto, fecha), venta (producto, valor), rechazo, volver a llamar (fecha/hora validada contra franjas).
- Verificación de cumplimiento **en servidor** antes de cada `<Dial>` (franjas + festivos + exclusiones).
- Aviso de grabación al inicio de la llamada (configurable).

### Fase 3 — Marcador automático
- Cola `cola_marcacion` + worker (`python -m app.marcador`) con `SELECT … FOR UPDATE SKIP LOCKED`.
- Modo **preview** (el sistema propone el siguiente registro; el agente confirma) y **progresivo** (1:1,
  el sistema marca al quedar libre el agente; AMD de Twilio).
- Reintentos configurables por campaña y por resultado (no contesta, ocupado, buzón), respetando
  franjas (el próximo intento cae en la siguiente ventana permitida).
- Evaluación de **frecuencia** (Ley 2300) con `intentos_contacto` entre campañas.
- Autorizaciones de horario del titular (si se confirma).
- WebSocket + `LISTEN/NOTIFY` (asignación de llamada al agente, estados en vivo).

### Fase 4 — Supervisión y reportes
- Panel en tiempo real: agentes por estado y tiempo en estado, llamadas activas, progreso por campaña.
- Reportes: contactabilidad (contactos directos / registros gestionados), intentos por registro,
  promesas de pago (monto, fecha) y **cumplimiento** (requiere carga de pagos — ver preguntas abiertas),
  ventas por agente, tiempos medios (AHT, ocupación). Exportación CSV.
- Escucha de grabaciones con control de acceso y auditoría.

### Fase 5 — Posterior al MVP (opcional)
Marcador predictivo (con control de tasa de abandono), escucha/susurro en vivo (conferencias),
multicanal (SMS/WhatsApp) contando frecuencia por canal, integración con webservice del RNE,
retención y borrado automático de datos, SSO.

## 9. Riesgos principales

Ver la sección *Riesgos y preguntas abiertas* de [`fase-1.md`](fase-1.md) (incluye las de fases
posteriores) — en resumen: interpretación jurídica de la frecuencia de la Ley 2300, alcance del RNE para
clientes con relación contractual, caller ID y regulación de Twilio en Colombia, latencia WebRTC,
volumen de importación síncrona y almacenamiento de grabaciones.

## 10. Fuentes normativas consultadas

- Ley 2300 de 2023 — [Función Pública, Gestor Normativo](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=213990),
  [Secretaría del Senado](http://www.secretariasenado.gov.co/senado/basedoc/ley_2300_2023.html).
- RNE — [Resolución CRC 7356 de 2024](https://normograma.mintic.gov.co/docs/pdf/resolucion_crc_7356_2024.pdf),
  conceptos CRC sobre consulta masiva/webservice (crcom.gov.co).
- Festivos 2026 — [calendariodecolombia.com](https://www.calendariodecolombia.com/descarga-calendario/2026/solo-feriados) (contrastado con el cálculo de la Ley 51 de 1983).
- Ley 2157 de 2021 (modifica Ley 1266) — [dmsjuridica](https://www.dmsjuridica.com/buscador_20179478954/legislacion/leyes/2022/10/26/ley-2157-de-2021/?print=pdf).

> Estas referencias son técnicas, no asesoría legal: las reglas son configurables precisamente para que
> el área jurídica del cliente las ajuste sin cambiar código.
