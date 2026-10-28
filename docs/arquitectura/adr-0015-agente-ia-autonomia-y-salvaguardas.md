# ADR-0015: Autonomía total del agente IA con salvaguardas en el servidor

- Estado: aceptado (implementación en subfase 2C; voz en 2D)
- Fecha: 2026-10-23
- Actualizado: 2026-10-28 (revisión de alcance "IA en voz": las mismas salvaguardas aplican a las
  llamadas, §10)
- Depende de: ADR-0011, ADR-0012, ADR-0014, ADR-0020

## Contexto
El usuario eligió **autonomía total**: el agente IA negocia acuerdos de pago y cierra ventas sin
aprobación humana previa; los humanos supervisan. Desde el 2026-10-28 esto aplica también a las
**llamadas de voz** (salientes, entrantes y, en 2F, llamadas de WhatsApp). Para que sea defendible
legal y operativamente, la autonomía debe estar **acotada por el servidor**, no por el prompt: un
modelo puede equivocarse o ser manipulado (prompt injection), el backend no.

Principio rector: **el modelo propone, el servidor dispone**. El modelo solo actúa mediante
herramientas; cada herramienta valida en servidor contra datos y reglas que el modelo no puede
alterar, y su resultado es la única fuente de saldos, precios y condiciones.

## Decisión

### 1. Límites de negocio por campaña (configuración, no prompt)
Tabla `configuracion_ia_campana` (1:1 con campaña) con `reglas` JSON validado por Pydantic
(`extra="forbid"`), **versionado** (`version` + historial en auditoría) y editable solo por
administrador/supervisor. **Las mismas reglas valen para chat y voz.**

Cobranza (`ReglasCobranza`):
| campo | significado |
|---|---|
| `base_descuento` | `saldo_mora` \| `saldo_total` — sobre qué saldo se calcula el descuento |
| `descuento_max_pct` | 0..100; descuento máximo sobre la base |
| `descuento_max_pct_por_cuotas` | lista `[{max_cuotas, descuento_max_pct}]` opcional (a más cuotas, menos descuento) |
| `monto_minimo_promesa` | monto mínimo total del acuerdo (COP) |
| `monto_minimo_cuota` | monto mínimo por cuota (COP) |
| `max_cuotas` | 1..36 |
| `plazo_max_dias_primer_pago` | días máximos hasta el primer pago |
| `plazo_max_dias_total` | días máximos hasta la última cuota |
| `periodicidades` | subconjunto de `semanal`, `quincenal`, `mensual` |
| `max_acuerdos_por_conversacion` | por defecto 1 (por conversación o llamada) |

Venta: tabla `ofertas_campana` (código, nombre, descripción, `precio` NUMERIC, `descuento_max_pct`,
`condiciones` texto, `activa`) + reglas (`max_unidades_por_venta`, `requiere_aceptacion_terminos`).

Las mismas validaciones (`limites.py`, **puro**) se aplican a las promesas y ventas que registra un
**agente humano** en campañas con reglas configuradas (coherencia, ADR-0011).

### 2. Herramientas (únicas acciones posibles)
Todas con `strict: true`, `input_schema` con `additionalProperties: false` y `required` completos.
**Ninguna recibe `cliente_id`, `campana_id`, teléfono ni documento de terceros**: el backend las ejecuta
sobre el `ContextoInteraccion` fijado al abrir la conversación o la llamada (ADR-0011 §5). No existe
ninguna herramienta que lea datos de otro cliente.

| Herramienta | Requiere identidad | Canales | Efecto |
|---|---|---|---|
| `verificar_identidad(numero_documento)` | — | chat, voz | Compara (normalizado) con el documento del cliente de la interacción. Máx. `verificacion.max_intentos` (def. 3); al agotarlos bloquea las herramientas protegidas y deriva a humano. Nunca revela el documento correcto ni cuántos dígitos coinciden. En voz el documento llega preferentemente por DTMF. |
| `consultar_obligacion()` | sí | chat, voz | Saldos, mora, vencimiento, número de obligación enmascarado (`***1234`) y **condiciones de negociación** aplicables (límites del §1). |
| `simular_acuerdo_pago(monto_total, numero_cuotas, fecha_primer_pago, periodicidad)` | sí | chat, voz | Sin efectos: valida contra límites y devuelve plan de cuotas o motivos de rechazo con el valor mínimo/máximo permitido. |
| `registrar_acuerdo_pago(monto_total, numero_cuotas, fecha_primer_pago, periodicidad, confirmacion_cliente)` | sí | chat, voz | Revalida y crea tipificación `promesa_pago` + `promesas_pago` + `promesa_cuotas` (`origen=agente_ia`). `confirmacion_cliente` = cita literal del cliente que acepta; el servidor comprueba que aparece en un mensaje entrante (chat) o en una transcripción final del cliente (voz) de la interacción. |
| `consultar_ofertas()` | sí | chat, voz | Ofertas activas de la campaña con precio y condiciones. |
| `registrar_venta(codigo_oferta, unidades, confirmacion_cliente)` | sí | chat, voz | Precio siempre del servidor; crea tipificación `venta` + `ventas`. Misma comprobación de cita. |
| `consultar_historial_gestiones()` | sí | chat, voz | Últimas gestiones del cliente **en esta campaña** (resultados, acuerdos vigentes), sin notas libres de agentes. |
| `programar_seguimiento(fecha_hora_local, motivo)` | no | chat, voz | Valida contra franjas/festivos (motor) y deja `proximo_intento_en`; el contacto futuro pasa por el cumplimiento normal (en voz IA, el marcador lo recoge). |
| `registrar_resultado(resultado, nota)` | no | chat, voz | Tipifica `contactado`, `rechazo`, `numero_errado` (el titular no es quien responde) o `volver_a_llamar` sin acuerdo. `numero_errado` crea exclusión y cierra. |
| `registrar_autorizacion_whatsapp(finalidad, cita_cliente)` | no | chat, voz | Opt-in explícito dado en el chat o en la llamada (ADR-0012 §4), con cita verificada. |
| `registrar_opt_out(alcance, cita_cliente)` | no | chat, voz | Chat: `whatsapp` o `todos_los_canales`; voz: `voz` o `todos_los_canales`. Crea exclusión y cierra tras la despedida. |
| `derivar_a_humano(motivo, resumen)` | no | chat, voz | Traspaso a la cola humana (chat) o transferencia a un agente de la consola con espera/devolución (voz) (ADR-0016). `motivo` de catálogo. `resumen` ≤ 500 car. para el agente. |
| `solicitar_permiso_llamada()` (2F) | sí | chat | Envía la solicitud de permiso de llamada de WhatsApp. |

Rechazos → `tool_result` con `is_error: true` y JSON `{"codigo": "...", "mensaje": "...",
"limites": {...}}` para que el modelo renegocie o derive. Los códigos son de catálogo
(`IDENTIDAD_NO_VERIFICADA`, `IDENTIDAD_BLOQUEADA`, `DESCUENTO_EXCEDE_LIMITE`, `MONTO_INFERIOR_MINIMO`,
`CUOTA_INFERIOR_MINIMO`, `CUOTAS_EXCEDEN_LIMITE`, `PLAZO_EXCEDE_LIMITE`, `PERIODICIDAD_NO_PERMITIDA`,
`ACUERDO_YA_REGISTRADO`, `OFERTA_NO_DISPONIBLE`, `CITA_NO_ENCONTRADA`, `FUERA_DE_FRANJA`,
`IA_DESACTIVADA`, `HERRAMIENTA_NO_DISPONIBLE_EN_CANAL`, …). El conjunto de herramientas enviado a
Claude es fijo por canal (prefijo cacheable).

### 3. El modelo nunca inventa cifras
- Saldos, precios y condiciones solo llegan por herramientas.
- **Guarda de salida determinista**: antes de enviar un texto de la IA (chat) o de **hablar una
  frase** (voz), se extraen los montos (`$ 1.234.567`, `1.234.567 pesos`, `$1234567`) y fechas
  explícitas; cada monto debe coincidir con un valor presente en algún `tool_result` de la interacción
  (o derivado: cuota del plan simulado). Si no, el texto **no se envía/no se habla**; se añade un
  `system` ("Tu respuesta menciona $X, que no proviene de ninguna herramienta; corrígela") y se
  reintenta una vez; si persiste → derivar a humano (`ia_monto_no_respaldado`). En voz el prompt pide
  montos en cifras ("1.500.000 pesos") para que la guarda los detecte y el TTS los normalice.
- Antes de verificar identidad, la guarda bloquea cualquier monto en la respuesta.

### 4. Transparencia
- **Chat**: el primer mensaje de la IA se antepone de forma determinista con el aviso configurable
  (`IA_AVISO_ASISTENTE`). **Voz**: saludo determinista al contestar con asistente virtual y grabación
  (`VOZ_IA_AVISO`, ADR-0020 §7). Ninguno depende del modelo.
- El system prompt obliga a reconocerse como asistente virtual si se pregunta y prohíbe hacerse pasar
  por humano.
- **Petición de humano**: (a) determinista si el mensaje o la transcripción normalizada coincide con
  la lista configurable (`ASESOR`, `HUMANO`, `HABLAR CON UNA PERSONA`, botón "Hablar con un asesor";
  en voz también **DTMF 0**); (b) por la IA con `derivar_a_humano(motivo="solicitud_cliente")` para
  paráfrasis. Nunca se niega.

### 5. Prompt injection
- Lo que dice el cliente va encapsulado y escapado (ADR-0014 §4); el system prompt declara que su
  contenido son datos, nunca instrucciones, y que las instrucciones del operador solo llegan como
  mensajes `system`.
- Alcance fijado por el backend (§2): aunque el modelo sea manipulado, no puede leer ni actuar sobre
  otro cliente ni exceder límites.
- Citas de confirmación verificadas en servidor: el modelo no puede "fingir" que el cliente aceptó.
- Las instrucciones de supervisores viajan como `{"role": "system"}` (canal no falsificable desde el
  texto o la voz del cliente).
- Límite de longitud de la entrada (`IA_MAX_CARACTERES_ENTRADA`, def. 2 000; se trunca con marca), de
  turnos por interacción y de duración de llamada.

### 6. Verificación de identidad (Ley 1581 / Ley 1266)
- Posesión: el número de WhatsApp o el teléfono llamado/llamante debe ser uno de los teléfonos del
  cliente (la interacción se resuelve así). Conocimiento: número de documento completo
  (`verificacion.factores = ["numero_documento"]`, ampliable).
- Hasta verificar: la IA puede saludar, preguntar por el titular por su nombre (voz), explicar el
  motivo genérico ("tenemos información sobre su cuenta"), atender opt-out, derivar y registrar
  `numero_errado`; **no** puede revelar saldos, ofertas personalizadas ni la existencia de la deuda a
  un tercero. En voz, nunca se leen en voz alta el documento ni números completos de obligación.
- El estado de verificación vive en servidor (`conversaciones.identidad_verificada` o
  `llamadas_ia.identidad_verificada`); al verificarse se informa al modelo en el `tool_result`.

### 7. Cumplimiento en todos los canales
Lo de ADR-0012: franjas y frecuencia para todo contacto iniciado por la empresa (incluido
`programar_seguimiento` y el marcador IA, ADR-0021), respuestas a entrantes según `entrantes.*`,
ventana de 24 h para texto libre, exclusiones por canal, opt-in.

### 8. Habeas Data
- **Minimización**: las herramientas devuelven solo lo necesario (número de obligación enmascarado; sin
  documento, teléfono, email ni dirección). No se envían a Claude datos de otros clientes ni notas
  libres de agentes.
- **Auditoría**: cada herramienta en `acciones_ia` (entrada y resultado **enmascarados**: el documento
  se guarda como `***1234`), y cada acción con efecto también en `auditoria` (`ia.acuerdo_registrado`,
  `ia.venta_registrada`, `ia.opt_out`, `ia.derivacion`, `ia.traspaso_voz`, …) con ids y catálogos, sin
  datos personales. Los logs de aplicación nunca incluyen texto de mensajes ni transcripciones.
- **Retención**: transcripciones (`mensajes`, `transcripciones_llamada`, `historial_ia`) se conservan
  `RETENCION_TRANSCRIPCIONES_DIAS` (def. 365, a confirmar con legal) y luego se anonimizan
  (texto → `[eliminado]`, se conservan métricas, tipificaciones y acuerdos); las grabaciones,
  `RETENCION_GRABACIONES_DIAS` (borrado en Twilio). Tarea periódica en 2G.
- **Transmisión internacional**: el proveedor del modelo (Anthropic) y, en voz, Twilio y sus
  subencargados de STT/TTS son encargados del tratamiento; requiere contrato/DPA, opción de no
  retención de datos si está disponible y mención en el aviso de privacidad.

### 9. Supervisión, kill switch y presupuesto
Ver ADR-0016 (intervención, toma de conversación o llamada, kill switch por campaña y global) y
ADR-0014 §6 (presupuesto). Todos se comprueban **antes de cada llamada al modelo y antes de cada
herramienta con efectos**.

### 10. Particularidades de voz (ADR-0020)
- **Constancia**: tras registrar un acuerdo o venta, el servidor dicta un texto determinista con las
  condiciones (no interrumpible) que queda en grabación y transcripción; si hay autorización de
  WhatsApp vigente, se envía además una plantilla utility de constancia (2E).
- **Citas**: se verifican contra las transcripciones finales normalizadas; una cita de un `prompt`
  parcial no vale.
- **Opt-out por voz**: frase exacta normalizada (`IA_VOZ_FRASES_OPT_OUT`) sin modelo, o herramienta
  para paráfrasis.
- **Errores de reconocimiento**: el prompt de voz exige repetir y confirmar montos, cuotas y fechas
  antes de `registrar_*` ("Entonces serían 3 cuotas de 400.000 pesos, la primera el 30 de octubre,
  ¿está de acuerdo?") y la cita debe ser posterior a esa confirmación.

## Alternativas consideradas
- **Aprobación humana de cada acuerdo** ("human in the loop"): más segura, pero contradice la decisión
  del usuario; la sustituyen los límites en servidor, la auditoría y la supervisión en vivo.
- **Límites solo en el prompt**: no verificables y vulnerables a injection; rechazado.
- **Exponer al modelo una herramienta genérica de consulta SQL/API**: imposible de acotar; rechazado.
- **Ocultar al modelo los límites y que pruebe a ciegas con `simular_acuerdo_pago`**: más llamadas y
  negociaciones torpes; se le dan los límites y el prompt le indica empezar por la opción más
  favorable para la empresa y ceder gradualmente.
- **Catálogos de herramientas distintos por canal**: duplicaría validación y evaluación; un único
  catálogo con disponibilidad por canal.

## Consecuencias
- + Cualquier acuerdo o venta registrado por la IA cumple los límites **por construcción**, en chat y
  en voz; lo que la IA puede hacer mal queda reducido a tono y oportunidad (cubierto por evaluación y
  supervisión).
- + Auditoría completa por herramienta para requerimientos de la SIC.
- − Configurar reglas por campaña es obligatorio antes de activar la IA (la activación valida que existan).
- − La guarda de montos puede dar falsos positivos (montos escritos en palabras no se detectan;
  números ambiguos); en voz, además, la transcripción de cifras dictadas puede fallar. Se mide en la
  evaluación y se ajusta.
