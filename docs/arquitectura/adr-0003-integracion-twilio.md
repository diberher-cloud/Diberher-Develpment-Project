# ADR-0003: Integración con Twilio Voice

- Estado: aceptado (implementado en 2A; progresivo en Fase 3; entrantes de WhatsApp en 2E)
- Fecha: 2026-10-23
- Actualizado: 2026-10-24 (estado real tras 2A: ubicación del puerto, `incoming_allow`,
  `crear_llamada_saliente` y firma compartida)

## Contexto
Telefonía impuesta: Twilio Voice API, softphone WebRTC en el navegador con Twilio Voice JS SDK
(`@twilio/voice-sdk` 2.x), webhooks de estado y grabación. La Fase 1 no debe depender de credenciales.

## Decisión
1. **Puerto/adaptador**: interfaz `ProveedorTelefonia` en `app/integraciones/telefonia/proveedor.py`
   con `emitir_token(identity, ttl_segundos)`, `colgar(call_sid)` y `validar_firma(url, params, firma)`.
   `crear_llamada_saliente(destino, origen, url_twiml, callback_estado, amd)` se añade en la **Fase 3**
   (progresivo); en 2A todas las llamadas salen del navegador. Implementaciones: `ProveedorTwilio`
   (SDK `twilio` de Python) y `ProveedorTelefoniaFalso` (tests y desarrollo sin credenciales). Se
   elige por variable `TELEFONIA_PROVEEDOR=twilio|falso`. La firma (`X-Twilio-Signature`) es una
   función pura compartida con WhatsApp (`app/integraciones/twilio_firma.py`, ADR-0013).
2. **Softphone**: Access Token con `VoiceGrant(outgoing_application_sid=<TwiML App>,
   incoming_allow=False)` en 2A (el navegador no llama a `device.register()` porque no recibe
   llamadas), identity `agente_<usuario_id>`, TTL `TELEFONIA_TOKEN_TTL_SEGUNDOS` (1 h), renovación al
   recibir `tokenWillExpire`. Pasa a `incoming_allow=True` (y `device.register()`) cuando haya
   llamadas entrantes al agente: progresivo de la Fase 3 (`<Dial><Client>`) y entrantes de WhatsApp en
   2E. Endpoint `POST /api/v1/telefonia/token` (rol agente).
3. **Llamada preview/manual**: `device.connect({ params: { campana_cliente_id, telefono_id } })`. Twilio
   llama al Voice URL de la TwiML App (`POST /api/v1/telefonia/twiml/saliente`). El backend valida la firma,
   que `From == client:agente_<id>` corresponde a un agente activo asignado a la campaña, **resuelve el
   número en servidor** y evalúa cumplimiento (franjas, festivos, exclusiones, frecuencia). Si se permite
   responde `<Dial callerId=… record="record-from-answer-dual" recordingStatusCallback=… action=…><Number statusCallback=… statusCallbackEvent="initiated ringing answered completed">+57…</Number></Dial>`;
   si no, `<Say>` breve + `<Hangup/>` y el motivo se envía a la consola. Contrato literal en
   `fase-2.md` §4.5.
4. **Progresivo** (fase 3): el worker crea la llamada con REST (`machine_detection=Enable`), y el TwiML de
   respuesta conecta con `<Dial><Client>agente_<id></Client></Dial>`; el navegador acepta automáticamente
   si el agente está en modo progresivo (requiere `incoming_allow=True`, punto 2).
5. **Webhooks** bajo `/api/v1/telefonia/webhooks/…`: validación de `X-Twilio-Signature` con la URL pública
   configurada (`PUBLIC_BASE_URL`), respuesta < 2 s, persistencia idempotente en `eventos_llamada`
   (único por `call_sid + estado + secuencia`). Sin JWT (los autentica la firma). Desde 2B la
   dependencia de validación vive en `app/integraciones/twilio_webhook.py` y la comparten voz y
   WhatsApp.
6. **Grabación**: dual channel; se guarda el `RecordingSid`/URL de Twilio, no el audio, en el MVP. El
   acceso a la grabación pasa por el backend (proxy autenticado + auditoría). Aviso de grabación al inicio
   en la pierna del cliente (`<Number url="…/twiml/aviso-grabacion">`, texto configurable) por Habeas
   Data.
7. Desarrollo local de webhooks: túnel (`cloudflared`/`ngrok`) y `PUBLIC_BASE_URL`.

## Alternativas consideradas
- **Conferencias para todas las llamadas**: facilitan escucha/susurro y transferencias, pero añaden
  latencia y complejidad; se reservan para fase 5 (supervisión en vivo, predictivo).
- **Número enviado desde el navegador**: rechazado; permitiría marcar números excluidos o fuera de campaña.
- **Twilio Flex / TaskRouter**: acelera, pero acopla el producto y el coste; el marcador propio es simple
  en modo 1:1.
- **`incoming_allow=True` desde 2A**: registraría el dispositivo para entrantes que todavía no existen;
  se habilita cuando haya un flujo que las use.

## Consecuencias
- + Fase 1-2 testeables sin Twilio real; el cumplimiento se aplica donde no se puede saltar.
- − Requiere URL pública para webhooks incluso en desarrollo con Twilio real.
- − Pendiente: número/caller ID colombiano en Twilio y requisitos regulatorios del número (ver preguntas abiertas).
- − Pendiente de validar con Twilio real que el softphone sin `register()` realiza salientes y renueva
  el token sin cortar la llamada (`docs/pendientes.md` §5).
