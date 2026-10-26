# Arquitectura — Plataforma omnicanal de campañas outbound (contact center, Colombia)

> Documento vivo del arquitecto. Fuente de verdad para el equipo junto con los ADR de esta carpeta
> y el detalle de cada fase (`fase-1.md` implementada; `fase-2.md` en curso).

## 1. Objetivo

Aplicación web para ejecutar campañas de un contact center en Colombia:

- **Venta / oferta de productos** a clientes.
- **Recuperación de cartera** (cobranza).

Por varios **canales**:

| Canal | Quién atiende | Dirección |
|---|---|---|
| Voz PSTN (Twilio Voice, softphone WebRTC) | Agente humano | Saliente (preview/manual; marcador en fase 3) |
| Llamada de voz por WhatsApp (WhatsApp Business Calling vía Twilio) | Agente humano | Saliente (con permiso del usuario) y entrante |
| Mensajes de WhatsApp (plantillas + conversación) | **Agente IA (Claude) con autonomía total**, supervisado por humanos; traspaso a agente humano | Saliente masivo con plantillas aprobadas y entrante |

Con cumplimiento normativo colombiano incorporado como **configuración** (no como código fijo), aplicado
a **todos los canales**: Ley 2300 de 2023 ("dejen de fregar": franjas, frecuencia, canales autorizados),
Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008 (Habeas Data financiero), Registro de Números Excluidos
(RNE) de la CRC, festivos colombianos (Ley 51 de 1983, "Ley Emiliani") y zona horaria `America/Bogota`;
además de las políticas de WhatsApp Business de Meta (opt-in, plantillas, ventana de 24 h).

Roles: **administrador**, **supervisor**, **agente** (humano). El agente IA no es un usuario: actúa en
nombre de la empresa dentro de los límites de cada campaña y queda auditado como `origen=agente_ia`.

## 2. Vista de componentes

```
                         Navegador (React + TS + Vite)
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ Admin / Supervisor UI            Consola del agente humano                 │
   │ (campañas, bases, reglas, IA,    (ficha, guion, tipificación, softphone    │
   │  supervisión en vivo de chats,    Twilio Voice JS SDK: PSTN y WhatsApp,     │
   │  kill switch, costes)             bandeja de chats traspasados)            │
   └──────┬──────────────────────────────┬─────────────────────┬───────────────┘
          │ HTTPS REST /api/v1           │ WebSocket /api/v1/ws│ WebRTC (voz)
          ▼                              ▼                     ▼
   ┌───────────────────────────────────────────────┐   ┌──────────────────────────┐
   │ API FastAPI (monolito modular)                │◀──│ Twilio                   │
   │ auth · usuarios · campanas · clientes ·       │   │  Voice (PSTN Colombia)   │
   │ importacion · exclusiones · cumplimiento ·    │──▶│  WhatsApp (Messaging +   │
   │ telefonia · consola · tiempo_real ·           │   │  Content API + Business  │
   │ whatsapp · conversaciones · atencion ·        │   │  Calling)                │
   │ agente_ia · supervision · auditoria           │   └──────────────────────────┘
   └──────┬────────────────────────────────────────┘     webhooks firmados
          │ SQLAlchemy 2 / LISTEN-NOTIFY / cola `trabajos`   (X-Twilio-Signature)
          ▼
   ┌──────────────────────┐   ┌────────────────────────────────────┐   ┌─────────────────┐
   │ PostgreSQL 16        │◀─▶│ Worker `python -m app.worker`      │──▶│ API de Claude   │
   │ (datos, cola de      │   │ (mismo código): turnos de IA,      │   │ (Anthropic, SDK │
   │  trabajos, bus de    │   │ envíos de WhatsApp, envíos masivos,│   │  `anthropic`)   │
   │  eventos)            │   │ cierres; marcador en fase 3        │   └─────────────────┘
   └──────────────────────┘   └────────────────────────────────────┘
```

Decisiones clave:

| ADR | Decisión |
|---|---|
| [0001](adr-0001-monolito-modular.md) | Monolito modular FastAPI + SPA React + PostgreSQL; sin microservicios ni broker externo |
| [0002](adr-0002-motor-cumplimiento-configurable.md) | Motor de cumplimiento puro (sin E/S) alimentado por políticas versionadas en BD y tabla de festivos |
| [0003](adr-0003-integracion-twilio.md) | Twilio Voice: softphone WebRTC, TwiML App, webhooks firmados, adaptador `ProveedorTelefonia` con doble falso |
| [0004](adr-0004-tiempo-real-websocket-listen-notify.md) | Tiempo real con WebSocket + `LISTEN/NOTIFY` (adelantado a 2A) |
| [0005](adr-0005-autenticacion-jwt-roles.md) | JWT HS256 de acceso (8 h), rol y estado leídos de BD en cada petición |
| [0006](adr-0006-persistencia-y-tests-sin-docker.md) | SQLAlchemy 2 síncrono + Alembic; tests en SQLite sin Docker |
| [0007](adr-0007-normalizacion-telefonos-e164.md) | Teléfonos normalizados a E.164 con `phonenumbers` |
| [0008](adr-0008-proteccion-datos-personales.md) | Habeas Data: minimización, auditoría, grabación con aviso, exclusiones por finalidad |
| [0009](adr-0009-marcador-preview-progresivo.md) | Marcador preview + progresivo 1:1 con cola en PostgreSQL (fase 3) |
| [0010](adr-0010-proveedor-whatsapp-twilio.md) | **WhatsApp por Twilio** (mensajería + Business Calling) tras la interfaz `ProveedorWhatsApp` con falso |
| [0011](adr-0011-modelo-omnicanal.md) | Modelo omnicanal: `intentos_contacto`, tipificaciones canal-agnósticas, `conversaciones`/`mensajes` |
| [0012](adr-0012-cumplimiento-omnicanal.md) | Cumplimiento en todos los canales: frecuencia evaluada, entrantes, opt-in por canal, opt-out determinista + IA |
| [0013](adr-0013-webhooks-y-cola-de-trabajos.md) | Webhooks firmados e idempotentes; cola `trabajos` en PostgreSQL + worker |
| [0014](adr-0014-agente-ia-arquitectura-claude.md) | Agente IA con la API de Claude: bucle manual, `ClienteLLM` con falso, caché de prompt, costes |
| [0015](adr-0015-agente-ia-autonomia-y-salvaguardas.md) | Autonomía total acotada por el servidor: límites por campaña, herramientas, identidad, injection, transparencia |
| [0016](adr-0016-traspaso-humano-y-supervision.md) | Cola de traspaso a humano, intervención del supervisor, kill switch |
| [0017](adr-0017-consola-agente-y-tipificaciones.md) | Consola del agente: asignación, reserva de registros, estados, tipificación obligatoria |
| [0018](adr-0018-evaluacion-agente-ia.md) | Evaluación del agente IA offline (cliente falso) y online opcional |
| [0019](adr-0019-whatsapp-bandeja-humana.md) | WhatsApp base y bandeja humana (subfase 2B) |

## 3. Módulos del backend

Todos bajo `backend/app/modulos/<modulo>/` con la misma forma: `modelos.py` (SQLAlchemy),
`esquemas.py` (Pydantic), `servicio.py` (lógica), `router.py` (FastAPI). La lógica pura (sin BD ni
red) vive en archivos propios y se prueba aislada. Adaptadores a terceros en `backend/app/integraciones/`.

| Módulo | Responsabilidad | Fase |
|---|---|---|
| `auth`, `usuarios` | Login, JWT, usuarios y roles | 1 |
| `campanas` | Campañas; asignación de agentes (2A); configuración de IA y ofertas (2C) | 1-2C |
| `clientes` | Cliente global, teléfonos, cliente↔campaña | 1 |
| `importacion` | CSV (1) y Excel `.xlsx` (2A); columna de autorización WhatsApp (2B) | 1-2B |
| `exclusiones` | Exclusiones por finalidad y, desde 2B, por canal | 1-2B |
| `cumplimiento` | Políticas, festivos, motor puro: franjas, festivos y **frecuencia omnicanal** (2A) | 1-2A |
| `auditoria` | Registro de acciones sensibles | 1 |
| `telefonia` | Adaptador Twilio Voice, token, TwiML, webhooks, llamadas; llamadas WhatsApp (2E) | 2A-2E |
| `consola` | Estado del agente, lista de trabajo, ficha, tipificaciones, promesas, ventas | 2A |
| `tiempo_real` | WebSocket y bus de eventos | 2A |
| `whatsapp` | Adaptador `ProveedorWhatsApp`, webhooks, plantillas, autorizaciones, envíos masivos (2D) | 2B-2D |
| `conversaciones` | Conversaciones, mensajes, ventana 24 h, bandeja humana | 2B |
| `trabajos` | Cola de trabajos y worker | 2B |
| `atencion` | Cola de traspaso a humano | 2B-2C |
| `agente_ia` | Bucle con Claude, herramientas, límites, guardas, costes, evaluación | 2C |
| `supervision` | Panel de agentes (2A), conversaciones IA (2C), KPIs (4) | 2A-4 |
| `marcador` | Cola de marcación, preview/progresivo, reintentos | 3 |
| `reportes` | KPIs, exportaciones | 4 |

## 4. Modelo de datos principal

```
usuarios ─┬─< campana_agentes >─ campanas ─┬─< campana_clientes >─ clientes ─< telefonos
          │                                │        │
          ├─ estados_agente / historial    │        ├─< tipificaciones ─┬─ promesas_pago ─< promesa_cuotas (2C)
          │                                │        │   (canal, origen) └─ ventas
          │                                │        ├─< llamadas ─< eventos_llamada ; grabaciones
          │                                │        └─< conversaciones (2B) ─< mensajes ─< eventos_mensaje
          │                                │                 ├─< historial_ia, acciones_ia, uso_ia (2C)
          │                                │                 └─< cola_atencion
          │                                ├─ configuracion_ia_campana (2C) ; ofertas_campana (2C)
          │                                └─< envios_masivos ─< envio_destinatarios (2D)
          └─ auditoria
intentos_contacto (cliente_id, canal, iniciado_por, momento, contacto_directo, tipo_campana)   ← frecuencia
exclusiones (numero_e164, motivo, aplica_a, canal)    autorizaciones_canal (numero_e164, canal, finalidad)
politicas_cumplimiento (tipo, versión, JSON)          festivos       plantillas_whatsapp      trabajos
```

Puntos clave:

- **`clientes` es global**: los límites de frecuencia de la Ley 2300 son por consumidor y se cuentan
  **entre campañas y entre canales** (ADR-0012).
- **`intentos_contacto`** es el historial común que alimenta la frecuencia; **`tipificaciones`** es el
  resultado común de humanos e IA (ADR-0011).
- El **agente IA** solo actúa mediante herramientas del backend sobre el cliente fijado por la
  conversación; sus límites de negocio son configuración por campaña (ADR-0015).
- Exclusiones, autorizaciones de canal y cumplimiento se evalúan **en el momento del contacto** (fuente
  de verdad) en el servidor.
- Fechas/horas en **UTC** (`timestamptz`); se evalúan y presentan en `America/Bogota`. Montos en COP como
  `NUMERIC(14,2)`; costes de IA en USD `NUMERIC(12,6)`.

## 5. Tiempo real

WebSocket `GET /api/v1/ws?token=<jwt>` **desde 2A**. Eventos tipados: `agente.estado`,
`llamada.estado`, `consola.registro` (2A); `conversacion.mensaje`, `conversacion.estado`,
`atencion.cola` (2B); `ia.alerta` (2C); `marcador.asignacion`, `campana.metricas` (3-4). API y worker
publican con `NOTIFY eventos`; cada instancia de la API escucha y reenvía según rol. Ver ADR-0004 y
ADR-0017.

## 6. Integraciones

**Twilio Voice** (ADR-0003, 2A): softphone `@twilio/voice-sdk` 2.x; el navegador nunca envía el número;
el TwiML saliente valida firma, agente, reserva, cumplimiento (franjas, festivos, frecuencia),
exclusiones y responde `<Dial>`; aviso de grabación en la pierna del cliente; webhooks idempotentes.

**WhatsApp vía Twilio** (ADR-0010, 2B-2E): envío de plantillas (Content API) y texto libre en ventana de
24 h; webhooks de entrantes y estados firmados; llamadas WhatsApp con `<Dial><WhatsApp>` y entrantes
puenteadas al softphone. Todo tras `ProveedorWhatsApp` con `ProveedorWhatsAppFalso`.

**Claude** (ADR-0014, 2C): SDK oficial `anthropic`, modelo configurable (por defecto
`claude-opus-5-5`, esfuerzo `medium`), bucle manual con herramientas `strict`, caché de prompt con
prefijo estable, registro de `usage` y coste. Tras `ClienteLLM` con `ClienteLLMFalso`.

## 7. Cumplimiento normativo como configuración

| Norma | Cómo se modela | Fase |
|---|---|---|
| Ley 2300/2023 art. 3 — franjas y festivos (también mensajería por aplicaciones) | `politicas_cumplimiento.configuracion.franjas` + `permitir_festivos`; aplicado a voz, plantillas y llamadas WhatsApp | 1 / 2A-2E |
| Ley 2300/2023 art. 3 — frecuencia tras contacto directo (día y canales/semana) | `configuracion.frecuencia` evaluada con `intentos_contacto` entre campañas y canales | 2A |
| Ley 2300/2023 art. 2 — solo canales autorizados | `autorizaciones_canal` (opt-in WhatsApp) exigida para contactos iniciados por la empresa | 2B |
| Respuestas a contactos iniciados por el cliente | `configuracion.entrantes` (supuestos S-E1/S-E2, ADR-0012) | 2B-2C |
| Ley 2300/2023 — autorización de otros horarios por el consumidor | `autorizaciones_horario` (pendiente de confirmar alcance) | 3 |
| RNE (CRC) | `exclusiones` `motivo=rne`, `aplica_a=venta`, `canal=todos` (cubre WhatsApp) | 1-2B |
| Opt-out | Determinista + herramienta IA → `exclusiones` por canal | 2B-2C |
| Festivos (Ley 51/1983) | Cálculo puro que siembra `festivos`, editable | 1 |
| Ley 1581/2012 | Finalidad, auditoría (incl. cada acción de la IA), minimización, verificación de identidad antes de revelar deuda, retención de transcripciones, transmisión internacional al proveedor de IA | 1-2F |
| Ley 1266/2008 | La plataforma **no reporta** a centrales; datos financieros solo tras verificar identidad | 1-2C |
| Políticas de Meta | Plantillas aprobadas, ventana 24 h, opt-in/opt-out, asistente de IA de la propia empresa (no de propósito general) | 2B-2D |

## 8. Plan por fases

Cada fase y subfase es entregable y verificable por sí misma **sin credenciales reales** (proveedores
falsos de telefonía y WhatsApp y cliente de Claude falso).

### Fase 1 — Cimientos sin telefonía — **implementada** ([`fase-1.md`](fase-1.md))
Auth/roles, usuarios, campañas, importación CSV, exclusiones, motor de cumplimiento (franjas + festivos),
auditoría.

### Fase 2 — Omnicanal: voz, WhatsApp y agente IA (detalle en [`fase-2.md`](fase-2.md))

| Subfase | Contenido | Depende de |
|---|---|---|
| **2A** Consola del agente y voz | Asignación agente↔campaña, reserva de registros, estado del agente, softphone Twilio (y falso), TwiML/webhooks de voz, aviso de grabación, tipificaciones (promesa, venta, volver a llamar, número errado), `intentos_contacto` + **frecuencia evaluada**, WebSocket, panel mínimo de agentes, importación Excel | Fase 1 |
| **2B** WhatsApp base y bandeja humana | `ProveedorWhatsApp` (Twilio + falso), webhooks firmados, cola `trabajos` + worker, conversaciones/mensajes, ventana 24 h, plantillas (sincronización y registro), opt-in (`autorizaciones_canal`, importación) y opt-out determinista, exclusiones por canal, bandeja de chat para agentes humanos, envío individual de plantilla | 2A |
| **2C** Agente IA en WhatsApp | `ClienteLLM` (Anthropic + falso), bucle manual, herramientas con límites por campaña, verificación de identidad, guardas, traspaso a humano, intervención y kill switch, presupuesto y costes, panel de supervisión de IA, evaluación offline (+ online opcional) | 2B |
| **2D** Campañas outbound de WhatsApp | Envíos masivos de plantillas con worker y ritmo configurable, cumplimiento por destinatario al enviar (franja, frecuencia, opt-in, exclusiones), métricas de entrega/lectura/respuesta, respuestas atendidas por la IA | 2C (o 2B si se lanza sin IA) |
| **2E** Llamadas de voz por WhatsApp | Permiso de llamada (solicitud, estado, caducidad), `<Dial><WhatsApp>` desde el softphone, llamadas entrantes de WhatsApp a agentes humanos, tipificación | 2A, 2B |
| **2F** Operación y endurecimiento | Retención/anonimización de transcripciones, evaluación online programada y umbral de activación, reportes de IA y costes, alertas, seguridad pendiente (límite de login, refresh/cookies httpOnly, CSP), pruebas de carga | 2C-2E |

### Fase 3 — Marcador automático
Cola `cola_marcacion` + worker (reutiliza la infraestructura de `trabajos`), modos preview y progresivo
1:1 con AMD, reintentos por resultado respetando franjas y frecuencia, autorizaciones de horario del
titular.

### Fase 4 — Supervisión y reportes
Panel en tiempo real completo (agentes, llamadas, conversaciones, progreso por campaña); reportes de
contactabilidad, promesas y su **cumplimiento** (requiere carga de pagos), ventas por agente humano e IA,
AHT/ocupación, coste por gestión y canal; escucha de grabaciones con auditoría; exportación CSV.

### Fase 5 — Posterior (opcional)
Marcador predictivo con control de abandono, escucha/susurro en vivo (conferencias), webservice del RNE,
SSO, proveedor de WhatsApp directo con Meta si el coste lo justifica, voz con IA (agente IA en llamadas).

## 9. Riesgos principales

Ver `fase-2.md` §8 (y `fase-1.md` §7). En resumen: interpretación jurídica de la frecuencia y de las
respuestas a entrantes (S-E1/S-E2), autonomía total de la IA (errores de negociación, injection,
reputación) mitigada por límites en servidor y supervisión, transmisión internacional de datos al
proveedor de IA, clasificación de plantillas de cobranza por Meta (utility vs. marketing) y su coste,
requisitos de Meta para llamadas WhatsApp (verificación y límite de mensajería), caller ID y regulación
de Twilio en Colombia, coste de la IA por conversación.

## 10. Fuentes consultadas

- Ley 2300 de 2023 — [Función Pública](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=213990),
  [Secretaría del Senado](http://www.secretariasenado.gov.co/senado/basedoc/ley_2300_2023.html),
  [normograma MinTIC](https://normograma.mintic.gov.co/docs/pdf/ley_2300_2023.pdf).
- RNE — [Resolución CRC 7356 de 2024](https://normograma.mintic.gov.co/docs/pdf/resolucion_crc_7356_2024.pdf).
- Festivos 2026 — [calendariodecolombia.com](https://www.calendariodecolombia.com/descarga-calendario/2026/solo-feriados).
- Ley 2157 de 2021 (modifica Ley 1266) — [dmsjuridica](https://www.dmsjuridica.com/buscador_20179478954/legislacion/leyes/2022/10/26/ley-2157-de-2021/?print=pdf).
- WhatsApp/Twilio/Meta — ver fuentes de [ADR-0010](adr-0010-proveedor-whatsapp-twilio.md).

> Estas referencias son técnicas, no asesoría legal: las reglas son configurables precisamente para que
> el área jurídica del cliente las ajuste sin cambiar código.
