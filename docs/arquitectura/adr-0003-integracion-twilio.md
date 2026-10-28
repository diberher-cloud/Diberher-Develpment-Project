# ADR-0003: Integración con Twilio Voice

- Estado: aceptado (implementado en 2A; llamadas IA, entrantes PSTN y transferencias a la consola en
  2D; llamadas de WhatsApp en 2F; progresivo humano en Fase 3)
- Fecha: 2026-10-23
- Actualizado: 2026-10-24 (estado real tras 2A: ubicación del puerto, `incoming_allow`,
  `crear_llamada_saliente` y firma compartida)
- Actualizado: 2026-10-28 (revisión de alcance "IA en voz": `crear_llamada_saliente` se adelanta a 2D
  para el marcador IA; el softphone recibe traspasos; ver ADR-0020 y ADR-0021)

## Contexto
Telefonía impuesta: Twilio Voice API, softphone WebRTC en el navegador con Twilio Voice JS SDK
(`@twilio/voice-sdk` 2.x), webhooks de estado y grabación. La Fase 1 no debe depender de credenciales.
Desde 2D las llamadas las atiende un agente IA (ConversationRelay, ADR-0020) y los humanos reciben
traspasos.

## Decisión
1. **Puerto/adaptador**: interfaz `ProveedorTelefonia` en `app/integraciones/telefonia/proveedor.py`
   con `emitir_token(identity, ttl_segundos)`, `colgar(call_sid)` y `validar_firma(url, params, firma)`.
   `crear_llamada_saliente(destino, origen, url_twiml, callback_estado, amd, grabar, timeout,
   time_limit) -> str (CallSid)` se añade en **2D** (marcador IA, ADR-0021; antes previsto para el
   progresivo de la Fase 3), con AMD asíncrono (`async_amd_status_callback`). Implementaciones:
   `ProveedorTwilio` (SDK `twilio` de Python) y `ProveedorTelefoniaFalso` (tests y desarrollo sin
   credenciales). Se elige por variable `TELEFONIA_PROVEEDOR=twilio|falso`. La firma
   (`X-Twilio-Signature`) es una función pura compartida con WhatsApp (`app/integraciones/twilio_firma.py`,
   ADR-0013).
2. **Softphone**: Access Token con `VoiceGrant(outgoing_application_sid=<TwiML App>,
   incoming_allow=False)` en 2A (el navegador no llama a `device.register()` porque no recibe
   llamadas), identity `agente_<usuario_id>`, TTL `TELEFONIA_TOKEN_TTL_SEGUNDOS` (1 h), renovación al
   recibir `tokenWillExpire`. Pasa a `incoming_allow=True` (y `device.register()`) en **2D** para
   recibir los **traspasos de llamadas atendidas por la IA** (`<Dial><Client>`), y lo usarán también
   las entrantes de WhatsApp sin IA (2F) y el progresivo de la Fase 3. Endpoint
   `POST /api/v1/telefonia/token` (rol agente).
3. **Llamada preview/manual**: `device.connect({ params: { campana_cliente_id, telefono_id } })`. Twilio
   llama al Voice URL de la TwiML App (`POST /api/v1/telefonia/twiml/saliente`). El backend valida la firma,
   que `From == client:agente_<id>` corresponde a un agente activo asignado a la campaña, **resuelve el
   número en servidor** y evalúa cumplimiento (franjas, festivos, exclusiones, frecuencia). Si se permite
   responde `<Dial callerId=… record="record-from-answer-dual" recordingStatusCallback=… action=…><Number statusCallback=… statusCallbackEvent="initiated ringing answered completed">+57…</Number></Dial>`;
   si no, `<Say>` breve + `<Hangup/>` y el motivo se envía a la consola. Contrato literal en
   `fase-2.md` §4.5. Sigue vigente para campañas con `voz_modo=humano`.
4. **Llamadas IA** (2D): el marcador crea la llamada por REST; el TwiML de inicio responde
   `<Connect action=…><ConversationRelay …/></Connect>` (ADR-0020). Las entrantes PSTN al número de la
   empresa llegan a `POST /api/v1/telefonia/twiml/entrante` y, si se identifica un único registro de
   una campaña con voz IA, se conectan igual.
5. **Progresivo** (fase 3, campañas humanas): el worker crea la llamada con REST (`machine_detection`), y el TwiML de
   respuesta conecta con `<Dial><Client>agente_<id></Client></Dial>`; el navegador acepta automáticamente
   si el agente está en modo progresivo (requiere `incoming_allow=True`, punto 2).
6. **Webhooks** bajo `/api/v1/telefonia/webhooks/…`: validación de `X-Twilio-Signature` con la URL pública
   configurada (`PUBLIC_BASE_URL`), respuesta < 2 s, persistencia idempotente en `eventos_llamada`
   (único por `call_sid + estado + secuencia`). Sin JWT (los autentica la firma). Desde 2B la
   dependencia de validación vive en `app/integraciones/twilio_webhook.py` y la comparten voz y
   WhatsApp. 2D añade `webhooks/amd`.
7. **Grabación**: dual channel; se guarda el `RecordingSid`/URL de Twilio, no el audio, en el MVP. El
   acceso a la grabación pasa por el backend (proxy autenticado + auditoría). Aviso de grabación al inicio
   en la pierna del cliente (`<Number url="…/twiml/aviso-grabacion">`, texto configurable) por Habeas
   Data; en llamadas IA el aviso va en el saludo determinista (ADR-0020 §7).
8. Desarrollo local de webhooks: túnel (`cloudflared`/`ngrok`) y `PUBLIC_BASE_URL`. El WebSocket de
   ConversationRelay necesita además `wss://` público hacia el servicio `voz-ia`.

## Alternativas consideradas
- **Conferencias para todas las llamadas**: facilitan escucha/susurro y transferencias, pero añaden
  latencia y complejidad; se reservan para fase 5 (supervisión en vivo, predictivo).
- **Número enviado desde el navegador**: rechazado; permitiría marcar números excluidos o fuera de campaña.
- **Twilio Flex / TaskRouter**: acelera, pero acopla el producto y el coste; el marcador propio es simple
  en modo 1:1 y con concurrencia controlada para IA.
- **`incoming_allow=True` desde 2A**: registraría el dispositivo para entrantes que todavía no existen;
  se habilita cuando haya un flujo que las use (traspasos de 2D).

## Consecuencias
- + Fase 1-2 testeables sin Twilio real; el cumplimiento se aplica donde no se puede saltar.
- − Requiere URL pública para webhooks incluso en desarrollo con Twilio real.
- − Pendiente: número/caller ID colombiano en Twilio y requisitos regulatorios del número (ver preguntas abiertas).
- − Pendiente de validar con Twilio real que el softphone sin `register()` realiza salientes y renueva
  el token sin cortar la llamada (`docs/pendientes.md` §5).
