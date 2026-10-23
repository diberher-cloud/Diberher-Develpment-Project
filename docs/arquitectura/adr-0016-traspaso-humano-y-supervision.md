# ADR-0016: Cola de traspaso a humano, intervención del supervisor y kill switch

- Estado: aceptado (2B: bandeja humana; 2C: traspaso desde IA, intervención y kill switch)
- Fecha: 2026-10-23

## Contexto
Con autonomía total de la IA, la supervisión humana es la red de seguridad: el cliente puede pedir un
humano en cualquier momento; la IA debe poder derivar casos que no sabe o no puede resolver; los
supervisores deben ver conversaciones en vivo, intervenir y apagar la IA de inmediato.

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
   - Por campaña: `configuracion_ia_campana.activa=false` (supervisor/admin). Las conversaciones `ia`
     abiertas de la campaña pasan a `sin_asignar` (motivo `ia_desactivada`) y los nuevos mensajes van a
     la cola humana.
   - Global: `IA_HABILITADA` (entorno) y bandera en BD `configuracion_global.ia_activa` (solo admin)
     con efecto inmediato.
   - Automático por presupuesto (ADR-0014 §6) y por tasa de errores (p. ej. > N fallos no transitorios
     en 10 min → desactivar campaña y alertar).
6. **Panel de supervisión** (2C): lista de conversaciones activas con filtros (campaña, atendida_por,
   motivo de cola, con acuerdo), vista en vivo de mensajes (WebSocket), acciones (instruir, tomar,
   devolver, cerrar), ficha de acciones de la IA (de `acciones_ia`), métricas por campaña/agente IA:
   conversaciones, tasa de verificación, acuerdos y ventas (número y monto), derivaciones por motivo,
   opt-outs, coste y tokens, tiempo medio de respuesta.
7. Eventos de tiempo real nuevos: `conversacion.mensaje`, `conversacion.estado`, `atencion.cola`,
   `ia.alerta`.

## Alternativas consideradas
- **Que la IA siga respondiendo mientras espera humano**: confunde al cliente y puede contradecir al
  asesor; rechazado (solo el mensaje fijo de espera).
- **Insertar los mensajes humanos como turnos `assistant`**: falsifica la autoría ante el modelo y
  complica los bloques de *thinking*; se usa un `system` con la transcripción.

## Consecuencias
- + El cliente siempre puede llegar a un humano; el supervisor puede parar todo en un clic.
- − Requiere agentes humanos con habilidad WhatsApp y asignación a campañas.
