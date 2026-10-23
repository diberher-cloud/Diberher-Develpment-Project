# ADR-0013: Webhooks firmados, idempotencia y cola de trabajos en PostgreSQL

- Estado: aceptado (2A: webhooks de voz; 2B: cola de trabajos y worker)
- Fecha: 2026-10-23
- Complementa: ADR-0003 (Twilio), ADR-0009 (cola con `SKIP LOCKED`)

## Contexto
Twilio notifica por webhooks: TwiML de llamadas, estados de llamada, grabaciones, mensajes de WhatsApp
entrantes y estados de entrega. Twilio espera respuesta rápida (los TwiML bloquean el inicio de la
llamada; el timeout de webhook es de 15 s) y **reintenta**, así que los eventos pueden llegar
duplicados o desordenados. El agente IA tarda segundos (varias llamadas a la API de Claude) y no puede
ejecutarse dentro del webhook. Los envíos masivos (2D) deben respetar ritmo y cumplimiento.

## Decisión
1. **Firma**: todo endpoint bajo `/api/v1/telefonia/twiml/*`, `/api/v1/telefonia/webhooks/*` y
   `/api/v1/whatsapp/webhooks/*` valida `X-Twilio-Signature` antes de cualquier otra cosa:
   - Algoritmo de Twilio implementado como **función pura** `firma_twilio(url, params, auth_token)` en
     `app/integraciones/twilio_firma.py`: `base64(HMAC-SHA1(auth_token, url + concat(k+v para cada
     parámetro POST ordenado por clave)))`; comparación en tiempo constante (`hmac.compare_digest`).
   - `url` = `PUBLIC_BASE_URL` + ruta + query original (nunca la URL que ve el servidor detrás del
     proxy).
   - Firma ausente o inválida → `403` con el formato de error común, código `FIRMA_INVALIDA`, sin
     procesar nada y con registro en log (sin parámetros).
   - En tests y con proveedor `falso` se usa el mismo algoritmo con `TWILIO_AUTH_TOKEN` de pruebas: los
     tests firman las peticiones con un helper; no hay "modo sin firma".
   - Estos endpoints **no** usan JWT; quedan fuera de CORS (no los llama el navegador).
2. **Idempotencia**:
   - Voz: `eventos_llamada` único por `(call_sid, estado_proveedor, secuencia)` (`SequenceNumber` de
     Twilio; 0 si no viene).
   - WhatsApp: `mensajes.proveedor_id` (`MessageSid`) único; estados en `eventos_mensaje` único por
     `(proveedor_id, estado)`.
   - Un duplicado responde igual que el original (200/204) sin efectos.
   - Estados que retroceden (p. ej. `delivered` tras `read`) se guardan como evento pero no degradan el
     estado actual (orden de estados definido en el servicio).
3. **Respuesta rápida**: los webhooks solo validan, persisten y **encolan**; objetivo < 500 ms. Los
   TwiML (que deciden si se marca) se calculan en línea porque son síncronos por naturaleza, con
   consultas acotadas e indexadas.
4. **Cola de trabajos** (2B) en PostgreSQL, tabla `trabajos`:
   `id, tipo, clave_unica (UNIQUE, nula), payload JSON, estado (pendiente|en_proceso|completado|fallido),
   intentos, max_intentos, disponible_desde, bloqueado_hasta, bloqueado_por, ultimo_error,
   creado_en, actualizado_en`.
   - Toma: `SELECT … WHERE estado='pendiente' AND disponible_desde<=now() ORDER BY disponible_desde
     FOR UPDATE SKIP LOCKED LIMIT n` (PostgreSQL). En SQLite (tests) el mismo servicio funciona sin
     `SKIP LOCKED` (un solo proceso) y los tests ejecutan los trabajos de forma síncrona con
     `ejecutar_pendientes(db)`.
   - Reintento con backoff exponencial (`disponible_desde = ahora + 2^intentos · 5 s`, máx. 10 min);
     al agotar `max_intentos` → `fallido` + alerta en supervisión.
   - `clave_unica` deduplica trabajos lógicos (p. ej. `turno_ia:<conversacion_id>` mientras esté
     pendiente: varios mensajes seguidos del cliente producen **un** turno de IA — debounce).
   - Reservas caducadas (`bloqueado_hasta < now()`) se recuperan (worker caído).
   - `ultimo_error` sin datos personales (tipo de excepción y código).
5. **Worker**: mismo código, otro proceso `python -m app.worker` (servicio `worker` en
   docker-compose). Tipos iniciales: `whatsapp.procesar_entrante`, `ia.turno`,
   `whatsapp.enviar_mensaje`, `whatsapp.envio_masivo_lote` (2D), `conversaciones.cerrar_inactivas`
   (periódico). El marcador de Fase 3 reutilizará la misma infraestructura.
6. **Eventos en tiempo real** tras confirmar la transacción (ADR-0004): el worker y la API publican con
   `NOTIFY`; la API reenvía por WebSocket.

## Alternativas consideradas
- **Procesar el turno de IA dentro del webhook**: Twilio reintentaría por timeout y duplicaría
  respuestas; rechazado.
- **Celery/RQ + Redis**: estándar pero añade infraestructura (ADR-0001); la tabla `trabajos` basta para
  decenas de mensajes por segundo.
- **`BackgroundTasks` de FastAPI**: se pierden si el proceso cae; sin reintentos ni visibilidad.
- **Validar por IP de origen**: Twilio no garantiza IPs estables.

## Consecuencias
- + Webhooks robustos ante duplicados, reintentos y caídas; trabajos visibles y reintentables.
- + Sin nueva infraestructura.
- − Un proceso más que operar (`worker`), con su healthcheck (último latido en tabla o log).
- − Requiere `PUBLIC_BASE_URL` exacta; un proxy que reescriba la URL rompe la firma (documentado).
