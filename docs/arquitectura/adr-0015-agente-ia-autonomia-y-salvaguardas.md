# ADR-0015: Autonomía total del agente IA con salvaguardas en el servidor

- Estado: aceptado (implementación en subfase 2C)
- Fecha: 2026-10-23
- Depende de: ADR-0011, ADR-0012, ADR-0014

## Contexto
El usuario eligió **autonomía total**: el agente IA negocia acuerdos de pago y cierra ventas sin
aprobación humana previa; los humanos supervisan. Para que sea defendible legal y operativamente, la
autonomía debe estar **acotada por el servidor**, no por el prompt: un modelo puede equivocarse o ser
manipulado (prompt injection), el backend no.

Principio rector: **el modelo propone, el servidor dispone**. El modelo solo actúa mediante
herramientas; cada herramienta valida en servidor contra datos y reglas que el modelo no puede
alterar, y su resultado es la única fuente de saldos, precios y condiciones.

## Decisión

### 1. Límites de negocio por campaña (configuración, no prompt)
Tabla `configuracion_ia_campana` (1:1 con campaña) con `reglas` JSON validado por Pydantic
(`extra="forbid"`), **versionado** (`version` + historial en auditoría) y editable solo por
administrador/supervisor:

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
| `max_acuerdos_por_conversacion` | por defecto 1 |

Venta: tabla `ofertas_campana` (código, nombre, descripción, `precio` NUMERIC, `descuento_max_pct`,
`condiciones` texto, `activa`) + reglas (`max_unidades_por_venta`, `requiere_aceptacion_terminos`).

Las mismas validaciones (`limites.py`, **puro**) se aplican a las promesas y ventas que registra un
**agente humano** en campañas con reglas configuradas (coherencia, ADR-0011).

### 2. Herramientas (únicas acciones posibles)
Todas con `strict: true`, `input_schema` con `additionalProperties: false` y `required` completos.
**Ninguna recibe `cliente_id`, `campana_id`, teléfono ni documento de terceros**: el backend las ejecuta
sobre el `ContextoConversacion` fijado al abrir la conversación (ADR-0011 §5). No existe ninguna
herramienta que lea datos de otro cliente.

| Herramienta | Requiere identidad | Efecto |
|---|---|---|
| `verificar_identidad(numero_documento)` | — | Compara (normalizado) con el documento del cliente de la conversación. Máx. `verificacion.max_intentos` (def. 3); al agotarlos bloquea las herramientas protegidas y deriva a humano. Nunca revela el documento correcto ni cuántos dígitos coinciden. |
| `consultar_obligacion()` | sí | Saldos, mora, vencimiento, número de obligación enmascarado (`***1234`) y **condiciones de negociación** aplicables (límites del §1). |
| `simular_acuerdo_pago(monto_total, numero_cuotas, fecha_primer_pago, periodicidad)` | sí | Sin efectos: valida contra límites y devuelve plan de cuotas o motivos de rechazo con el valor mínimo/máximo permitido. |
| `registrar_acuerdo_pago(monto_total, numero_cuotas, fecha_primer_pago, periodicidad, confirmacion_cliente)` | sí | Revalida y crea tipificación `promesa_pago` + `promesas_pago` + `promesa_cuotas` (`origen=agente_ia`). `confirmacion_cliente` = cita literal del mensaje del cliente que acepta; el servidor comprueba que aparece en un mensaje entrante de la conversación. |
| `consultar_ofertas()` | sí | Ofertas activas de la campaña con precio y condiciones. |
| `registrar_venta(codigo_oferta, unidades, confirmacion_cliente)` | sí | Precio siempre del servidor; crea tipificación `venta` + `ventas`. Misma comprobación de cita. |
| `consultar_historial_gestiones()` | sí | Últimas gestiones del cliente **en esta campaña** (resultados, acuerdos vigentes), sin notas libres de agentes. |
| `programar_seguimiento(fecha_hora_local, motivo)` | no | Valida contra franjas/festivos (motor) y deja `proximo_intento_en`; el contacto futuro pasa por el cumplimiento normal. |
| `registrar_resultado(resultado, nota)` | no | Tipifica `contactado`, `rechazo`, `numero_errado` (el titular no es quien responde) o `volver_a_llamar` sin acuerdo. `numero_errado` crea exclusión y cierra. |
| `registrar_autorizacion_whatsapp(finalidad, cita_cliente)` | no | Opt-in explícito dado en el chat (ADR-0012 §4), con cita verificada. |
| `registrar_opt_out(alcance, cita_cliente)` | no | `whatsapp` o `todos_los_canales`; crea exclusión y cierra la conversación tras la despedida. |
| `derivar_a_humano(motivo, resumen)` | no | Traspaso a la cola humana (ADR-0016). `motivo` de catálogo. `resumen` ≤ 500 car. para el agente. |
| `solicitar_permiso_llamada()` (2E) | sí | Envía la solicitud de permiso de llamada de WhatsApp. |

Rechazos → `tool_result` con `is_error: true` y JSON `{"codigo": "...", "mensaje": "...",
"limites": {...}}` para que el modelo renegocie o derive. Los códigos son de catálogo
(`IDENTIDAD_NO_VERIFICADA`, `IDENTIDAD_BLOQUEADA`, `DESCUENTO_EXCEDE_LIMITE`, `MONTO_INFERIOR_MINIMO`,
`CUOTA_INFERIOR_MINIMO`, `CUOTAS_EXCEDEN_LIMITE`, `PLAZO_EXCEDE_LIMITE`, `PERIODICIDAD_NO_PERMITIDA`,
`ACUERDO_YA_REGISTRADO`, `OFERTA_NO_DISPONIBLE`, `CITA_NO_ENCONTRADA`, `FUERA_DE_FRANJA`,
`IA_DESACTIVADA`, …).

### 3. El modelo nunca inventa cifras
- Saldos, precios y condiciones solo llegan por herramientas.
- **Guarda de salida determinista**: antes de enviar un texto de la IA, se extraen los montos
  (`$ 1.234.567`, `1.234.567 pesos`, `$1234567`) y fechas explícitas; cada monto debe coincidir con un
  valor presente en algún `tool_result` de la conversación (o derivado: cuota del plan simulado). Si no,
  el texto **no se envía**; se añade un `system` ("Tu respuesta menciona $X, que no proviene de ninguna
  herramienta; corrígela") y se reintenta una vez; si persiste → derivar a humano
  (`ia_monto_no_respaldado`).
- Antes de verificar identidad, la guarda bloquea cualquier monto en la respuesta.

### 4. Transparencia
- El **primer mensaje** de la IA en cada conversación se antepone de forma determinista con el aviso
  configurable (`IA_AVISO_ASISTENTE`, p. ej. "Hola, soy el asistente virtual de {empresa}. Puedes
  pedir hablar con un asesor en cualquier momento."). No depende del modelo.
- El system prompt obliga a reconocerse como asistente virtual si se pregunta y prohíbe hacerse pasar
  por humano.
- **Petición de humano**: (a) determinista si el mensaje normalizado coincide con la lista configurable
  (`ASESOR`, `HUMANO`, `HABLAR CON UNA PERSONA`, botón "Hablar con un asesor"); (b) por la IA con
  `derivar_a_humano(motivo="solicitud_cliente")` para paráfrasis. Nunca se niega.

### 5. Prompt injection
- Mensajes del cliente encapsulados y escapados (ADR-0014 §4); el system prompt declara que su
  contenido son datos, nunca instrucciones, y que las instrucciones del operador solo llegan como
  mensajes `system`.
- Alcance fijado por el backend (§2): aunque el modelo sea manipulado, no puede leer ni actuar sobre
  otro cliente ni exceder límites.
- Citas de confirmación verificadas en servidor: el modelo no puede "fingir" que el cliente aceptó.
- Las instrucciones de supervisores viajan como `{"role": "system"}` (canal no falsificable desde el
  texto del cliente).
- Límite de longitud del mensaje entrante (`IA_MAX_CARACTERES_ENTRADA`, def. 2 000; se trunca con
  marca) y de turnos por conversación.

### 6. Verificación de identidad (Ley 1581 / Ley 1266)
- Posesión: el número de WhatsApp debe ser uno de los teléfonos del cliente (la conversación se
  resuelve así). Conocimiento: número de documento completo (`verificacion.factores =
  ["numero_documento"]`, ampliable).
- Hasta verificar: la IA puede saludar, explicar el motivo genérico ("tenemos información sobre tu
  cuenta"), atender opt-out, derivar y registrar `numero_errado`; **no** puede revelar saldos, ofertas
  personalizadas ni la existencia de la deuda a un tercero.
- El estado de verificación vive en `conversaciones.identidad_verificada` (servidor); al verificarse se
  informa al modelo en el `tool_result`.

### 7. Cumplimiento en todos los canales
Lo de ADR-0012: franjas y frecuencia para todo contacto iniciado por la empresa (incluido
`programar_seguimiento`), respuestas a entrantes según `entrantes.*`, ventana de 24 h para texto
libre, exclusiones por canal, opt-in.

### 8. Habeas Data
- **Minimización**: las herramientas devuelven solo lo necesario (número de obligación enmascarado; sin
  documento, teléfono, email ni dirección). No se envían a Claude datos de otros clientes ni notas
  libres de agentes.
- **Auditoría**: cada herramienta en `acciones_ia` (entrada y resultado **enmascarados**: el documento
  se guarda como `***1234`), y cada acción con efecto también en `auditoria` (`ia.acuerdo_registrado`,
  `ia.venta_registrada`, `ia.opt_out`, `ia.derivacion`, …) con ids y catálogos, sin datos personales.
  Los logs de aplicación nunca incluyen texto de mensajes.
- **Retención**: transcripciones (`mensajes`, `historial_ia`) se conservan
  `RETENCION_TRANSCRIPCIONES_DIAS` (def. 365, a confirmar con legal) y luego se anonimizan
  (texto → `[eliminado]`, se conservan métricas, tipificaciones y acuerdos). Tarea periódica en 2F.
- **Transmisión internacional**: el proveedor del modelo es encargado del tratamiento; requiere
  contrato/DPA, opción de no retención de datos si está disponible y mención en el aviso de privacidad.

### 9. Supervisión, kill switch y presupuesto
Ver ADR-0016 (intervención, toma de conversación, kill switch por campaña y global) y ADR-0014 §6
(presupuesto). Todos se comprueban **antes de cada llamada al modelo y antes de cada herramienta con
efectos**.

## Alternativas consideradas
- **Aprobación humana de cada acuerdo** ("human in the loop"): más segura, pero contradice la decisión
  del usuario; la sustituyen los límites en servidor, la auditoría y la supervisión en vivo.
- **Límites solo en el prompt**: no verificables y vulnerables a injection; rechazado.
- **Exponer al modelo una herramienta genérica de consulta SQL/API**: imposible de acotar; rechazado.
- **Ocultar al modelo los límites y que pruebe a ciegas con `simular_acuerdo_pago`**: más llamadas y
  negociaciones torpes; se le dan los límites y el prompt le indica empezar por la opción más
  favorable para la empresa y ceder gradualmente.

## Consecuencias
- + Cualquier acuerdo o venta registrado por la IA cumple los límites **por construcción**; lo que la
  IA puede hacer mal queda reducido a tono y oportunidad (cubierto por evaluación y supervisión).
- + Auditoría completa por herramienta para requerimientos de la SIC.
- − Configurar reglas por campaña es obligatorio antes de activar la IA (la activación valida que existan).
- − La guarda de montos puede dar falsos positivos (montos escritos en palabras no se detectan;
  números ambiguos); se mide en la evaluación y se ajusta.
