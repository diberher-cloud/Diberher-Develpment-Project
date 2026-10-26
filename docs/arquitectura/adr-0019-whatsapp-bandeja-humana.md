# ADR-0019: WhatsApp base y bandeja humana (subfase 2B)

- Estado: aceptado (implementación en subfase 2B)
- Fecha: 2026-10-24
- Concreta: ADR-0010 (proveedor), ADR-0011 (conversaciones), ADR-0012 (cumplimiento), ADR-0013
  (webhooks y cola), ADR-0016 (traspaso). Detalle de contrato en [`fase-2b.md`](fase-2b.md).

## Contexto
La subfase 2B abre el canal WhatsApp con atención humana y debe dejar el modelo listo para que en 2C
un agente IA sea el dueño de las conversaciones. Varias decisiones de los ADR anteriores quedaban a
nivel medio y hay que fijarlas: qué hace el webhook entrante y qué el worker, cómo se modela el dueño,
cómo se aplica la ventana de 24 h y la franja a las respuestas, qué se hace con los medios, cómo se
detecta el opt-out sin IA, cómo responde la API cuando el cumplimiento bloquea una plantilla y cómo
llegan las variables de entorno a los contenedores.

## Decisión
1. **Webhook entrante = persistir y encolar.** El webhook valida firma, guarda el mensaje
   (`conversacion_id` nulo, `proveedor_id` único) y encola `whatsapp.procesar_entrante` con solo el id.
   La resolución del contexto, el opt-out y el enrutado los hace el worker. Motivo: Twilio Messaging
   no reintenta por defecto; un fallo en lógica de negocio dentro del webhook perdería el mensaje. Se
   recomienda además `#rc=3&rp=ct,rt,5xx` en la URL (el fragmento no se firma).
2. **Dueño de la conversación** independiente del ciclo de vida: `estado` (`abierta`/`cerrada`) y
   `atendida_por` (`sin_asignar`/`humano`/`ia`) + `usuario_asignado_id`, con CHECK de coherencia.
   Todo cambio de dueño pasa por un único servicio `cambiar_dueno` que mantiene `cola_atencion`,
   auditoría y eventos. El traspaso IA ↔ humano de 2C es solo otra llamada a ese servicio.
3. **Ventana y franja en respuestas.** Texto libre solo con `ahora < ventana_expira_en − margen`
   (60 s). Con `entrantes.responder_fuera_de_franja=false`, la respuesta se **retiene** hasta la
   próxima franja si cae dentro de la ventana; si no cabe, se rechaza (`RESPUESTA_FUERA_DE_FRANJA`) y
   el agente debe usar plantilla en franja. Sin campaña se aplica la política más restrictiva de las
   activas. Los **mensajes automáticos** fijos (confirmación de opt-out, espera, aviso de fuera de
   franja) se envían siempre dentro de la ventana: son acuse inmediato de un mensaje del cliente
   (ADR-0012 §3). Las respuestas no crean `intentos_contacto`; las plantillas sí.
4. **Plantilla bloqueada por cumplimiento no es un error HTTP**: `200 ResultadoEnvioPlantilla` con
   `permitido=false` y todos los motivos (`EXCLUIDO`, `SIN_AUTORIZACION`, horario y frecuencia), igual
   que la simulación de llamadas de 2A. Los errores 4xx quedan para validación y estado.
5. **Opt-out determinista** por coincidencia **exacta** tras normalizar (sin tildes, signos ni
   emojis, sin fórmulas de cortesía al inicio/fin), con dos listas configurables (alcance `whatsapp` y
   `todos`) y el payload del botón de baja. Nunca por subcadena; "cancelar" se excluye porque en
   Colombia significa pagar. Las paráfrasis las registra el agente con `POST /conversaciones/{id}/opt-out`
   (y la IA con su herramienta en 2C). El opt-out revoca las autorizaciones de WhatsApp.
6. **Medios entrantes por proxy, sin almacenar.** Se guarda tipo y URL de Twilio (nunca enviada al
   navegador); el backend descarga con Basic Auth (API Key) solo desde el prefijo de la cuenta
   (anti-SSRF), con límite de 16 MiB y lista blanca (imagen jpeg/png/webp, audio, PDF), y responde con
   `nosniff`, `no-store` y `CSP sandbox`. Sin medios salientes en 2B (exigirían alojar ficheros en una
   URL pública).
7. **Envío "como mucho una vez".** El worker marca `enviando` y confirma antes de llamar al proveedor;
   si un reintento encuentra `enviando`, marca `ENVIO_INCIERTO` en vez de reenviar. Solo se reintenta
   lo que con seguridad no salió (429, 503, error de conexión). Los estados de entrega se aplican de
   forma monótona y pueden llegar antes de que se guarde el SID (se guardan y se aplican después).
8. **Cola `trabajos`**: `clave_unica` deduplica solo mientras el trabajo está pendiente (se libera al
   tomarlo), lo que da el *debounce* de turnos de IA de 2C sin perder mensajes llegados durante un
   turno. Worker de un solo hilo por proceso, réplicas seguras con `SKIP LOCKED`, latido en
   `latidos_worker` y `--healthcheck`.
9. **Orden global de bloqueos**: `estados_agente` → `clientes` → `conversaciones` → `cola_atencion` →
   `mensajes` (amplía la regla B4 de 2A), con una excepción acotada en `tomar-siguiente` (SKIP LOCKED +
   UPDATE condicional).
10. **docker-compose con `env_file`** compartido por `backend` y `worker` (ancla YAML), manteniendo en
    `environment` solo `DATABASE_URL` (host de compose) y la comprobación de `JWT_SECRETO`.

## Alternativas consideradas
- **Procesar el entrante dentro del webhook**: menos latencia y sin `conversacion_id` nulo, pero un
  error pierde el mensaje (sin reintentos por defecto). Rechazada.
- **Guardar el entrante crudo en el payload de `trabajos`**: duplicaría datos personales fuera de la
  tabla con retención; se guarda en `mensajes` y el trabajo lleva solo el id.
- **Descargar y almacenar los medios** (disco o S3): independencia de Twilio, pero añade
  almacenamiento, cifrado y retención propios; se pospone (la interfaz `descargar_media` permite
  cambiarlo).
- **Opt-out por subcadena o por IA**: más cobertura, pero falsos positivos ("quiero cancelar la
  deuda") o no determinista; rechazadas como mecanismo principal.
- **Plantilla bloqueada como `409` con motivos en `detalles`**: obligaría a ampliar el formato de error
  común con códigos por detalle; se prefiere un resultado tipado.
- **Lista explícita de variables en docker-compose**: es lo que causó la deuda de 2A; rechazada.
- **Columna de "habilidad WhatsApp" por agente**: la asignación a una campaña con
  `whatsapp_habilitado` basta en 2B.

## Consecuencias
- + 2C solo añade tablas nuevas y la función de decisión de dueño; no altera tablas de 2B.
- + Todo es verificable sin credenciales (proveedor falso con reglas de error deterministas,
  simulador, `ejecutar_pendientes`).
- − Un proceso más (`worker`) y latencia de hasta `WORKER_INTERVALO_SEGUNDOS` en los entrantes.
- − Los medios dependen de la disponibilidad de Twilio y de su retención.
- − `ENVIO_INCIERTO` exige revisión humana en el caso raro de caída de red tras enviar.
- − `env_file` exige Docker Compose ≥ 2.24 y pasa al contenedor todas las variables del `.env`.
