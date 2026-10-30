# ADR-0022: Núcleo del agente IA en 2C — turnos, historial, herramientas y gestión única

- Estado: aceptado (implementación en subfase 2C; el núcleo lo reutiliza la voz en 2D)
- Fecha: 2026-10-30
- Concreta: ADR-0014 (arquitectura con Claude), ADR-0015 (autonomía y salvaguardas), ADR-0016
  (traspaso y supervisión), ADR-0018 (evaluación), ADR-0019 (bandeja de 2B). Detalle de contrato en
  [`fase-2c.md`](fase-2c.md).

## Contexto
Los ADR 0014-0016 fijaron la arquitectura del agente IA a nivel medio. Al bajar a contrato aparecieron
problemas que esos ADR no resolvían:
1. La cola `trabajos` de 2B libera la `clave_unica` al tomar un trabajo: un mensaje que llega durante un
   turno encola otro, y dos workers podrían ejecutar dos turnos de la misma conversación a la vez. No
   se puede mantener un `FOR UPDATE` durante la llamada al modelo (segundos).
2. Los mensajes `role: "system"` intermedios solo son válidos tras un `user` y si son el último elemento
   o les sigue un `assistant` (documentación del SDK). Un turno abortado deja secuencias `user, system`
   a las que luego se añadiría otro `user`: petición inválida. Y una corrección tras un `assistant` no
   puede ser un `system` directo.
3. 2B impone una tipificación por conversación (`UNIQUE tipificaciones.conversacion_id`), mientras el
   catálogo de ADR-0015 tenía varias herramientas que tipifican (`registrar_acuerdo_pago`,
   `registrar_venta`, `registrar_resultado`, `programar_seguimiento`).
4. El modelo puede "fingir" una aceptación o registrar un plan distinto del que vio el cliente.
5. Las herramientas terminales (derivar, cerrar) cambian el dueño, pero el modelo debe poder despedirse
   después; y el cierre de 2B cancela los mensajes pendientes.
6. Las ventas con descuento producen importes que el modelo calcularía por su cuenta, y la guarda de
   montos los bloquearía.

## Decisión
1. **Arrendamiento de turno** en una tabla `bloqueos_turno_ia(clave PK, trabajador, expira_en)`,
   adquirido con la conversación bloqueada (INSERT o UPDATE condicional si caducó), renovado antes de
   cada llamada al modelo y de cada herramienta y liberado al terminar. Un segundo trabajo que lo
   encuentra ocupado se reprograma (`ReprogramarTrabajo`, sin consumir intento). La duración máxima de
   un turno es menor que el bloqueo del worker. *Debounce*: `clave_unica = turno_ia:<id>` +
   `disponible_desde` pospuesto hasta un máximo.
2. **Transacciones cortas**: inicio de turno, registro de cada respuesta, cada herramienta y el cierre
   del turno son transacciones separadas; nunca hay una abierta durante `crear_mensaje`. Antes de cada
   llamada y cada herramienta con efectos se revalidan dueño, kill switch, presupuesto y arrendamiento.
3. **Historial append-only con reconstrucción pura**: `historial_ia` nunca se edita; una función pura
   construye `messages` emitiendo tal cual los segmentos cerrados por un `assistant` y normalizando solo
   la cola abierta (todos los `user` fusionados con los `tool_result` primero; todos los `system`
   después). Las correcciones de las guardas se añaden como `user` con un marcador
   `<control_servidor/>` (no falsificable: el texto del cliente se escapa) seguido del `system` con la
   corrección. Si el modelo no admite `system` intermedio (lista configurable), los `system` se
   convierten en bloques `<aviso_servidor>` del `user` anterior.
4. **Reparación** de `tool_use` sin resultado al iniciar un turno: se usa el resultado guardado en
   `acciones_ia` (idempotencia por `tool_use_id`) o un error `INTERRUMPIDO`; nunca se ejecuta una
   herramienta pendiente al reparar.
5. **Una gestión por conversación**: la primera herramienta de resultado crea la tipificación; las
   demás devuelven `GESTION_YA_REGISTRADA`. Catálogo final: `registrar_resultado` se sustituye por
   `cerrar_conversacion(resultado ∈ contactado|rechazo|numero_errado|ninguno, resumen)`;
   `programar_seguimiento` tipifica `volver_a_llamar`; se añade `cotizar_venta` (sin efectos), simétrica
   de `simular_acuerdo_pago`; `registrar_autorizacion_whatsapp` toma la finalidad de la campaña. El
   conjunto de herramientas depende de **canal y tipo de campaña** (chat-cobranza, chat-venta).
6. **Acuerdos y ventas en dos pasos verificados por el servidor**: `registrar_*` exige una
   `simular_acuerdo_pago`/`cotizar_venta` previa no errónea con valores idénticos en la misma
   conversación, revalida con las reglas actuales y exige que la cita aparezca en un mensaje del
   cliente **posterior** a esa simulación. Una promesa vigente del registro impide otra.
7. **Despedida tras acciones terminales**: la derivación es inmediata y la despedida del modelo se envía
   solo si la fila de cola creada sigue pendiente; el cierre por la IA queda pendiente y se aplica al
   final del turno, después de crear la despedida, con `motivo_cierre='sistema'`; el trabajo de envío
   entrega los mensajes `ia`/`sistema` creados antes de un cierre `sistema`. Tras un opt-out no se
   envía texto del modelo.
8. **Guardas de salida en orden**: documento del cliente, URL no permitida, longitud, cifras antes de
   verificar, cifras no respaldadas por resultados de herramientas (montos y porcentajes, tolerancia de
   1 peso / 0,01 %). Una corrección por turno; el segundo fallo deriva.

## Alternativas consideradas
- **Advisory locks de PostgreSQL** para el turno: no portables a SQLite (tests) y ligados a la conexión,
  que SQLAlchemy devuelve al pool entre transacciones. Rechazada.
- **Mantener `FOR UPDATE` durante el turno**: bloquearía webhooks, bandeja y supervisión durante
  segundos y arriesga interbloqueos con las herramientas. Rechazada.
- **Borrar o reescribir filas del historial** para "arreglar" turnos abortados: rompe la caché y
  invalida los bloques de *thinking* (que dependen del historial previo). Rechazada.
- **Varias gestiones por conversación**: exigiría alterar la UNIQUE de 2B y complicaría la coherencia
  de `intentos_contacto` y de la frecuencia. Rechazada; una conversación nueva permite otra gestión.
- **Aceptar la cita sin comprobar el orden temporal**: el modelo podría registrar un plan que el cliente
  aceptó antes de ver sus condiciones exactas. Rechazada.
- **Un único catálogo de herramientas para todos los tipos de campaña** (con
  `HERRAMIENTA_NO_DISPONIBLE`): un prefijo de caché menos, pero el modelo vería herramientas que no
  puede usar. Rechazada.
- **Cerrar inmediatamente y exceptuar la despedida en el cierre de 2B**: igual de complejo y con riesgo
  de cancelar la constancia; se aplaza el cierre al final del turno.

## Consecuencias
- + Un turno por conversación garantizado en PostgreSQL y SQLite, con recuperación ante caídas.
- + Las peticiones a la API son siempre válidas y el prefijo cacheado no cambia entre turnos.
- + Ningún acuerdo o venta se registra sin un plan calculado por el servidor y una aceptación posterior
  verificable del cliente.
- + El núcleo (contexto, canal, historial, herramientas, guardas) es independiente de WhatsApp; 2D
  añade `CanalVoz` sin tocarlo.
- − Una tabla más (`bloqueos_turno_ia`) y reprogramaciones de trabajos visibles en la cola.
- − La negociación necesita una ronda más (simular → proponer → aceptar → registrar).
- − Cambios acotados en 2B: `decidir_dueno_inicial`, enrutado a `ia.turno`, revalidación de mensajes
  `ia`, entrega de despedidas tras un cierre `sistema` y cierre humano de conversaciones ya tipificadas.
