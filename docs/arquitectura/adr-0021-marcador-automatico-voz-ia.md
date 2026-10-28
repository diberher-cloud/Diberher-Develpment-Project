# ADR-0021: Marcador automático de campañas de voz atendidas por IA

- Estado: aceptado (implementación en subfase 2D)
- Fecha: 2026-10-28
- Modifica: ADR-0009 (el marcador deja de esperar a la Fase 3 para campañas con IA; preview y
  progresivo para humanos siguen en Fase 3, ahora opcionales)
- Depende de: ADR-0012 (cumplimiento), ADR-0013 (cola de trabajos), ADR-0017 (reservas y bloqueos),
  ADR-0020 (agente IA de voz)

## Contexto
Con la IA atendiendo las llamadas, lanzar una saliente ya no exige un agente humano disponible: el
límite pasa a ser el **coste**, la **concurrencia** que admiten Twilio y nuestro servicio de voz, y la
capacidad de los **humanos de respaldo** para absorber traspasos. No hay abandono (siempre "contesta"
la IA), pero sí riesgo de duplicar llamadas al mismo cliente, de violar franjas, festivos, frecuencia
o exclusiones a escala, y de gastar sin control.

Twilio: por defecto 1 llamada por segundo (CPS) por cuenta; ampliable en consola (hasta ~30 de forma
autoservicio según la documentación reciente, a confirmar); las peticiones por encima del CPS se
encolan en Twilio, no se rechazan.

## Decisión
1. **Modo de voz por campaña**: `campanas.voz_modo` ∈ {`humano` (2A, por defecto), `ia`}. En `ia` los
   registros los marca el marcador y los atiende la IA; **no aparecen en la lista de trabajo de la
   consola**, salvo los marcados `requiere_humano=true` (devoluciones de llamada, ADR-0020 §9). Los
   agentes asignados a la campaña reciben los traspasos.
2. **Activación**: `configuracion_ia_campana.voz_activa` (exige reglas válidas, evaluación offline de
   voz en verde, `voz_max_concurrentes > 0` y al menos un agente humano asignado). Es también el
   **kill switch por campaña** de voz.
3. **Tick del marcador**: trabajo periódico `marcador_ia.tick` (cola `trabajos`, ADR-0013) cada
   `MARCADOR_IA_INTERVALO_SEGUNDOS` (2). Un solo tick a la vez en todo el sistema: bloquea la fila
   `configuracion_global('marcador_ia')` con `FOR UPDATE NOWAIT` (si está tomada, termina).
   - Capacidad global = `min(MARCADOR_IA_MAX_CONCURRENTES_GLOBAL, configuracion_global
     .voz_max_concurrentes)` − llamadas IA activas (`llamadas.atendida_por='ia'` en estado no terminal).
   - Por campaña activa en modo `ia` con `voz_activa` y sin kill switch global: capacidad =
     `voz_max_concurrentes` − activas de la campaña; además, si `voz_limitar_por_humanos=true`,
     ≤ `voz_llamadas_por_humano` × agentes humanos asignados y conectados (protege la cola de traspasos).
   - Ritmo: como mucho `MARCADOR_IA_CPS` (por defecto 1, ≤ CPS contratado en Twilio) llamadas nuevas
     por segundo en todo el sistema; el tick reparte el cupo entre campañas por turno rotatorio.
   - Presupuesto: no se marca en una campaña con el presupuesto mensual agotado (y se activa su kill
     switch, ADR-0014 §6).
   - No se marca si quedan menos de `MARCADOR_IA_MARGEN_FIN_FRANJA_MINUTOS` (10) para el fin de la
     franja del día (la conversación no debe desbordarla).
4. **Selección y reserva** (anti-duplicados, mismo orden de bloqueos que 2A/2B):
   1. Candidatos sin bloqueo: registros `pendiente` (o `en_gestion` con reserva caducada y sin llamada
      activa) de la campaña, `intentos < max_intentos`, `proximo_intento_en <= ahora` o nulo,
      `requiere_humano=false`; orden: rellamadas programadas vencidas primero, luego
      `COALESCE(proximo_intento_en, creado_en)`, `id`. Límite = capacidad × 3.
   2. Para cada candidato, hasta cubrir la capacidad: `clientes` `FOR UPDATE SKIP LOCKED` (si otro
      proceso tiene al cliente —p. ej. un humano llamándolo en otra campaña—, se salta) → revalidar y
      reservar el registro con un **UPDATE condicional** (`estado`, reserva libre, sin llamada activa,
      `intentos`) que pone `estado='en_gestion'`, `reserva_origen='marcador'`, `reservado_por=NULL`,
      `reservado_hasta = ahora + MARCADOR_IA_RESERVA_MINUTOS`.
   3. Con el cliente bloqueado: **cumplimiento autoritativo** (el mismo `evaluar_contacto` del TwiML
      saliente de 2A): campaña activa, exclusiones del teléfono para el tipo de campaña y canal `voz`,
      franja, festivo y **frecuencia omnicanal**. Teléfono: el de mayor prioridad no excluido.
   4. Permitido → en la misma transacción: `intentos_contacto` (`canal=voz`, `iniciado_por=empresa`,
      `politica_version`), `llamadas` (`atendida_por='ia'`, `usuario_id=NULL`, `estado=iniciando`,
      `call_sid` provisional `"pendiente:<uuid>"`), `llamadas_ia`; commit. Bloqueado → libera la
      reserva y deja `proximo_intento_en` en la próxima ventana permitida (horario y frecuencia) sin
      crear llamada; se cuenta en métricas por motivo.
   5. Fuera de la transacción: `ProveedorTelefonia.crear_llamada_saliente(destino, origen,
      url_twiml, callback_estado, amd, grabar, timeout, time_limit)` (ADR-0003). Éxito → guarda el
      `CallSid`. Error definitivo → llamada `fallida`, se **borra** el intento de contacto (no hubo
      contacto) y se libera la reserva con reintento. Error incierto (red tras enviar) → se deja
      `iniciando`; los webhooks (que llevan `llamada_id` en la URL) la reconcilian y un barrido marca
      `fallida` las que sigan sin `CallSid` tras 2 min.
5. **Correcciones necesarias en 2A** para que la reserva sin usuario sea segura: `reserva_vigente()` y
   el UPDATE de `tomar` deben tratar como ocupada una reserva vigente con `reservado_por IS NULL`
   (hoy `reservado_por IS NULL` se considera libre), y `_llamada_pendiente_de_otro` debe usar
   `IS DISTINCT FROM` (hoy `usuario_id != :yo` ignora las llamadas con `usuario_id` nulo).
6. **Reintentos** por resultado técnico (configuración por campaña `voz_reintentos` JSON, validado):
   `no_contesta`, `ocupado`, `buzon`, `fallida`, `colgo_sin_verificar` → minutos de espera
   (por defecto 120, 30, 240, 60, 240), siempre llevados a la próxima ventana permitida y contando
   `intentos` contra `max_intentos`. Se reutiliza `consola/efectos.py` con el intervalo por motivo.
   Rellamadas acordadas por la IA (`programar_seguimiento`) usan su fecha y vuelven a pasar por
   cumplimiento al marcarse.
7. **Kill switch**: por campaña (`voz_activa=false`) y global (`configuracion_global.ia_activa`,
   `IA_HABILITADA`). Efecto inmediato en el siguiente tick (no se marca nada nuevo). Llamadas en curso:
   según `voz_kill_switch_en_curso` ∈ {`terminar_turno` (por defecto: la sesión, antes de su siguiente
   llamada al modelo, ofrece traspaso a humano o se despide con texto fijo), `colgar`}. Pausa del
   marcador sin apagar la IA de entrantes: `voz_marcador_pausado`.
8. **Observabilidad**: evento WS `marcador.estado` (por campaña: activas, marcadas/min, bloqueadas por
   motivo, traspasos en espera) y `campana.metricas`; alerta `ia.alerta` si la tasa de fallos de
   creación o de sesiones huérfanas supera el umbral.

## Alternativas consideradas
- **Predictivo / sin límite de concurrencia**: no hay abandono con IA, pero dispara coste y traspasos
  sin humanos para atenderlos; la concurrencia explícita es más segura.
- **Encolar llamadas en Twilio (CPS) sin ritmo propio**: perderíamos el control del momento real de
  marcación frente a franja y frecuencia (el cumplimiento debe evaluarse justo antes de marcar).
- **Reserva con un usuario técnico "IA"**: violaría "la IA no es un usuario" (README §1) y mezclaría
  métricas de agentes; se usa `reserva_origen='marcador'`.
- **Bloquear `campana_clientes` antes que `clientes`**: invertiría el orden global de 2A (riesgo de
  interbloqueo con el TwiML saliente humano); se bloquea primero el cliente con `SKIP LOCKED`.

## Consecuencias
- + Escala sin humanos en línea y sin abandono; cumplimiento y anti-duplicado con los mismos
  mecanismos auditados de 2A.
- + Coste acotado por concurrencia, ritmo y presupuesto.
- − Se tocan servicios de 2A (reserva y consulta de llamada pendiente) con tests de regresión.
- − Un tick global serializado limita el ritmo máximo (suficiente para decenas de CPS).
