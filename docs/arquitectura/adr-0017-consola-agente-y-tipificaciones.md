# ADR-0017: Consola del agente humano, reserva de registros, tipificaciones y tiempo real en 2A

- Estado: aceptado (implementación en subfase 2A)
- Fecha: 2026-10-23
- Modifica: ADR-0004 (el WebSocket se adelanta de la Fase 3 a la 2A), ADR-0008 §3 (asignación agente↔campaña)

## Contexto
La subfase 2A entrega la consola del agente humano con llamada PSTN preview/manual por Twilio
(ADR-0003) y la tipificación del resultado. El marcador automático (cola y worker) sigue en la Fase 3.
Hay que evitar que dos agentes llamen al mismo cliente, garantizar que cada llamada termine tipificada
y mostrar en vivo el estado de agentes y llamadas.

## Decisión
1. **Asignación agente↔campaña** (`campana_agentes`): solo agentes asignados a una campaña `activa`
   ven sus registros en la consola. La gestionan administrador y supervisor.
2. **Reserva de registro** (preview manual): el agente elige un registro de su lista de trabajo y lo
   **toma** (`campana_clientes.estado=en_gestion`, `reservado_por`, `reservado_hasta = ahora +
   CONSOLA_RESERVA_MINUTOS`). Otro agente recibe `409 REGISTRO_RESERVADO`. Una reserva caducada se
   considera libre. La ficha completa solo se ve con reserva propia (minimización, auditoría
   `consola.ficha_ver`). La reserva se renueva al llamar y se libera al tipificar o soltar. Un registro
   reservado por agente a la vez.
3. **Estado del agente** (máquina de estados en servidor, tabla `estados_agente` + historial):
   `desconectado`, `disponible`, `pausa`, `en_llamada`, `tipificando`.
   - Manuales: entre `desconectado`, `disponible` y `pausa` en cualquier sentido (la pausa exige
     motivo); prohibidas desde `en_llamada` y `tipificando`.
   - Automáticos: TwiML saliente aceptado → `en_llamada`; fin de la llamada → `tipificando`;
     tipificación registrada → `disponible`.
   - Solo se puede llamar en `disponible`.
   - Desconexión del WebSocket: si en `CONSOLA_DESCONEXION_SEGUNDOS` (60 s) no hay otro socket del
     agente y estaba `disponible`/`pausa` → `desconectado`.
   - Tabla completa de transiciones en `fase-2.md` §4.3.
4. **Tipificación obligatoria**: cada llamada saliente realizada genera exactamente una tipificación
   (`UNIQUE(llamada_id)`); mientras el agente tenga una llamada terminada sin tipificar, el TwiML
   saliente rechaza nuevas llamadas (`TIPIFICACION_PENDIENTE`). Catálogo único (ADR-0011):
   `contactado`, `no_contesta`, `numero_errado`, `promesa_pago`, `venta`, `rechazo`,
   `volver_a_llamar`. Efectos sobre el registro y el teléfono en `fase-2.md` §4.6.
5. **Número errado** crea exclusión `motivo=numero_errado`, `aplica_a=todas` para ese teléfono
   (cubre todos los canales: al añadirse la columna `canal` en 2B, las filas existentes quedan con
   `canal=todos`).
6. **Volver a llamar** valida la fecha/hora contra el motor (franja + festivo) y la deja en
   `proximo_intento_en`; si no es válida → `422` con la próxima ventana sugerida.
7. **Frecuencia evaluada desde 2A** (ADR-0012), con `intentos_contacto` registrado al aceptar el TwiML
   saliente y `contacto_directo` actualizado al tipificar.
8. **Tiempo real en 2A** (adelanta ADR-0004): WebSocket `GET /api/v1/ws?token=…` con bus
   `BusEventos` (interfaz) → `BusPostgres` (`pg_notify` dentro de la transacción + `LISTEN`) en
   PostgreSQL y `BusMemoria` (despacho en `after_commit`) en SQLite/tests. Eventos de 2A:
   `agente.estado`, `llamada.estado`, `consola.registro`.
9. **Softphone con doble falso**: el token indica el proveedor (`twilio`|`falso`); el frontend usa
   `SoftphoneTwilio` (`@twilio/voice-sdk`) o `SoftphoneFalso`, que llama a endpoints de **simulación**
   (solo `ENTORNO != produccion` y `TELEFONIA_PROVEEDOR=falso`) que ejecutan **la misma lógica** que los
   webhooks de Twilio. Así la consola completa se prueba sin credenciales.
10. **Aviso de grabación al cliente**: se reproduce en la pierna del cliente con
    `<Number url="…/twiml/aviso-grabacion">` (TwiML ejecutado al contestar, antes de puentear), texto
    configurable. Grabación `record-from-answer-dual` si `TELEFONIA_GRABAR=true`.
11. **Minimización en consola**: el agente ve los teléfonos enmascarados; el navegador solo envía ids
    (`campana_cliente_id`, `telefono_id`) y el servidor resuelve el número.

## Alternativas consideradas
- **Lista de trabajo sin reserva** (cualquiera llama a cualquiera): duplicaría llamadas y rompería la
  frecuencia; rechazado.
- **Asignación automática del siguiente registro** (preview del marcador): es la Fase 3; en 2A el
  agente elige, lo que permite operar campañas pequeñas sin marcador.
- **Polling en lugar de WebSocket en 2A**: suficiente para la consola de voz, pero la bandeja de chat
  (2B) y la supervisión de IA (2C) lo necesitan; se implementa una vez desde 2A.

## Consecuencias
- + Consola usable de punta a punta sin Twilio (falso) y con Twilio real cambiando solo variables.
- + El historial de estados de agente alimenta los reportes de la Fase 4 (ocupación, AHT).
- − Cada instancia de la API mantiene una conexión `LISTEN` dedicada.
