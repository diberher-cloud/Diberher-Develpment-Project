# Bandeja de WhatsApp: guía para agentes y supervisores

Guía de uso de la página **Bandeja de WhatsApp** (`/bandeja`), disponible para los tres roles. Describe lo que
hace el sistema en cada acción. Para la configuración de Twilio y del worker, ver
[`whatsapp-twilio.md`](whatsapp-twilio.md). Las reglas de cumplimiento (franjas, frecuencia, autorización y
baja) están en [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md).

> **Alcance de 2B.** Hasta la subfase 2C, la respuesta de la conversación la escribe siempre una persona. No hay
> agente de IA en el chat. Tampoco se envían adjuntos desde la bandeja (solo se reciben).

Índice: [1. Quién puede hacer qué](#1-quién-puede-hacer-qué) · [2. La pantalla](#2-la-pantalla) ·
[3. Cola de atención](#3-cola-de-atención) · [4. Tomar, asignar y liberar](#4-tomar-asignar-y-liberar) ·
[5. Responder dentro de la ventana](#5-responder-dentro-de-la-ventana) ·
[6. Plantillas fuera de la ventana](#6-plantillas-fuera-de-la-ventana) · [7. Adjuntos](#7-adjuntos) ·
[8. Vincular a un registro de campaña](#8-vincular-a-un-registro-de-campaña) ·
[9. Cerrar con tipificación](#9-cerrar-con-tipificación) · [10. Autorización y baja manual](#10-autorización-y-baja-manual) ·
[11. Conversaciones sin campaña](#11-conversaciones-sin-campaña) · [12. Estados de los mensajes](#12-estados-de-los-mensajes)

---

## 1. Quién puede hacer qué

| Acción | Agente | Supervisor | Administrador |
|---|---|---|---|
| Ver la cola de atención | Solo las campañas a las que está asignado, con WhatsApp activo. Nunca las conversaciones sin campaña. | Todo | Todo |
| Ver conversaciones | Solo las suyas | Todas | Todas |
| **Tomar siguiente** (la conversación de mayor prioridad de su cola) | Sí | No | No |
| **Tomar** una conversación sin dueño | Sí, si es de una campaña asignada | Sí | Sí |
| **Asignar a…** | No | Sí | Sí |
| **Liberar** (devolver a la cola) | Solo la suya | Sí | Sí |
| Responder (texto o plantilla) | Solo como dueño | Solo como dueño | Solo como dueño |
| Vincular un registro de campaña | Solo como dueño y en campañas asignadas | Sí | Sí |
| Cerrar con tipificación | Solo como dueño | Sí, aunque no sea el dueño | Sí, aunque no sea el dueño |
| Registrar autorización | Solo como dueño | Solo como dueño | Solo como dueño |
| Registrar baja (opt-out) manual | Solo como dueño | Solo como dueño | Solo como dueño |
| Ver la ficha del cliente | Solo como dueño, con registro vinculado | Sí | Sí |

Un supervisor o administrador que quiera escribir en una conversación debe tomarla o asignársela a sí mismo
antes. No hay escritura "en nombre de" otro usuario.

---

## 2. La pantalla

La pantalla tiene tres zonas:

- **Columna izquierda, "Cola y conversaciones":**
  - **Cola de atención**, con el botón **Tomar siguiente** (solo agentes) y, en cada elemento, **Tomar**.
    Cada elemento muestra el motivo de entrada, la campaña, el número enmascarado y el tiempo de espera.
  - **Lista de conversaciones**, con filtros de estado (Abiertas, Cerradas), de dueño (Todas, Sin asignar,
    Agente humano, Agente IA) y, para supervisores y administradores, de campaña (incluida "Sin campaña").
- **Zona central:** la conversación abierta. Incluye:
  - Las **alertas** de la conversación (por ejemplo, "El número tiene una exclusión para WhatsApp").
  - El **banner de ventana**: "Ventana de 24 h abierta: quedan HH:MM:SS.", o "Ventana de 24 h cerrada: solo
    plantillas.".
  - El **historial**. Al subir, carga los mensajes anteriores.
  - Las **acciones**: Tomar, Liberar, Asignar a…, Ver ficha del cliente, Vincular registro, Registrar autorización,
    Registrar baja (opt-out) y Cerrar conversación. Solo aparecen las que corresponden al estado y a su rol.
- **Contador del menú:** "Bandeja (n)" cuenta los mensajes sin leer de sus conversaciones.

Al abrir una conversación suya se marca como leída. Los mensajes nuevos llegan en tiempo real si la conexión
está activa. Si se pierde la conexión, la pantalla se recarga al reconectar.

---

## 3. Cola de atención

Una conversación entra en la cola en estos casos:

| Motivo | Cuándo se genera |
|---|---|
| `entrante` | Llega un mensaje de un cliente con registro de campaña reconocido. |
| `sin_campana` | Llega un mensaje y el número no se puede asociar a un registro. Solo lo ven supervisores y administradores. |
| `liberada` | Alguien la libera a la cola. |
| `agente_desconectado` | El agente dueño pasa a desconectado (manual o por falta de conexión). |

Los motivos de la subfase 2C (agente de IA) existen en el catálogo, pero en 2B no se generan.

**Prioridad.** Los elementos con prioridad alta se marcan con "Prioridad alta". En 2B todos los motivos anteriores
tienen prioridad normal.

**Orden.** Por prioridad, después por antigüedad (la más antigua primero).

**Tomar siguiente** (agente). Elige la conversación más prioritaria y antigua de sus campañas asignadas, con WhatsApp
activo. Requisitos:

- Estar en estado **Disponible** (en la consola). Si no, `409 AGENTE_NO_DISPONIBLE`.
- No superar el límite de conversaciones abiertas (`ATENCION_MAX_CONVERSACIONES_AGENTE`, 5 por defecto). Si lo
  supera, `409 CAPACIDAD_MAXIMA`.

Si la cola está vacía, la respuesta es "no hay nada que tomar" (sin error).

**Aviso de espera.** Si un cliente escribe y no hay ningún agente disponible en la campaña, el sistema le envía
automáticamente el aviso de espera (`WHATSAPP_MENSAJE_ESPERA`). No se envía si ya se envió antes en esa conversación.

---

## 4. Tomar, asignar y liberar

- **Tomar** pasa una conversación sin dueño a tu bandeja. Las comprobaciones son las mismas que en "Tomar siguiente":
  campaña asignada, estado disponible y capacidad. Si otro usuario la tomó antes, `409 CONVERSACION_ASIGNADA`.
- **Asignar a…** (supervisor y administrador). Elige un agente activo. Si es agente, debe estar asignado a la
  campaña de la conversación. Una conversación sin campaña solo puede asignarla un supervisor o administrador
  (`422` con el motivo). Asignar no aplica el límite de capacidad.
- **Liberar.** La conversación vuelve a la cola con motivo `liberada` y la pierde el dueño actual.
- **Estado del agente:**
  - **Disponible**: puede tomar conversaciones.
  - **Pausa**: conserva sus conversaciones, pero no puede tomar nuevas.
  - **Desconectado**: sus conversaciones abiertas vuelven automáticamente a la cola con motivo `agente_desconectado`.

---

## 5. Responder dentro de la ventana

La **ventana de 24 h** se abre con cada mensaje del cliente y dura 24 horas. Dentro de ella puede escribir
texto libre en el compositor.

- **Límite:** 4096 caracteres. Un contador se lo indica.
- **Enviar:** Enter envía; Mayús+Enter añade una línea nueva.
- **Margen de seguridad:** a 60 segundos del cierre (`WHATSAPP_MARGEN_VENTANA_SEGUNDOS`), la ventana se considera
  cerrada. El banner lo muestra y el compositor pasa a plantillas.
- **Estado del mensaje:** `pendiente` mientras el worker lo envía, `enviado` cuando Twilio lo acepta,
  `entregado` y `leído` según llegue la confirmación. Ver la sección 12.
- **Reintentos:** si la conexión falla al enviar, la interfaz reutiliza la misma clave de idempotencia, así que
  reenviar el mismo texto no crea un duplicado.

**Por qué no se puede escribir en una conversación.** El compositor se desactiva y muestra el motivo:

| Motivo | Qué significa |
|---|---|
| `VENTANA_CERRADA` | Pasaron más de 24 horas desde el último mensaje del cliente. Use una plantilla. |
| `CLIENTE_OPT_OUT` | El cliente pidió no recibir más mensajes después de su último mensaje. Ya no se puede escribir. |
| `NO_ES_DUENO` | La conversación no es suya. Tómela primero. |
| `CONVERSACION_CERRADA` | La conversación ya está cerrada. Si el cliente vuelve a escribir, se abre una nueva. |

**Respuestas fuera de franja.** Según la política de la campaña, puede estar permitido responder en cualquier hora
al cliente que escribió. Si la política no lo permite:

- Si la próxima franja cae dentro de la ventana, el mensaje queda **retenido**. La conversación muestra
  "N mensajes retenidos hasta la próxima franja permitida." y el mensaje se envía al empezar la franja. La primera
  vez se envía además un aviso automático de fuera de franja.
- Si la próxima franja cae después de que cierre la ventana, el envío se rechaza con `RESPUESTA_FUERA_DE_FRANJA`.
  En ese caso, use una plantilla dentro de la franja.

---

## 6. Plantillas fuera de la ventana

Cuando la ventana está cerrada, el compositor muestra **Enviar una plantilla**. Para elegir plantilla:

1. Seleccione una plantilla de la lista. Solo aparecen las **enviables** y compatibles con la finalidad de la campaña.
2. Revise la **vista previa** (la plantilla con sus variables ya rellenadas).
3. Pulse **Enviar plantilla**.

Las variables se rellenan solo con datos que no son de deuda: el primer nombre del cliente, el nombre de la empresa,
el primer nombre del agente que envía y el producto del registro. Si el registro no tiene **producto** y la plantilla
lo usa, el envío se bloquea con `PLANTILLA_VARIABLE_VACIA`.

**Cuándo una plantilla se bloquea.** El sistema lo comprueba todo antes de enviar y muestra cada motivo. Un bloqueo
por cumplimiento **no es un error**: la plantilla simplemente no sale, y la bandeja muestra "La plantilla no se
envió por cumplimiento." con la próxima ventana permitida.

| Motivo | Qué significa | Qué hacer |
|---|---|---|
| `EXCLUIDO` | El número está en la lista de exclusiones para WhatsApp (por ejemplo, RNE o una baja). | No contacte por este medio. |
| `SIN_AUTORIZACION` | No hay autorización de WhatsApp vigente para la finalidad. | Registre la autorización si el cliente la dio (sección 10). |
| `FESTIVO` | Es festivo y la política no permite contactar. | Espere a la próxima franja (se indica). |
| `DIA_SIN_FRANJA` | Ese día no hay franja (domingo por defecto). | Espere a la próxima franja. |
| `FUERA_DE_FRANJA` | La hora está fuera de la franja del día. | Espere a la próxima franja. |
| `FRECUENCIA_DIA` | Ya hubo demasiados contactos hoy con el cliente. | Espere a mañana. |
| `FRECUENCIA_MEDIOS` | Ya hubo contacto esta semana por otro medio. | Espere a la próxima semana. |

Las reglas de frecuencia se explican en [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md).

**Plantillas desde la ficha de la consola.** Un agente de la consola de voz puede enviar una plantilla desde la
ficha del cliente, con el registro reservado. Si la conversación de ese número está abierta con la ventana abierta,
el sistema pide responder en la conversación (`VENTANA_ABIERTA`). Si la conversación pertenece a otro agente,
`CONVERSACION_ASIGNADA`.

---

## 7. Adjuntos

Los adjuntos del cliente se muestran en la conversación. Se piden al servidor en el momento; el archivo no se
guarda en el sistema.

| Tipo del adjunto | Cómo se muestra |
|---|---|
| Imagen (JPEG, PNG, WebP) | Miniatura. |
| Audio (OGG, MPEG, MP4, AAC, AMR) | Reproductor. |
| PDF | Enlace **Descargar documento PDF**. |
| Otro (vídeo, contacto, Office…) | "Adjunto no soportado (tipo)". |

Un mensaje de un tipo no soportado muestra "Mensaje de un tipo no soportado.". Un error al descargar aparece en
el propio adjunto. Si hay demasiadas descargas a la vez, se pide reintentar.

La bandeja no permite enviar adjuntos. Ver [`fase-2b.md`](arquitectura/fase-2b.md), sección 7.1 (supuesto S-B7).

---

## 8. Vincular a un registro de campaña

Una conversación sin registro (por ejemplo, la de un número que no se pudo asociar) puede vincularse con
**Vincular registro**:

1. Se listan los **registros candidatos**: campañas activas con WhatsApp en las que el cliente tiene ese número.
   No aparecen si el número está marcado como número errado.
2. Elija el registro. La conversación queda vinculada al cliente, a la campaña y al teléfono.
3. Si la conversación la empezó el cliente, se registra su intento de contacto (como cuenta para la frecuencia).
4. Si estaba en la cola como `sin_campana`, sale de ella y entra de nuevo como `entrante`.

Reglas:

- Solo se puede vincular una vez. Si ya tiene registro, `409 CONVERSACION_YA_VINCULADA`.
- El registro debe tener el número de la conversación. Si no, `422 REGISTRO_NO_COINCIDE`.
- Un agente solo ve los candidatos de sus campañas asignadas.
- Con registro vinculado, **Ver ficha del cliente** muestra la ficha de la consola (teléfonos enmascarados).

---

## 9. Cerrar con tipificación

**Cerrar conversación** termina la conversación. Se pueden hacer dos cosas:

- **Con registro vinculado:** la tipificación es obligatoria. Es la misma que en la consola de voz (resultado,
  observación y, según el resultado, promesa de pago, venta o fecha de rellamada). Ver
  [`consola-agente.md`](consola-agente.md). Hay una regla de coherencia:
  - Si el cliente escribió alguna vez, el resultado no puede ser **No contesta**.
  - Si no escribió, el resultado solo puede ser **No contesta**.
  - Si no se cumple, `422 RESULTADO_INCOHERENTE`.
- **Sin registro:** se cierra sin tipificación.

Efectos del cierre:

- Los mensajes salientes que aún no se han enviado (`pendiente` o `retenido`) pasan a `cancelado`.
- La conversación queda cerrada con el motivo `agente` (si cierra un agente) o `supervisor` (si cierra un supervisor
  o administrador).
- Si el cliente vuelve a escribir, se abre una **conversación nueva**.
- Un cierre por inactividad (24 horas sin mensajes y con la ventana vencida) no tipifica nada. Lo hace el sistema
  automáticamente.

---

## 10. Autorización y baja manual

### 10.1 Registrar autorización (opt-in)

Una plantilla **solo se envía si el número tiene una autorización vigente** para la finalidad de la campaña. El
cliente puede dar la autorización en el chat, pero eso no basta para enviarle plantillas en el futuro: la
autorización debe registrarse.

1. Pulse **Registrar autorización**.
2. Elija la finalidad (`venta`, `cobranza` o `todas`).
3. Escriba la **evidencia** (de 5 a 500 caracteres): por ejemplo, «Cliente escribe en el chat que acepta mensajes
   por este medio», o la referencia del soporte.

La autorización queda como `origen=cliente`, con la conversación y el usuario que la registró. Si ya hay una
vigente para esa finalidad, `409 AUTORIZACION_DUPLICADA`. Las autorizaciones también se pueden crear y revocar en
la página **Autorizaciones**, solo para supervisores y administradores.

### 10.2 Registrar baja (opt-out) manual

Cuando el cliente pide la baja con sus propias palabras y el sistema no la reconoce, use **Registrar baja (opt-out)**.
Elija el alcance:

- **Solo WhatsApp:** no se le escribirá por WhatsApp, pero las llamadas de voz siguen permitidas.
- **Todos los canales (también llamadas):** no se le contactará por ningún medio.

Efectos (iguales que la baja automática):

- Se crea una exclusión de tipo `solicitud_titular` para el número.
- Se revocan sus autorizaciones de WhatsApp.
- Se cancelan los mensajes pendientes o retenidos.
- Se envía la confirmación de baja, si la ventana está abierta.
- La conversación se cierra con el motivo `opt_out`. No se crea tipificación.

Un "no me llamen" del cliente, reconocido por el sistema, solo excluye la voz; no cierra la conversación de WhatsApp.

---

## 11. Conversaciones sin campaña

Cuando el número de un mensaje no corresponde a ningún registro (ninguna campaña activa con WhatsApp, o varias
candidatas sin pista), la conversación entra en la cola con el motivo **`sin_campana`**:

- Solo la ven y la atienden **supervisores y administradores**. Los agentes no las ven.
- Pueden tomarla, asignarla, responder y vincular un registro (sección 8). Sin vinculación, solo pueden cerrarla sin
  tipificación.
- Para ver el número completo, la pantalla lo muestra solo a supervisores y administradores.

---

## 12. Estados de los mensajes

| Estado | Dirección | Significado | Qué hacer |
|---|---|---|---|
| Recibido | Cliente | El mensaje llegó y se está procesando. | Nada. |
| Pendiente | Agente | Guardado, esperando al worker para enviarse. | Esperar. Si se alarga, avise al supervisor (el worker puede estar parado). |
| Retenido | Agente | Programado para la próxima franja (se indica la hora). | Esperar. |
| Enviando | Agente | El worker lo está enviando. | Esperar. |
| Enviado | Agente | Twilio lo aceptó. | Nada. |
| Entregado | Agente | Llegó al dispositivo del cliente. | Nada. |
| Leído | Agente | El cliente lo leyó (si su configuración lo permite). | Nada. |
| Fallido | Agente | No se envió o no se entregó. Muestra el motivo. | Ver la tabla de abajo. |
| Cancelado | Agente | No se envió porque la conversación se cerró antes o por una baja. | Nada. |

Motivos de un mensaje **fallido** que pueden verse en pantalla:

| Motivo | Qué hacer |
|---|---|
| "Fuera de la ventana de 24 h." (`63016`) | Use una plantilla. |
| "El número no está disponible en WhatsApp." (`63003`) | Verifique el número con el cliente. |
| "La ventana de 24 h se cerró antes de enviar." | Use una plantilla. |
| "El cliente pidió no recibir mensajes." | No vuelva a escribir por este medio. |
| "El contacto ya no está permitido (exclusión o sin autorización)." | No envíe plantillas. Revise la autorización. |
| "No se pudo confirmar el envío; revise antes de reenviar." | Sección 4.4 de [`whatsapp-twilio.md`](whatsapp-twilio.md#44-envío-como-mucho-una-vez-y-envio_incierto). Compruebe con el cliente antes de reenviar. |

Un error de Twilio sin texto propio aparece como "Error del proveedor (código)."
