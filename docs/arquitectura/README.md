# Arquitectura — Plataforma omnicanal de campañas outbound (contact center, Colombia)

> Documento vivo del arquitecto. Fuente de verdad para el equipo junto con los ADR de esta carpeta
> y el detalle de cada fase (`fase-1.md` implementada; `fase-2.md` en curso).
>
> **Revisión de alcance 2026-10-28 — IA en voz.** Las llamadas de voz (salientes de campañas,
> entrantes y llamadas de WhatsApp) también las atiende un agente de IA con Claude, con la misma
> autonomía que en chat y traspaso a agentes humanos de respaldo de la consola de 2A (confirmado por
> el usuario). Ver ADR-0020 (voz con IA), ADR-0021 (marcador IA) y el plan revisado en §8.

## 1. Objetivo

Aplicación web para ejecutar campañas de un contact center en Colombia:

- **Venta / oferta de productos** a clientes.
- **Recuperación de cartera** (cobranza).

Por varios **canales**:

| Canal | Quién atiende | Dirección |
|---|---|---|
| Voz PSTN (Twilio Voice) | **Agente IA (Claude) con autonomía total** vía Twilio ConversationRelay; traspaso en vivo a un agente humano de la consola (softphone WebRTC) o devolución de llamada. Campañas en modo humano siguen disponibles (preview/manual de 2A) | Saliente con **marcador automático IA** y entrante |
| Llamada de voz por WhatsApp (WhatsApp Business Calling vía Twilio) | **Agente IA** (si ConversationRelay lo admite, a verificar en 2F; si no, agente humano), con traspaso a humano | Saliente (con permiso del usuario) y entrante |
| Mensajes de WhatsApp (plantillas + conversación) | **Agente IA (Claude) con autonomía total**, supervisado por humanos; traspaso a agente humano | Saliente masivo con plantillas aprobadas y entrante |

Con cumplimiento normativo colombiano incorporado como **configuración** (no como código fijo), aplicado
a **todos los canales**: Ley 2300 de 2023 ("dejen de fregar": franjas, frecuencia, canales autorizados),
Ley 1581 de 2012 (Habeas Data), Ley 1266 de 2008 (Habeas Data financiero), Registro de Números Excluidos
(RNE) de la CRC, festivos colombianos (Ley 51 de 1983, "Ley Emiliani") y zona horaria `America/Bogota`;
además de las políticas de WhatsApp Business de Meta (opt-in, plantillas, ventana de 24 h).

Roles: **administrador**, **supervisor**, **agente** (humano). El agente IA no es un usuario: actúa en
nombre de la empresa dentro de los límites de cada campaña y queda auditado como `origen=agente_ia`.
Los agentes humanos son el **respaldo** de la IA en chat y en voz (traspasos, devoluciones de llamada)
y pueden seguir operando campañas en modo humano.

## 2. Vista de componentes

```
                         Navegador (React + TS + Vite)
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ Admin / Supervisor UI            Consola del agente humano                 │
   │ (campañas, bases, reglas, IA,    (ficha, guion, tipificación, softphone    │
   │  marcador, supervisión en vivo    Twilio Voice JS SDK: salientes y         │
   │  de chats y llamadas IA,          traspasos entrantes de la IA, bandeja    │
   │  kill switch, costes)             de chats, devoluciones de llamada)       │
   └──────┬──────────────────────────────┬─────────────────────┬───────────────┘
          │ HTTPS REST /api/v1           │ WebSocket /api/v1/ws│ WebRTC (voz)
          ▼                              ▼                     ▼
   ┌───────────────────────────────────────────────┐   ┌──────────────────────────┐
   │ API FastAPI (monolito modular)                │◀──│ Twilio                   │
   │ auth · usuarios · campanas · clientes ·       │   │  Voice (PSTN Colombia)   │
   │ importacion · exclusiones · cumplimiento ·    │──▶│  ConversationRelay       │
   │ telefonia · consola · tiempo_real ·           │   │   (STT/TTS gestionado)   │
   │ whatsapp · conversaciones · atencion ·        │   │  WhatsApp (Messaging +   │
   │ agente_ia · voz_ia · marcador · supervision · │   │  Content API + Business  │
   │ auditoria                                     │   │  Calling)                │
   └──────┬────────────────────────────────────────┘   └───────────┬──────────────┘
          │ SQLAlchemy 2 / LISTEN-NOTIFY / cola `trabajos`          │ WebSocket de texto
          ▼                                                         ▼ (wss, por llamada)
   ┌──────────────────────┐   ┌──────────────────────────────┐   ┌───────────────────────────┐
   │ PostgreSQL 16        │◀─▶│ Worker `python -m app.worker`│   │ Servicio `voz-ia`          │
   │ (datos, cola de      │   │ turnos de IA de chat, envíos │   │ (`app.voz_ia:app`, mismo   │
   │  trabajos, bus de    │◀─▶│ de WhatsApp, envíos masivos, │   │  código): sesiones de voz  │
   │  eventos)            │   │ tick del marcador IA, cierres│   │  IA en streaming           │
   └──────────────────────┘   └──────────────┬───────────────┘   └─────────────┬─────────────┘
              ▲                               └──────────────┬──────────────────┘
              └──────────────────────────────────────────────┤
                                                             ▼
                                                  ┌─────────────────────┐
                                                  │ API de Claude       │
                                                  │ (Anthropic, SDK     │
                                                  │  `anthropic`)       │
                                                  └─────────────────────┘
```

Decisiones clave:

| ADR | Decisión |
|---|---|
| [0001](adr-0001-monolito-modular.md) | Monolito modular FastAPI + SPA React + PostgreSQL; sin microservicios ni broker externo |
| [0002](adr-0002-motor-cumplimiento-configurable.md) | Motor de cumplimiento puro (sin E/S) alimentado por políticas versionadas en BD y tabla de festivos |
| [0003](adr-0003-integracion-twilio.md) | Twilio Voice: softphone WebRTC, TwiML App, webhooks firmados, adaptador `ProveedorTelefonia` con doble falso; creación REST de llamadas desde 2D |
| [0004](adr-0004-tiempo-real-websocket-listen-notify.md) | Tiempo real con WebSocket + `LISTEN/NOTIFY` (adelantado a 2A) |
| [0005](adr-0005-autenticacion-jwt-roles.md) | JWT HS256 de acceso (8 h), rol y estado leídos de BD en cada petición |
| [0006](adr-0006-persistencia-y-tests-sin-docker.md) | SQLAlchemy 2 síncrono + Alembic; tests en SQLite sin Docker |
| [0007](adr-0007-normalizacion-telefonos-e164.md) | Teléfonos normalizados a E.164 con `phonenumbers` |
| [0008](adr-0008-proteccion-datos-personales.md) | Habeas Data: minimización, auditoría, grabación con aviso, exclusiones por finalidad |
| [0009](adr-0009-marcador-preview-progresivo.md) | Marcador preview + progresivo 1:1 para campañas **humanas** (Fase 3, opcional; modificado por 0021) |
| [0010](adr-0010-proveedor-whatsapp-twilio.md) | **WhatsApp por Twilio** (mensajería + Business Calling) tras la interfaz `ProveedorWhatsApp` con falso |
| [0011](adr-0011-modelo-omnicanal.md) | Modelo omnicanal: `intentos_contacto`, tipificaciones canal-agnósticas, `conversaciones`/`mensajes` |
| [0012](adr-0012-cumplimiento-omnicanal.md) | Cumplimiento en todos los canales: frecuencia evaluada, entrantes, opt-in por canal, opt-out determinista + IA |
| [0013](adr-0013-webhooks-y-cola-de-trabajos.md) | Webhooks firmados e idempotentes; cola `trabajos` en PostgreSQL + worker |
| [0014](adr-0014-agente-ia-arquitectura-claude.md) | Agente IA con la API de Claude: bucle manual, núcleo canal-agnóstico (chat y voz), `ClienteLLM` con falso (y stream), caché de prompt, costes, modelo por canal |
| [0015](adr-0015-agente-ia-autonomia-y-salvaguardas.md) | Autonomía total acotada por el servidor en chat y voz: límites por campaña, herramientas, identidad, injection, transparencia |
| [0016](adr-0016-traspaso-humano-y-supervision.md) | Cola de traspaso a humano (chat) y transferencia en vivo de llamadas IA con espera y devolución; intervención; kill switch |
| [0017](adr-0017-consola-agente-y-tipificaciones.md) | Consola del agente: asignación, reserva de registros, estados, tipificación obligatoria |
| [0018](adr-0018-evaluacion-agente-ia.md) | Evaluación del agente IA offline (cliente falso) y online opcional |
| [0019](adr-0019-whatsapp-bandeja-humana.md) | WhatsApp base y bandeja humana (subfase 2B) |
| [0020](adr-0020-agente-ia-voz-conversationrelay.md) | **Agente IA de voz** con Twilio ConversationRelay + Claude en streaming: servicio `voz-ia`, turnos, interrupciones, AMD, aviso, identidad por DTMF, traspaso, tipificación automática, latencia y coste por minuto |
| [0021](adr-0021-marcador-automatico-voz-ia.md) | **Marcador automático IA**: concurrencia por campaña y global, ritmo, reintentos, cumplimiento y bloqueos de 2A, kill switch |

## 3. Módulos del backend

Todos bajo `backend/app/modulos/<modulo>/` con la misma forma: `modelos.py` (SQLAlchemy),
`esquemas.py` (Pydantic), `servicio.py` (lógica), `router.py` (FastAPI). La lógica pura (sin BD ni
red) vive en archivos propios y se prueba aislada. Adaptadores a terceros en `backend/app/integraciones/`.

| Módulo | Responsabilidad | Fase |
|---|---|---|
| `auth`, `usuarios` | Login, JWT, usuarios y roles | 1 |
| `campanas` | Campañas; asignación de agentes (2A); configuración de IA y ofertas (2C); modo de voz y configuración de voz IA (2D) | 1-2D |
| `clientes` | Cliente global, teléfonos, cliente↔campaña | 1 |
| `importacion` | CSV (1) y Excel `.xlsx` (2A); columna de autorización WhatsApp (2B) | 1-2B |
| `exclusiones` | Exclusiones por finalidad y, desde 2B, por canal | 1-2B |
| `cumplimiento` | Políticas, festivos, motor puro: franjas, festivos y **frecuencia omnicanal** (2A) | 1-2A |
| `auditoria` | Registro de acciones sensibles | 1 |
| `telefonia` | Adaptador Twilio Voice, token, TwiML, webhooks, llamadas; creación REST, AMD, TwiML de IA, entrantes PSTN y traspasos (2D); llamadas WhatsApp (2F) | 2A-2F |
| `consola` | Estado del agente, lista de trabajo, ficha, tipificaciones, promesas, ventas; recepción de traspasos y devoluciones (2D) | 2A-2D |
| `tiempo_real` | WebSocket y bus de eventos | 2A |
| `whatsapp` | Adaptador `ProveedorWhatsApp`, webhooks, plantillas, autorizaciones, envíos masivos (2E) | 2B-2E |
| `conversaciones` | Conversaciones, mensajes, ventana 24 h, bandeja humana | 2B |
| `trabajos` | Cola de trabajos y worker | 2B |
| `atencion` | Cola de traspaso a humano (chat) | 2B-2C |
| `agente_ia` | Núcleo canal-agnóstico: bucle con Claude, herramientas, límites, guardas, costes, evaluación | 2C-2D |
| `voz_ia` | Servicio de sesiones de voz (WebSocket de ConversationRelay), turno en streaming, transcripción, traspasos de voz | 2D |
| `marcador` | Marcador automático IA (2D); preview/progresivo para humanos (Fase 3, opcional) | 2D-3 |
| `supervision` | Panel de agentes (2A), conversaciones IA (2C), llamadas IA y marcador (2D), KPIs (4) | 2A-4 |
| `reportes` | KPIs, exportaciones | 4 |

## 4. Modelo de datos principal

```
usuarios ─┬─< campana_agentes >─ campanas ─┬─< campana_clientes >─ clientes ─< telefonos
          │                                │        │
          ├─ estados_agente / historial    │        ├─< tipificaciones ─┬─ promesas_pago ─< promesa_cuotas (2C)
          │                                │        │   (canal, origen) └─ ventas
          │                                │        ├─< llamadas ─< eventos_llamada ; grabaciones
          │                                │        │      ├─ llamadas_ia (2D) ─< transcripciones_llamada
          │                                │        │      └─< traspasos_llamada (2D)
          │                                │        └─< conversaciones (2B) ─< mensajes ─< eventos_mensaje
          │                                │                 └─< cola_atencion
          │                                ├─ configuracion_ia_campana (2C; + voz 2D) ; ofertas_campana (2C)
          │                                └─< envios_masivos ─< envio_destinatarios (2E)
          └─ auditoria
historial_ia, acciones_ia, uso_ia, instrucciones_supervisor (2C)  → conversación O llamada (CHECK exactamente uno)
intentos_contacto (cliente_id, canal, iniciado_por, momento, contacto_directo, tipo_campana)   ← frecuencia
exclusiones (numero_e164, motivo, aplica_a, canal)    autorizaciones_canal (numero_e164, canal, finalidad)
politicas_cumplimiento (tipo, versión, JSON)          festivos       plantillas_whatsapp      trabajos
configuracion_global (ia_activa, voz_max_concurrentes, cerrojo del marcador)
```

Puntos clave:

- **`clientes` es global**: los límites de frecuencia de la Ley 2300 son por consumidor y se cuentan
  **entre campañas y entre canales** (ADR-0012).
- **`intentos_contacto`** es el historial común que alimenta la frecuencia; **`tipificaciones`** es el
  resultado común de humanos e IA (ADR-0011), también en voz (tipificación automática, ADR-0020 §10).
- El **agente IA** solo actúa mediante herramientas del backend sobre el cliente fijado por la
  conversación o la llamada; sus límites de negocio son configuración por campaña (ADR-0015).
- Exclusiones, autorizaciones de canal y cumplimiento se evalúan **en el momento del contacto** (fuente
  de verdad) en el servidor; el marcador IA usa los mismos bloqueos que el TwiML saliente de 2A.
- Fechas/horas en **UTC** (`timestamptz`); se evalúan y presentan en `America/Bogota`. Montos en COP como
  `NUMERIC(14,2)`; costes de IA y voz en USD `NUMERIC(12,6)`.

## 5. Tiempo real

WebSocket `GET /api/v1/ws?ticket=<ticket>` **desde 2A**. Eventos tipados: `agente.estado`,
`llamada.estado`, `consola.registro` (2A); `conversacion.mensaje`, `conversacion.estado`,
`atencion.cola` (2B); `ia.alerta` (2C); `llamada_ia.estado`, `llamada_ia.turno`,
`traspaso_voz.estado`, `marcador.estado` (2D); `campana.metricas` (2E-4). API, worker y servicio
`voz-ia` publican con `NOTIFY eventos`; cada instancia de la API escucha y reenvía según rol. Solo ids
y catálogos, nunca texto. Ver ADR-0004 y ADR-0017.

## 6. Integraciones

**Twilio Voice** (ADR-0003, 2A): softphone `@twilio/voice-sdk` 2.x; el navegador nunca envía el número;
el TwiML saliente valida firma, agente, reserva, cumplimiento (franjas, festivos, frecuencia),
exclusiones y responde `<Dial>`; aviso de grabación en la pierna del cliente; webhooks idempotentes.
Desde 2D: creación REST de llamadas con AMD asíncrono, `incoming_allow=True` para recibir traspasos.

**Twilio ConversationRelay** (ADR-0020, 2D): STT/TTS gestionados por Twilio; nuestro servicio `voz-ia`
recibe transcripciones y envía texto en streaming por WebSocket; `end` + `handoffData` para traspasos;
reconexión por la URL `action`. Tras un adaptador con doble falso (relay simulado en tests).

**WhatsApp vía Twilio** (ADR-0010, 2B-2F): envío de plantillas (Content API) y texto libre en ventana de
24 h; webhooks de entrantes y estados firmados; llamadas WhatsApp atendidas por la IA (o por humanos si
ConversationRelay no las admite). Todo tras `ProveedorWhatsApp` con `ProveedorWhatsAppFalso`.

**Claude** (ADR-0014, 2C-2D): SDK oficial `anthropic`, modelo configurable por campaña **y canal** (chat
por defecto `claude-opus-5-5` esfuerzo `medium`; voz por defecto `claude-sonnet-5-5` esfuerzo `low`),
bucle manual con herramientas `strict`, streaming en voz, caché de prompt con prefijo estable por canal,
registro de `usage`, latencia y coste. Tras `ClienteLLM` con `ClienteLLMFalso`.

## 7. Cumplimiento normativo como configuración

| Norma | Cómo se modela | Fase |
|---|---|---|
| Ley 2300/2023 art. 3 — franjas y festivos (también mensajería por aplicaciones) | `politicas_cumplimiento.configuracion.franjas` + `permitir_festivos`; aplicado a voz (humana e IA, marcador incluido), plantillas y llamadas WhatsApp | 1 / 2A-2F |
| Ley 2300/2023 art. 3 — frecuencia tras contacto directo (día y canales/semana) | `configuracion.frecuencia` evaluada con `intentos_contacto` entre campañas y canales, en el momento de marcar | 2A |
| Ley 2300/2023 art. 2 — solo canales autorizados | `autorizaciones_canal` (opt-in WhatsApp) exigida para contactos iniciados por la empresa | 2B |
| Respuestas a contactos iniciados por el cliente | `configuracion.entrantes` (supuestos S-E1/S-E2, ADR-0012); entrantes PSTN atendidas por la IA | 2B-2D |
| Ley 2300/2023 — autorización de otros horarios por el consumidor | `autorizaciones_horario` (pendiente de confirmar alcance) | 3 |
| RNE (CRC) | `exclusiones` `motivo=rne`, `aplica_a=venta`, `canal=todos` (cubre WhatsApp y voz IA) | 1-2B |
| Opt-out | Determinista + herramienta IA → `exclusiones` por canal (chat y voz: "no me llamen") | 2B-2D |
| Transparencia: asistente virtual y grabación | Aviso determinista al inicio de cada chat y de cada llamada IA (`IA_AVISO_ASISTENTE`, `VOZ_IA_AVISO`) | 2C-2D |
| Festivos (Ley 51/1983) | Cálculo puro que siembra `festivos`, editable | 1 |
| Ley 1581/2012 | Finalidad, auditoría (incl. cada acción de la IA), minimización, verificación de identidad antes de revelar deuda (DTMF en voz), retención de transcripciones y grabaciones, transmisión internacional a Anthropic, Twilio y sus proveedores de STT/TTS | 1-2G |
| Ley 1266/2008 | La plataforma **no reporta** a centrales; datos financieros solo tras verificar identidad | 1-2D |
| Políticas de Meta | Plantillas aprobadas, ventana 24 h, opt-in/opt-out, asistente de IA de la propia empresa (no de propósito general), permiso de llamada | 2B-2F |

## 8. Plan por fases

Cada fase y subfase es entregable y verificable por sí misma **sin credenciales reales** (proveedores
falsos de telefonía y WhatsApp, ConversationRelay simulado y cliente de Claude falso).

### Fase 1 — Cimientos sin telefonía — **implementada** ([`fase-1.md`](fase-1.md))
Auth/roles, usuarios, campañas, importación CSV, exclusiones, motor de cumplimiento (franjas + festivos),
auditoría.

### Fase 2 — Omnicanal: voz y WhatsApp atendidos por IA (detalle en [`fase-2.md`](fase-2.md))

Plan revisado el 2026-10-28 (IA en voz). Las subfases anteriores 2D (masivos WhatsApp), 2E (llamadas
WhatsApp) y 2F (operación) pasan a 2E, 2F y 2G.

| Subfase | Contenido | Depende de |
|---|---|---|
| **2A** Consola del agente y voz — **implementada** | Asignación agente↔campaña, reserva de registros, estado del agente, softphone Twilio (y falso), TwiML/webhooks de voz, aviso de grabación, tipificaciones, `intentos_contacto` + **frecuencia evaluada**, WebSocket, panel mínimo de agentes, importación Excel | Fase 1 |
| **2B** WhatsApp base y bandeja humana — *en curso* | `ProveedorWhatsApp` (Twilio + falso), webhooks firmados, cola `trabajos` + worker, conversaciones/mensajes, ventana 24 h, plantillas, opt-in/opt-out, exclusiones por canal, bandeja humana, plantilla individual | 2A |
| **2C** Núcleo del agente IA + chat de WhatsApp | Núcleo **canal-agnóstico** (contexto fijado por servidor, herramientas con límites, guardas, costes, auditoría, tablas de IA referidas a conversación o llamada), `ClienteLLM` (Anthropic + falso), adaptador de chat, verificación de identidad, traspaso a humano, intervención y kill switch, presupuesto, panel de supervisión de IA, evaluación offline (+ online opcional) | 2B |
| **2D** Agente IA de voz telefónica + marcador IA | Servicio `voz-ia` (ConversationRelay), turno en streaming, interrupciones/silencios, AMD, aviso legal, identidad por DTMF, opt-out por voz, constancia del acuerdo, transferencia a la consola 2A con espera y devolución, transcripción, tipificación automática, entrantes PSTN; marcador con concurrencia, ritmo, reintentos y kill switch; supervisión de llamadas IA; evaluación de voz | 2C (y 2A) |
| **2E** Campañas masivas de WhatsApp | Envíos masivos de plantillas con ritmo, cumplimiento por destinatario, métricas, respuestas atendidas por la IA; plantilla de constancia de acuerdos de voz | 2C |
| **2F** Llamadas de WhatsApp atendidas por IA | Verificación inicial de ConversationRelay sobre WhatsApp Calling; permiso de llamada; salientes por el marcador IA y entrantes a la IA; alternativa con humanos si no es viable | 2D, 2E |
| **2G** Operación y endurecimiento | Retención/anonimización de transcripciones y grabaciones, evaluación online programada y umbral de activación (chat y voz), reportes de IA, costes por canal y latencia, alertas, seguridad pendiente, pruebas de carga del worker, del WebSocket y de sesiones de voz | 2C-2F |

### Fase 3 — Marcador para campañas humanas (opcional)
Preview y progresivo 1:1 con AMD para campañas en `voz_modo=humano` (ADR-0009), reutilizando la
creación REST, el AMD y los reintentos del marcador IA de 2D; autorizaciones de horario del titular.

### Fase 4 — Supervisión y reportes
Panel en tiempo real completo (agentes, llamadas, conversaciones, progreso por campaña); reportes de
contactabilidad, promesas y su **cumplimiento** (requiere carga de pagos), ventas por agente humano e IA
y por canal, AHT/ocupación, coste por gestión y canal; escucha de grabaciones con auditoría; exportación
CSV.

### Fase 5 — Posterior (opcional)
Marcador predictivo para humanos con control de abandono, escucha/susurro en vivo de llamadas IA y
humanas (conferencias), voz con STT/TTS propios (Media Streams) si el coste de ConversationRelay lo
justifica, webservice del RNE, SSO, proveedor de WhatsApp directo con Meta si el coste lo justifica.

## 9. Riesgos principales

Ver `fase-2.md` §8 (y `fase-1.md` §7). En resumen: interpretación jurídica de la frecuencia y de las
respuestas a entrantes (S-E1/S-E2), **llamadas automatizadas con IA** frente a la Ley 2300 y la SIC,
validez de acuerdos verbales cerrados por la IA y su constancia, autonomía total de la IA (errores de
negociación, injection, reputación) mitigada por límites en servidor y supervisión, transmisión
internacional de datos (Anthropic, Twilio y sus proveedores de STT/TTS), **latencia y calidad del
español colombiano** en voz, precisión del AMD, coste por minuto (~US$0,13 con Sonnet) y concurrencia,
disponibilidad de humanos de respaldo, clasificación de plantillas de cobranza por Meta, requisitos de
Meta para llamadas WhatsApp y si ConversationRelay las admite, caller ID y regulación de Twilio en
Colombia.

## 10. Fuentes consultadas

- Ley 2300 de 2023 — [Función Pública](https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=213990),
  [Secretaría del Senado](http://www.secretariasenado.gov.co/senado/basedoc/ley_2300_2023.html),
  [normograma MinTIC](https://normograma.mintic.gov.co/docs/pdf/ley_2300_2023.pdf).
- RNE — [Resolución CRC 7356 de 2024](https://normograma.mintic.gov.co/docs/pdf/resolucion_crc_7356_2024.pdf).
- Festivos 2026 — [calendariodecolombia.com](https://www.calendariodecolombia.com/descarga-calendario/2026/solo-feriados).
- Ley 2157 de 2021 (modifica Ley 1266) — [dmsjuridica](https://www.dmsjuridica.com/buscador_20179478954/legislacion/leyes/2022/10/26/ley-2157-de-2021/?print=pdf).
- WhatsApp/Twilio/Meta — ver fuentes de [ADR-0010](adr-0010-proveedor-whatsapp-twilio.md).
- Voz con IA (ConversationRelay, AMD, precios, latencia) — ver fuentes de [ADR-0020](adr-0020-agente-ia-voz-conversationrelay.md).

> Estas referencias son técnicas, no asesoría legal: las reglas son configurables precisamente para que
> el área jurídica del cliente las ajuste sin cambiar código.
