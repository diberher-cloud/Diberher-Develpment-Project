# ADR-0004: Tiempo real con WebSocket y LISTEN/NOTIFY de PostgreSQL

- Estado: aceptado (implementación **adelantada a la subfase 2A**, ver ADR-0017; eventos de WhatsApp e IA en 2B-2C, ADR-0016)
- Fecha: 2026-10-23

## Contexto
La consola del agente necesita recibir asignaciones de llamada y cambios de estado; el panel de
supervisión, estados de agentes y métricas de campaña en vivo. Los eventos nacen en distintos procesos:
API (webhooks de Twilio, tipificaciones) y worker del marcador.

## Decisión
- Endpoint WebSocket nativo de FastAPI `GET /api/v1/ws?token=<jwt>` (el token va en query porque el
  navegador no permite cabeceras en WebSocket; se valida al conectar y se cierra con código 4401 si expira).
- Mensajes JSON `{ "tipo": "agente.estado" | "llamada.estado" | "marcador.asignacion" | "campana.metricas", "datos": {...}, "emitido_en": "<ISO-8601 UTC>" }`.
  (Tipos ampliados en fase 2: `consola.registro`, `conversacion.mensaje`, `conversacion.estado`,
  `atencion.cola`, `ia.alerta`; ver `fase-2.md`.)
- Bus entre procesos: `NOTIFY eventos, '<json>'` con payload pequeño (ids y estado; < 8000 bytes). Cada
  instancia de la API mantiene una conexión `LISTEN eventos` (psycopg 3 async) y reparte a los sockets
  según rol: agente → solo sus eventos; supervisor/admin → todos.
- Métricas agregadas del panel: recalculadas cada 5 s por consulta y emitidas (no por evento individual).
- Fallback del cliente: reconexión con backoff y recarga del estado por REST al reconectar.

## Alternativas consideradas
- **Redis pub/sub**: estándar, pero añade infraestructura; reconsiderar si hay > 1 instancia con mucha carga.
- **Server-Sent Events**: unidireccional y suficiente para el panel, pero el agente también envía
  señales (latido, estado); un solo mecanismo es más simple.
- **Polling**: aceptable para reportes, no para asignaciones del progresivo (latencia).

## Consecuencias
- + Sin nuevas piezas de infraestructura.
- − `NOTIFY` no persiste: si nadie escucha, el evento se pierde; por eso el estado autoritativo siempre
  está en tablas y el cliente resincroniza por REST.
- − En tests se sustituye el bus por uno en memoria.
