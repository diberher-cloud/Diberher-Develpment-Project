# ADR-0016: Cola de traspaso a humano, intervención del supervisor y kill switch

- Estado: aceptado (2B: bandeja humana; 2C: traspaso desde IA en chat, intervención y kill switch;
  2D: traspaso de llamadas de voz atendidas por IA)
- Fecha: 2026-10-23
- Actualizado: 2026-10-28 (revisión de alcance "IA en voz", §8; decisión del usuario: hay agentes
  humanos de respaldo para los traspasos de chat y de voz)

## Contexto
Con autonomía total de la IA, la supervisión humana es la red de seguridad: el cliente puede pedir un
humano en cualquier momento; la IA debe poder derivar casos que no sabe o no puede resolver; los
supervisores deben ver conversaciones y llamadas en vivo, intervenir y apagar la IA de inmediato. El
usuario confirmó (2026-10-28) que **habrá agentes humanos de respaldo** en la consola de 2A para
recibir los traspasos.

## Decisión
1. **Estados de atención** de una conversación: `atendida_por` ∈ {`ia`, `humano`, `sin_asignar`}.
   - `ia`: el worker ejecuta turnos de IA con cada mensaje entrante.
   - `sin_asignar`: en cola humana, nadie responde aún (la IA ya no responde).
   - `humano`: asignada a `usuario_asignado_id` (agente o supervisor).
2. **Cola de atención** `cola_atencion` (una fila por traspaso): `conversacion_id`, `motivo`
   (catálogo: `solicitud_cliente`, `ia_no_resuelve`, `identidad_bloqueada`, `ia_rechazo`,
   `ia_max_tokens`, `ia_iteraciones`, `ia_monto_no_respaldado`, `presupuesto_excedido`,
   `ia_desactivada`, `sin_campana`, `queja`, `supervisor`), `resumen` (de la IA, ≤ 500),
   `prioridad` (1 alta … 3), `estado` (`pendiente`, `asignada`, `cerrada`), `asignada_a`,
   `creado_en`, `asignada_en`, `cerrada_en`.
   - Toma: `POST /atencion/tomar-siguiente` (agente con la campaña asignada y habilidad WhatsApp) o
     asignación directa por supervisor. En PostgreSQL con `FOR UPDATE SKIP LOCKED`.
   - Orden: prioridad, antigüedad. SLA visible (tiempo en cola).
   - **Fuera de horario de agentes** (sin agentes `disponible`): mensaje fijo configurable al cliente
     ("Un asesor te escribirá en el horario de atención…") y la conversación queda en cola. El primer
     mensaje humano posterior es respuesta (si la ventana de 24 h sigue abierta) o plantilla.
3. **Intervención del supervisor** sin tomar la conversación: `POST /conversaciones/{id}/instrucciones`
   con texto (≤ 1 000). Se guarda y se añade al historial de Claude como
   `{"role": "system", "content": "Instrucción del supervisor: …"}` en el siguiente turno (no invalida la
   caché ni puede ser falsificado por el cliente). Auditado.
4. **Tomar la conversación** (`POST /conversaciones/{id}/tomar`): `atendida_por=humano` inmediato; si
   hay un turno de IA en curso, el bucle lo detecta antes de la siguiente llamada o herramienta con
   efectos y se detiene sin enviar. **Devolver a la IA** (`POST /conversaciones/{id}/devolver-ia`): se
   añade al historial un `system` con la transcripción de lo intercambiado durante la intervención
   humana (los mensajes humanos no se insertan como turnos `assistant` fabricados).
5. **Kill switch**:
   - Por campaña: `configuracion_ia_campana.activa=false` (chat) y `voz_activa=false` (voz)
     (supervisor/admin). Chat: las conversaciones `ia` abiertas pasan a `sin_asignar` (motivo
     `ia_desactivada`). Voz: el marcador deja de marcar en el siguiente tick y las llamadas en curso
     siguen `voz_kill_switch_en_curso` (ADR-0021 §7: traspaso o despedida fija antes de la siguiente
     llamada al modelo).
   - Global: `IA_HABILITADA` (entorno) y bandera en BD `configuracion_global.ia_activa` (solo admin)
     con efecto inmediato en ambos canales.
   - Automático por presupuesto (ADR-0014 §6) y por tasa de errores (p. ej. > N fallos no transitorios
     en 10 min → desactivar campaña y alertar).
6. **Panel de supervisión** (2C chat; 2D voz): lista de conversaciones y **llamadas IA activas** con
   filtros (campaña, atendida_por, motivo de cola, con acuerdo), vista en vivo de mensajes y de la
   transcripción de la llamada (WebSocket con ids + lectura por REST), acciones (instruir, tomar,
   devolver, cerrar; en voz: instruir, forzar traspaso, colgar), ficha de acciones de la IA (de
   `acciones_ia`), métricas por campaña y canal: interacciones, tasa de verificación, acuerdos y ventas
   (número y monto), derivaciones por motivo, opt-outs, coste y tokens, tiempo de respuesta (chat) y
   latencia de turno (voz), traspasos de voz en espera y devoluciones pendientes.
7. Eventos de tiempo real nuevos: `conversacion.mensaje`, `conversacion.estado`, `atencion.cola`,
   `ia.alerta` (2C); `llamada_ia.estado`, `llamada_ia.turno`, `traspaso_voz.estado`,
   `marcador.estado` (2D). Solo ids y catálogos, nunca texto.

### 8. Traspaso de llamadas de voz (2D, ADR-0020 §9)
- **Destino**: un agente humano asignado a la campaña y `disponible` en la consola de 2A; se le
  transfiere la llamada en vivo (`<Dial><Client>`) con la ficha, el resumen de la IA y la
  transcripción visibles antes de contestar. No hay "devolver a la IA" en voz.
- **Tabla** `traspasos_llamada` (motivo del mismo catálogo que `cola_atencion`, resumen ≤ 500,
  prioridad, estado `pendiente|en_espera|timbrando|conectado|devolucion|abandonado|cancelado`,
  agente asignado, intentos de asignación y marcas de tiempo). Asignación con `estados_agente`
  `FOR UPDATE SKIP LOCKED` en orden de más tiempo disponible.
- **Sin humano disponible**: espera corta con música y reintento cada 10 s hasta
  `VOZ_TRASPASO_ESPERA_MAX_SEGUNDOS` (120); al vencer, o fuera de `VOZ_HORARIO_HUMANOS`, **devolución
  de llamada**: el registro queda `requiere_humano=true` con `proximo_intento_en` en la próxima ventana
  permitida y aparece con prioridad en la lista de trabajo de la consola (no lo marca la IA). Si el
  cliente cuelga en espera → `abandonado` (también genera devolución si `VOZ_DEVOLVER_ABANDONADOS=true`).
- **Intervención en voz**: `POST /llamadas/{id}/instrucciones` (mismo mecanismo `system`, se aplica en
  el siguiente turno de la sesión), `POST /llamadas/{id}/traspasar` (supervisor fuerza traspaso,
  motivo `supervisor`) y `POST /llamadas/{id}/colgar` (despedida fija y fin). Escucha en vivo de la
  llamada: Fase 5 (conferencias).
- **Capacidad**: el marcador limita la concurrencia de llamadas IA por campaña en función de los
  humanos conectados si `voz_limitar_por_humanos=true` (ADR-0021 §3), para que la cola de traspasos
  no crezca sin control.

## Alternativas consideradas
- **Que la IA siga respondiendo mientras espera humano**: confunde al cliente y puede contradecir al
  asesor; rechazado (solo el mensaje fijo de espera). En voz, igual: espera con música, no IA.
- **Insertar los mensajes humanos como turnos `assistant`**: falsifica la autoría ante el modelo y
  complica los bloques de *thinking*; se usa un `system` con la transcripción.
- **Cola de voz con `<Enqueue>`/TaskRouter**: más capacidades (posición en cola, prioridades), pero
  acopla a Twilio TaskRouter (ADR-0003); el bucle de espera con `<Redirect>` y la asignación en
  nuestra BD bastan a esta escala.
- **Espera larga en línea sin devolución**: coste por minuto y mala experiencia; se acota la espera y
  se ofrece devolución.

## Consecuencias
- + El cliente siempre puede llegar a un humano (en vivo o por devolución); el supervisor puede parar
  todo en un clic.
- − Requiere agentes humanos asignados a las campañas con IA (chat y voz) y horario de respaldo
  definido; la consola necesita aceptar llamadas entrantes (`incoming_allow=True`) desde 2D.
