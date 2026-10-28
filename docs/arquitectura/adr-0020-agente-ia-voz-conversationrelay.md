# ADR-0020: Agente IA de voz con Twilio ConversationRelay y Claude en streaming

- Estado: aceptado (implementación en subfase 2D; llamadas de WhatsApp en 2F)
- Fecha: 2026-10-28
- Depende de: ADR-0003 (Twilio Voice), ADR-0013 (webhooks), ADR-0014 (agente IA), ADR-0015
  (salvaguardas), ADR-0016 (traspaso), ADR-0017 (consola y tipificaciones), ADR-0021 (marcador IA)

## Contexto
Cambio de alcance del usuario (2026-10-28): "las llamadas se atienden por un agente de IA". Las
llamadas de voz (salientes de campañas de venta y cobranza, entrantes PSTN y, en 2F, llamadas de
WhatsApp) las atiende un agente de IA con Claude, con la **misma autonomía total** que en chat
(ADR-0015: negocia acuerdos y cierra ventas dentro de límites validados por el servidor) y con
traspaso a un humano cuando el cliente lo pide o la IA lo decide. **Decisión confirmada por el
usuario**: habrá agentes humanos de respaldo en la consola de 2A para los traspasos; si no hay ninguno
disponible se aplica espera corta y, si no, devolución de llamada (§9).

Lo construido en 2A (consola, softphone, estados de agente, tipificaciones, frecuencia, reservas)
sigue vigente como destino de los traspasos y para supervisión.

En voz la latencia de turno manda: una pausa de más de ~1 s se percibe como fallo de la línea, y el
cliente interrumpe ("barge-in"). La API de Claude no recibe ni produce audio: hace falta convertir voz
a texto (STT) y texto a voz (TTS) alrededor del modelo.

### Investigación (búsquedas web, octubre de 2026; `twilio.com` no fue accesible para lectura directa
### desde la sesión de diseño: los puntos marcados "verificar" se comprueban al iniciar 2D)

| Aspecto | Twilio ConversationRelay | Media Streams + STT/TTS propios | Plataforma de voz IA de terceros (Vapi, Retell, agentes de ElevenLabs…) con Claude como LLM |
|---|---|---|---|
| Qué hace Twilio | STT y TTS gestionados; nuestro backend recibe **texto** por WebSocket y responde **texto** (tokens en streaming) | Envía audio μ-law 8 kHz en base64 por WebSocket bidireccional (`<Connect><Stream>`, un stream por llamada; DTMF solo entrante) | Solo transporte (SIP o número) |
| Lo que operamos | Un servidor WebSocket de texto | Servidor de medios: VAD, detección de fin de turno, barge-in, códecs, conexión a STT y TTS en streaming | La integración con el tercero (webhooks de herramientas) |
| Mensajes | Entrantes: `setup`, `prompt` (transcripción, `last`), `dtmf`, `interrupt` (lo dicho hasta el corte y ms transcurridos), `error`. Salientes: `text` (`token`, `last`, `interruptible`), `end` (`handoffData` → callback `action` de `<Connect>`), cambio de idioma, envío de dígitos | Eventos `start`/`media`/`mark`/`stop` de audio | Propios de cada plataforma |
| Interrupciones | `interruptible` = `none\|dtmf\|speech\|any`, por TwiML y por mensaje | Implementación propia | Gestionadas por el tercero |
| STT / TTS | STT: Deepgram (por defecto `nova-3-general` en cuentas nuevas desde sep-2025; Flux desde may-2026, con filtrado de *backchannel* en español) o Google. TTS: ElevenLabs (por defecto), Google, Amazon | Cualquier proveedor (Deepgram, Google, Azure, ElevenLabs, Cartesia…) | Las del tercero |
| Español de Colombia | Español disponible (ejemplos `es-ES`/`es-US`); `es-CO`/`es-419` **no confirmado** → verificar código de idioma y voces | Depende del proveedor elegido | Depende del tercero |
| Precio | **US$0,07/min** (página de precios de Twilio, ago-2026) + minutos de voz; LLM aparte | Minutos de voz + STT (~US$0,005-0,01/min) + TTS (por carácter) | US$0,05-0,15/min de plataforma + LLM + transporte |
| Reconexión | Si el WebSocket cae (error 64105), Twilio llama a la URL `action` de `<Connect>`; el backend puede devolver otro `<Connect><ConversationRelay>` para la misma `CallSid` | Propia | Del tercero |
| Llamadas WhatsApp | **No confirmado** que `<Connect><ConversationRelay>` funcione sobre llamadas de WhatsApp Business Calling (no se halló documentación) → verificar al iniciar 2F | Igual de incierto | Normalmente no |
| Datos | Audio y texto pasan por Twilio y sus subencargados de STT/TTS | Audio a nuestros proveedores | Audio, texto y herramientas pasan por otro encargado más |

Presupuestos de latencia publicados para agentes de voz: objetivo conversacional ~800 ms entre el fin
del habla y el primer audio; mediciones reales de proveedores ~680 ms p50 y ~1,5 s p95, con el primer
token del LLM como mayor componente. No hay cifras públicas para español.

## Decisión

### 1. Tecnología: ConversationRelay
Se usa **Twilio ConversationRelay** (TwiML `<Connect action="…"><ConversationRelay …/></Connect>`):
- Reutiliza lo que ya operamos (Twilio Voice, firma, números, webhooks de estado y grabación, TwiML).
- Nuestro backend solo maneja **texto**: el mismo núcleo del agente IA del chat (ADR-0014/0015) con
  un adaptador de canal. Sin servidor de medios ni dependencias de audio.
- Barge-in, detección de fin de turno, DTMF y normalización de TTS los resuelve Twilio.
- Es verificable sin credenciales: el protocolo es JSON por WebSocket y se simula en tests.

Parámetros por configuración (no código): `VOZ_IA_IDIOMA` (por defecto `es-US` hasta verificar
`es-CO`/`es-419`), `VOZ_IA_STT_PROVEEDOR` (`Deepgram`), `VOZ_IA_STT_MODELO` (`nova-3-general`;
evaluar `flux`), `VOZ_IA_TTS_PROVEEDOR` (`ElevenLabs`), `VOZ_IA_VOZ` (id de voz en español neutro o
colombiano, elegida tras escucha), `VOZ_IA_INTERRUPCION=speech`, `VOZ_IA_DTMF=true`,
`VOZ_IA_HINTS` (vocabulario: nombre de la empresa, "cédula", productos). Un adaptador
`app/integraciones/voz_ia/` aísla los nombres de atributos y mensajes de Twilio
(`traducir_entrante(json) -> EventoRelay`, `texto(token, ultimo, interrumpible) -> json`,
`fin(handoff) -> json`, `twiml_relay(...) -> str`).

### 2. Servicio de sesiones de voz
- **Proceso**: mismo código, nuevo punto de entrada ASGI `app.voz_ia:app` (servicio `voz-ia` en
  docker-compose; en desarrollo puede montarse dentro de la API con `VOZ_IA_EN_API=true`). Solo expone
  `GET /api/v1/voz-ia/ws` (WebSocket de ConversationRelay) y `GET /salud`. Se separa de la API porque
  sus conexiones duran minutos, son sensibles a la latencia y escalan con la concurrencia de llamadas,
  no con usuarios de la web. El proxy inverso enruta `/api/v1/voz-ia/` a este servicio.
- **Asíncrono**: el manejador WebSocket es `async`; el modelo se invoca con el SDK asíncrono
  (`anthropic.AsyncAnthropic`, `client.messages.stream`); las operaciones de BD (síncronas, ADR-0006)
  se ejecutan en hilos (`anyio.to_thread.run_sync`) con una sesión SQLAlchemy por operación y
  transacciones cortas. Nunca se mantiene una transacción abierta durante una llamada al modelo.
- **Estado**: en memoria del proceso solo lo efímero (búfer DTMF, temporizadores, tarea de streaming en
  curso). Todo lo necesario para reanudar está en BD: `llamadas_ia` (dueño, identidad, contadores,
  modelo), `historial_ia`, `transcripciones_llamada`, `acciones_ia`. Cualquier réplica puede atender una
  reconexión.
- **Autenticación del WebSocket**: el TwiML incluye la URL `wss://…/api/v1/voz-ia/ws?sesion=<token>`
  con un token aleatorio de **un solo uso**, 60 s de validez, guardado como hash en `llamadas_ia`
  (mismo patrón que los tickets de ADR-0017). Además se valida `X-Twilio-Signature` del *handshake*
  si Twilio la envía (verificar). El mensaje `setup` debe traer la misma `callSid` que la llamada del
  token; si no → cierre.
- **Reconexión**: si el WebSocket cae, Twilio invoca la URL `action` de `<Connect>`
  (`/api/v1/telefonia/twiml/voz-ia/fin-sesion?llamada_id=`, firmada). Si la llamada sigue activa, no
  hubo `end` voluntario y `reconexiones < VOZ_IA_MAX_RECONEXIONES` (2), se devuelve un nuevo
  `<Connect><ConversationRelay>` (token nuevo, saludo de reanudación fijo "Disculpe, se cortó un
  momento. Le escucho.") y la sesión continúa desde BD. Si no, traspaso a humano (§9) o despedida fija.
- **Escalado y apagado**: `VOZ_IA_MAX_SESIONES_POR_PROCESO` (por defecto 100; se rechaza el
  *handshake* por encima y el marcador nunca supera la concurrencia global, ADR-0021). En `SIGTERM`
  el proceso deja de aceptar sesiones y espera a que terminen las activas hasta
  `VOZ_IA_DRENAJE_SEGUNDOS` (900); al vencer, envía `end` con `handoffData={"motivo":"reinicio"}` y la
  URL `action` reconecta la llamada en otra réplica.
- **Latido**: cada sesión actualiza `llamadas_ia.latido_en` cada 10 s; un trabajo periódico detecta
  sesiones huérfanas (llamada activa sin latido) y alerta.

### 3. Núcleo compartido con el chat (ADR-0014/0015)
El bucle agéntico se refactoriza en un núcleo canal-agnóstico:
- `InteraccionIA` = conversación de WhatsApp **o** llamada: las tablas `historial_ia`, `acciones_ia`,
  `uso_ia` e `instrucciones_supervisor` (migración `0004`, 2C) llevan `conversacion_id` y `llamada_id`
  nulos con `CHECK` "exactamente uno" (se diseñan así desde 2C para no migrarlas en 2D).
- `ContextoInteraccion` (cliente, registro, campaña, identidad verificada, modelo, esfuerzo, versión
  de prompt) lo fija el **servidor** al abrir la interacción; las herramientas actúan sobre él.
- **Mismo catálogo de herramientas y mismos ejecutores** (`limites.py`, validación en servidor,
  idempotencia por `tool_use_id`, auditoría). Diferencias por canal declaradas en una tabla de
  disponibilidad: en voz no existen `solicitar_permiso_llamada` ni el envío de mensajes; se añade
  `transferir_a_humano` como alias semántico de `derivar_a_humano` (misma implementación) y
  `registrar_opt_out` admite el alcance `voz`.
- Adaptadores de canal: `CanalChat` (worker, `ClienteLLM.crear_mensaje`, envía por `ProveedorWhatsApp`)
  y `CanalVoz` (sesión WebSocket, `ClienteLLM.crear_mensaje_stream`, envía tokens a ConversationRelay).
- Prompts de sistema separados y versionados: `sistema_chat_v<N>.md` y `sistema_voz_v<N>.md`
  (estilo oral: frases cortas, una pregunta por turno, sin listas ni símbolos, montos como
  "1.500.000 pesos", fechas como "el 30 de octubre", nunca leer números de documento ni de
  obligación completos). El prefijo `tools` + `system` es estable por canal (caché por canal).
- **Modelo por canal**: `configuracion_ia_campana` añade `voz_modelo` y `voz_esfuerzo`. Por defecto en
  voz `claude-sonnet-5-5` con `output_config.effort="low"` (`IA_VOZ_MODELO_POR_DEFECTO`,
  `IA_VOZ_ESFUERZO_POR_DEFECTO`); `claude-haiku-5-5` como opción de menor latencia y coste si supera la
  evaluación; `claude-opus-5-5` posible (el *thinking* no se desactiva en Opus 5.5: solo `effort`),
  pero con más latencia. Modelo y esfuerzo se fijan al abrir la llamada.
- Restricciones de la API que se mantienen: sin `tool_choice` forzado (`auto` + `strict: true`), sin
  *prefill*, sin `temperature`/`top_p`/`top_k`, comprobación de `stop_reason` (incluido `refusal` con
  `betas=["server-side-fallback-2026-07-01"]` + `fallbacks="default"` si `IA_FALLBACK_RECHAZO`),
  instrucciones del supervisor como `{"role": "system"}` a mitad de conversación, historial
  append-only con los bloques completos.
- En streaming, las herramientas se declaran con `eager_input_streaming: true`.

### 4. Turno de voz en streaming
```
prompt(last=true) o dtmf terminado en '#'  →  turno
  guardas deterministas de entrada (opt-out por voz, petición de humano, DTMF 0)  → actuar y salir
  comprobar kill switch, presupuesto (campaña, llamada) y dueño == ia
  historial_ia += user [<habla_cliente>…</habla_cliente> | <dtmf>…</dtmf> | <interrupcion …/>]
  for i in 1..IA_MAX_ITERACIONES:
      stream = llm.crear_mensaje_stream(...)
      por cada delta de texto: acumular en búfer de FRASE
          al cerrar frase (. ? ! ; o salto) → guarda de montos/fechas sobre la frase
              ok   → enviar tokens de la frase a ConversationRelay (last=false)
              fallo→ cancelar stream, NO se dice nada de la frase, system de corrección, reintentar 1 vez
      al terminar: historial_ia += assistant (contenido completo, con thinking) ; uso_ia (+ ttft_ms)
      tool_use → si aún no se habló en el turno y la herramienta tarda > VOZ_IA_RELLENO_MS (700):
                   enviar frase de relleno FIJA ("Permítame un momento.")
                 ejecutar herramientas (hilo, transacción propia) ; continue
      end_turn → enviar text(last=true) ; break
      refusal/max_tokens/otro → traspaso (§9) con el motivo de ADR-0016
```
- La **guarda de montos** (ADR-0015 §3) se aplica **por frase antes de hablar**: lo que no se ha
  enviado a TTS no se ha dicho. Antes de verificar identidad se bloquea cualquier monto.
- **Constancia del acuerdo**: tras `registrar_acuerdo_pago`/`registrar_venta` el servidor dicta un
  texto **determinista** con las condiciones registradas (no lo redacta el modelo), con
  `interruptible=none`, y queda en la transcripción y la grabación.

### 5. Interrupciones, silencios y no respuesta
- **Interrupción** (`interrupt`): se cancela el stream en curso. Si la respuesta ya estaba completa en
  `historial_ia`, el siguiente `user` incluye `<interrupcion dicho_hasta="…"/>` (texto de Twilio) para
  que el modelo sepa qué oyó el cliente. Si se estaba generando, el turno del asistente se descarta
  (no se guarda un turno parcial: los bloques de *thinking* deben ir completos) y se informa igual.
  Una herramienta con efectos que ya empezó **termina** (transacción atómica) y su resultado se añade
  antes del nuevo turno del cliente. Los textos deterministas (aviso legal, constancia) son
  `interruptible=none`.
- **Silencio**: temporizador del servidor que arranca al enviar `last=true` más la duración estimada
  del habla (caracteres / `VOZ_IA_CARACTERES_POR_SEGUNDO`, 15) — ConversationRelay no notifica el fin
  de reproducción (verificar). Tras `VOZ_IA_SILENCIO_SEGUNDOS` (8) se dice un texto fijo ("¿Sigue en
  la línea?"); al segundo silencio consecutivo, despedida fija y colgar (`end`). Sin modelo.
- **Duración máxima**: `max_duracion_llamada_segundos` por campaña (def. 900) y `timeLimit` de Twilio
  como red de seguridad; al acercarse, el servidor añade un `system` pidiendo cerrar y, al vencer,
  despedida fija.

### 6. Contestadores (AMD) en salientes
- Llamadas creadas por REST con `machine_detection="DetectMessageEnd"` y **AMD asíncrono**
  (`async_amd=true`, `async_amd_status_callback=/api/v1/telefonia/webhooks/amd?llamada_id=`), para no
  añadir segundos de silencio a una persona que contesta "¿Aló?". Configurable
  `VOZ_IA_AMD=async|sync|off`.
- Mientras llega el resultado, la sesión arranca con el **saludo y aviso** (§7), que no contienen
  datos personales, así que oírlos un contestador no revela nada. El modelo **no** recibe el primer
  turno hasta que llegue `AnsweredBy=human` o `unknown`, o hasta que el cliente hable.
- `AnsweredBy` = `machine_*`/`fax` → `end` + colgar; **no se deja mensaje de voz** por defecto (dejar
  un mensaje sobre una deuda en un buzón puede revelarla a terceros): `VOZ_IA_MENSAJE_BUZON` vacío.
  Resultado técnico `buzon` (§10).
- La precisión del AMD en español no está publicada: se mide en piloto (falsos "humano" y falsos
  "máquina") y se ajustan `machine_detection_timeout` y umbrales.

### 7. Aviso legal y transparencia
- Saludo **determinista** en `welcomeGreeting` (no lo genera el modelo, no interrumpible; atributo de
  no interrupción a verificar), texto configurable `VOZ_IA_AVISO`: "Buenos días. Le habla el asistente
  virtual de {empresa}. Esta llamada es grabada y monitoreada. Puede pedir hablar con un asesor en
  cualquier momento." Va siempre, con o sin grabación (cierra el pendiente de 2A de aviso ligado a
  `TELEFONIA_GRABAR` para las llamadas IA).
- Luego, en saliente, se pregunta por el titular por su nombre ("¿Hablo con María?") sin mencionar
  motivo ni deuda. El prompt obliga a reconocerse como asistente virtual si se pregunta.

### 8. Identidad, opt-out y petición de humano por voz
- **Identidad** (ADR-0015 §6): posesión débil (se llamó a un teléfono del cliente o el número
  entrante es suyo) + conocimiento: número de documento completo, **preferentemente por teclado**
  (DTMF terminado en `#`, más preciso y privado que dictarlo) o hablado. La herramienta
  `verificar_identidad` es la misma (máx. intentos, sin revelar coincidencias). Hasta verificar, la IA
  no menciona deuda, saldos ni ofertas personalizadas; si quien contesta no es el titular → solo
  "volveremos a intentar", sin motivo (o `numero_errado` si dice que no lo conoce). Factores
  adicionales configurables (`verificacion.factores`).
- **Opt-out determinista** (sin modelo): transcripción final normalizada que coincide **exactamente**
  con una frase de `IA_VOZ_FRASES_OPT_OUT` ("no me llamen", "no me vuelvan a llamar", "no quiero más
  llamadas"…) → exclusión `canal=voz`, `aplica_a=todas`, `origen=sistema`; confirmación fija; colgar.
  Paráfrasis → herramienta `registrar_opt_out(alcance ∈ voz|todos_los_canales, cita_cliente)` con
  cita verificada contra la transcripción de la llamada.
- **Petición de humano** determinista: frase de `IA_VOZ_FRASES_HUMANO` o **DTMF `0`** → traspaso;
  paráfrasis → `derivar_a_humano(motivo="solicitud_cliente")`. Nunca se niega.
- Las citas (`confirmacion_cliente`, `cita_cliente`) se verifican contra los `prompt` finales de la
  llamada (normalizados: minúsculas, sin tildes ni signos).

### 9. Traspaso a humano (consola de 2A)
1. La IA (o una guarda) decide el traspaso: se guarda `traspasos_llamada` (motivo de catálogo de
   ADR-0016, resumen ≤ 500 de la IA, estado) y la sesión envía una frase fija ("Le comunico con un
   asesor, un momento por favor") y `end` con `handoffData={"traspaso_id": N}`.
2. Twilio llama a `action` (`/twiml/voz-ia/fin-sesion`). El backend busca un agente humano
   **asignado a la campaña** y `disponible` (orden: más tiempo disponible), lo bloquea
   (`estados_agente` FOR UPDATE SKIP LOCKED → `clientes` → `campana_clientes`, orden global), lo pasa a
   `en_llamada`, fija `llamadas.usuario_id` y la reserva del registro para él, y responde
   `<Dial timeout="20" action="…/twiml/voz-ia/traspaso-terminado?traspaso_id="><Client>agente_<id>
   <Parameter name="llamada_id" value="…"/></Client></Dial>`. El agente recibe la llamada en el
   softphone (`incoming_allow=True` + `device.register()` desde 2D) con la **ficha, el resumen de la
   IA y la transcripción** en la consola antes de contestar (transferencia con contexto; la IA no
   habla con el humano).
3. Si el agente no contesta en 20 s → se libera (vuelve a `disponible`) y se prueba el siguiente.
4. **Sin humano disponible** → **espera corta**: TwiML con mensaje fijo, música y `<Redirect>` cada
   `VOZ_TRASPASO_REINTENTO_SEGUNDOS` (10) para reintentar la asignación, hasta
   `VOZ_TRASPASO_ESPERA_MAX_SEGUNDOS` (120). Al vencer → **devolución de llamada**: mensaje fijo ("Un
   asesor le devolverá la llamada"), el registro queda con `requiere_humano=true` y
   `proximo_intento_en` = próxima ventana permitida, visible con prioridad en la lista de trabajo de
   la consola y **excluido del marcador IA**. Fuera del horario de humanos
   (`VOZ_HORARIO_HUMANOS`, configurable) se salta la espera y se ofrece la devolución directamente.
5. El humano tipifica la llamada como en 2A (si la IA ya registró una tipificación para esa llamada,
   el agente vuelve a `disponible` sin pendiente). No se devuelve una llamada de humano a la IA.

### 10. Transcripción, grabación y tipificación automática
- `transcripciones_llamada(llamada_id, secuencia, hablante ∈ cliente|ia|sistema|agente, texto,
  interrumpida, dicho_hasta, momento)`: lo que se dijo/oyó (como `mensajes` en chat);
  `historial_ia` es lo que vio el modelo. Grabación dual de toda la llamada (REST `record=true` en
  salientes; `<Start><Recording>` o equivalente en entrantes, verificar) con el mismo tratamiento de
  `grabaciones` (ADR-0003 §6). Retención `RETENCION_TRANSCRIPCIONES_DIAS` y
  `RETENCION_GRABACIONES_DIAS` con anonimización (2G). Nunca texto en logs.
- **Tipificación automática** con la tabla de efectos de 2A (`consola/efectos.py`, reutilizada) y
  `origen=agente_ia` (o `sistema` para resultados técnicos), `canal=voz`:

| Situación al finalizar | resultado | contacto_directo | origen |
|---|---|---|---|
| La IA registró acuerdo/venta/resultado por herramienta | el registrado | true (salvo `numero_errado`) | `agente_ia` |
| No contesta, ocupado, fallida, cancelada | `no_contesta` (observación con el estado técnico) | false | `sistema` |
| Contestador (`AnsweredBy=machine_*`) | `no_contesta` (observación `buzon`; reintento con el intervalo de buzón) | false | `sistema` |
| Contestó, colgó antes de verificar identidad | `no_contesta` (observación `colgo_sin_verificar`) — supuesto S-V5 | false | `sistema` |
| Contestó, identidad verificada, sin resultado registrado | `contactado` | true | `agente_ia` |
| Opt-out | `rechazo` + exclusión | true | `agente_ia`/`sistema` |
| Traspasada a humano | la tipifica el humano (2A) | según humano | `agente` |

  El servidor cierra siempre la tipificación pendiente en `finalizar` (no hay "tipificando" para la
  IA). `intentos_contacto.contacto_directo` se actualiza igual que en 2A.

### 11. Costes y latencia
- **Latencia objetivo de turno** (fin de habla del cliente → primer audio de la IA, medida como
  `prompt` recibido → primer token enviado, más la latencia de TTS de Twilio): **p50 ≤ 1,2 s y
  p95 ≤ 2,5 s** en turnos sin herramientas; en turnos con herramientas, frase de relleno en ≤ 1 s.
  Se registra `ttft_ms` y `primer_texto_ms` por llamada al modelo en `uso_ia` y se reporta por
  campaña. Palancas: modelo (Haiku/Sonnet), `effort=low`, caché del prefijo, prompt que pide
  respuestas de una o dos frases, envío por frases.
- **Coste por minuto estimado** (a validar en piloto; tarifas de Twilio Colombia de ago-2026):

| Componente | US$/min |
|---|---|
| Voz saliente a móvil Colombia (Twilio) | 0,0377 (fijo/local: 0,07) |
| ConversationRelay | 0,07 |
| Grabación (aprox.) | 0,0025 |
| Claude, ~5 turnos/min con prefijo cacheado, `effort=low`: Sonnet 5.5 | ~0,02 |
| (Opus 5.5 ~0,04 · Haiku 5.5 ~0,002) | |
| **Total aproximado** | **~0,13 con Sonnet** (≈0,11 con Haiku, ≈0,15 con Opus) |

  Más AMD por llamada (cargo por llamada de Twilio, verificar) y los intentos no contestados (solo
  AMD y segundos de timbre no se facturan; verificar). Una gestión de cobranza de 4 min ≈ US$0,50.
- Presupuesto: el de la campaña es común a chat y voz (`uso_ia` + coste estimado de telefonía por
  llamada en `llamadas_ia.costo_voz_usd`), más `max_costo_llamada_usd`. Al excederse la llamada →
  traspaso; al excederse la campaña → kill switch de voz (ADR-0016).

### 12. Verificación sin credenciales
- `ClienteLLMFalso` con `crear_mensaje_stream` (deltas guionizados, retardos configurables, eventos de
  *thinking* y `tool_use`).
- **Relay falso**: los tests abren el WebSocket real del servicio (`TestClient.websocket_connect`) y
  envían `setup`/`prompt`/`dtmf`/`interrupt` como lo haría Twilio; aserciones sobre los `text`/`end`
  recibidos y el estado en BD.
- `ProveedorTelefoniaFalso.crear_llamada_saliente` + endpoints de simulación (`contestada_humano`,
  `contestada_buzon`, `no_contesta`, `ocupado`, `colgada`, `ws_caido`) que ejecutan los mismos
  servicios que los webhooks.
- **Simulador web** (`/voz-ia/simulador`, solo `ENTORNO != produccion`): el navegador actúa como
  ConversationRelay (texto en lugar de voz) contra el mismo WebSocket.

## Alternativas consideradas
- **Media Streams + STT/TTS propios**: control fino de voces, endpointing y coste (sin los US$0,07/min
  de ConversationRelay), pero obliga a construir y operar un servidor de medios en tiempo real (VAD,
  fin de turno, barge-in, códecs, eco) difícil de probar sin credenciales. Se reserva como evolución
  si el coste por minuto o la calidad del español lo justifican; el núcleo canal-agnóstico no cambia
  (solo el adaptador de canal).
- **Plataforma de voz IA de terceros con Claude como "LLM personalizado"**: rápida de montar, pero las
  herramientas, límites y auditoría quedarían repartidos entre dos sistemas, añade otro encargado de
  datos personales y coste por minuto similar o mayor; rechazada.
- **Modelos *speech-to-speech***: no cumplen el requisito de usar Claude; rechazada.
- **SIP a un servidor propio (LiveKit, Pipecat…)**: misma complejidad que Media Streams; pospuesta.
- **Mantener humanos en voz y IA solo en chat**: contradice la decisión del usuario.
- **Un único prompt para chat y voz**: el estilo oral es distinto y el prefijo cacheado cambiaría
  según el canal; se versionan por separado.

## Consecuencias
- + Un solo núcleo de IA (herramientas, límites, auditoría, costes, evaluación) para chat y voz.
- + El backend no procesa audio; todo es verificable con texto y dobles falsos.
- + Lo construido en 2A se reutiliza como destino de traspasos, tipificación y supervisión.
- − Coste fijo de ConversationRelay (~US$0,07/min, más de la mitad del coste por minuto).
- − Dependencia de Twilio y de sus proveedores de STT/TTS para la calidad del español colombiano;
  hay que verificar idioma, voces y precisión de números dictados.
- − Un servicio nuevo (`voz-ia`) con conexiones largas: drenaje en despliegues y alertas de sesiones
  huérfanas.
- − Llamadas de WhatsApp atendidas por IA dependen de una capacidad no confirmada (2F empieza con una
  verificación; si no existe, esas llamadas van a humanos como en el diseño anterior).

## Fuentes
- Twilio: [precios de IA conversacional](https://www.twilio.com/en-us/products/conversational-ai/pricing),
  [`<ConversationRelay>`](https://www.twilio.com/docs/voice/twiml/connect/conversationrelay),
  [mensajes WebSocket](https://www.twilio.com/docs/voice/conversationrelay/websocket-messages),
  [elección de voz](https://www.twilio.com/docs/voice/conversationrelay/voice-configuration),
  [buenas prácticas](https://www.twilio.com/docs/voice/conversationrelay/best-practices),
  [Deepgram Nova-3](https://www.twilio.com/en-us/changelog/conversationrelay--deepgram-nova-3-speech-to-text-is-now-availab),
  [Deepgram Flux (may-2026)](https://www.twilio.com/en-us/changelog/conversation-relay-now-supports-deepgram-flux---new-features),
  [traspaso a Flex con `handoffData`](https://www.twilio.com/en-us/blog/developers/tutorials/integrations/conversationrelay-flex-contextual-escalations),
  [error 64105](https://www.twilio.com/docs/api/errors/64105),
  [Media Streams](https://www.twilio.com/docs/voice/media-streams),
  [AMD — buenas prácticas](https://www.twilio.com/docs/voice/answering-machine-detection-faq-best-practices),
  [precios de voz Colombia](https://www.twilio.com/en-us/voice/pricing/co),
  [WhatsApp Business Calling GA](https://www.twilio.com/en-us/changelog/whatsapp_business_calling_available).
- Secundarias: [ThunderPhone — precios de ConversationRelay](https://thunderphone.com/guides/twilio-conversationrelay-pricing),
  [ElevenLabs — latencia de agentes de voz](https://elevenlabs.io/blog/voice-agent-latency-optimization),
  [Twig — presupuesto de 800 ms](https://www.twig.so/blog/voice-ai-agents-latency-budget-800ms).
