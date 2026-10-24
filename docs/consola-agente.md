# Consola del agente y supervisión (subfase 2A)

Guía de uso para agentes, supervisores y administradores: estados, lista de trabajo, reservas, ficha,
llamadas, tipificaciones y supervisión en vivo. Incluye el procedimiento de soporte `liberar-gestion`.

Diseño: [ADR-0017](arquitectura/adr-0017-consola-agente-y-tipificaciones.md) y
[`fase-2.md`](arquitectura/fase-2.md) §4.3 a §4.7. Voz y Twilio: [`telefonia-twilio.md`](telefonia-twilio.md).
Frecuencia y horario: [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md).

> **Alcance de 2A.** Llamadas salientes manuales (preview manual) con reserva de registro. No hay marcador
> automático, reintentos automáticos, transferencias ni llamadas entrantes. WhatsApp y el agente de IA llegan
> en las subfases 2B a 2E.

Índice: [Quién usa la consola](#1-quién-usa-la-consola) · [Estados](#2-estados-del-agente) ·
[Lista de trabajo](#3-lista-de-trabajo) · [Tomar, soltar y reservas](#4-tomar-soltar-y-reservas) ·
[Ficha](#5-ficha-del-cliente) · [Llamar](#6-llamar) · [Tipificaciones](#7-tipificaciones-y-sus-efectos) ·
[Supervisión](#8-supervisión-en-vivo-y-tipificaciones-de-campaña) · [Errores](#9-códigos-de-error-de-la-consola) ·
[Procedimiento de soporte](#10-procedimiento-de-soporte-liberar-gestion)

---

## 1. Quién usa la consola

- **Agente** (`/consola`): solo ve campañas **asignadas** y en estado `activa`. Solo usuarios con rol `agente`
  pueden asignarse a una campaña y usar la consola (S-A6).
- **Administrador y supervisor**: asignan agentes a una campaña en la pestaña **Agentes** del detalle de la
  campaña (`PUT /api/v1/campanas/{id}/agentes` con `{"usuario_ids": [5, 6]}`, que reemplaza el conjunto). Ven
  la pestaña **Tipificaciones** y la página **Supervisión** (`/supervision/agentes`).
- Un usuario de rol agente se desactiva con `PATCH /api/v1/usuarios/{id}` (`{"activo": false}`). Si tiene
  gestión pendiente, la API responde `409 USUARIO_CON_GESTION_PENDIENTE`. Hay que resolverla antes (ver
  [sección 10](#10-procedimiento-de-soporte-liberar-gestion)).

Requisitos previos de una llamada: campaña `activa` con clientes, agente asignado, registro reservado por
él, estado `disponible`, teléfono llamable y cumplimiento permitido. El detalle está en las secciones 3 a 6.

---

## 2. Estados del agente

| Estado | Significado | Quién lo cambia |
|---|---|---|
| `desconectado` | No está trabajando. Es el estado de un usuario sin fila de estado. | Manual, o automático tras 60 s sin WebSocket. |
| `disponible` | Puede tomar registros y llamar. | Manual, o automático al tipificar. |
| `pausa` | Pausa con motivo: `descanso`, `almuerzo`, `capacitacion`, `reunion` u `otro`. | Manual. |
| `en_llamada` | Tiene una llamada en curso. | Automático al aceptarse la llamada (TwiML). |
| `tipificando` | La llamada terminó y falta tipificarla. | Automático al terminar la llamada. |

**Cambios manuales** (`PUT /api/v1/consola/estado`, selector «Cambiar estado a» en la consola):

| desde \ hacia | disponible | pausa | desconectado |
|---|---|---|---|
| `desconectado` | permitido | permitido | igual (sin cambios) |
| `disponible` | igual (sin cambios) | permitido | permitido |
| `pausa` | permitido | permitido (cambia el motivo) | permitido |
| `en_llamada` | 409 `AGENTE_EN_LLAMADA` | 409 `AGENTE_EN_LLAMADA` | 409 `AGENTE_EN_LLAMADA` |
| `tipificando` | 409 `TIPIFICACION_PENDIENTE` | 409 `TIPIFICACION_PENDIENTE` | 409 `TIPIFICACION_PENDIENTE` |

- Pasar a `pausa` exige `motivo_pausa`. Enviarlo con otro estado devuelve 422.
- Un cambio al mismo estado y motivo no tiene efecto y no se registra en el historial.
- Cada cambio queda en `historial_estados_agente` (base del reporte de ocupación de la Fase 4).

**Cambios automáticos:**

- Llamada permitida → `en_llamada`.
- Llamada terminada (cualquier estado final que fue realizada) → `tipificando`.
- Tipificación guardada → `disponible`. Si el usuario fue desactivado, queda `desconectado`.
- Sin WebSocket abierto durante `CONSOLA_DESCONEXION_SEGUNDOS` (60 s por defecto), estando `disponible` o
  `pausa` → `desconectado`. Un agente con la consola abierta en otra pestaña sigue conectado. El temporizador
  vive en la memoria del proceso (ver [`pendientes.md`](pendientes.md), sección 5).

**Regla práctica:** el agente no puede llamar, tomar otro registro ni cambiar de estado mientras tenga
una llamada sin tipificar. La consola lo muestra con el bloque «Tipificar la llamada».

---

## 3. Lista de trabajo

La consola muestra las campañas asignadas con el número de **pendientes** (`GET /api/v1/consola/campanas`).
Al elegir una campaña (o «todas»), la lista (`GET /api/v1/consola/registros`) incluye:

- Los registros **reservados por el agente** con reserva vigente.
- Los registros **pendientes** (o `en_gestion` con reserva caducada), con `intentos < max_intentos` y con
  `proximo_intento_en` vacío o ya llegado.

Orden: primero los reservados por mí, después por `proximo_intento_en` (o fecha de creación) y por `id`.
La lista se refresca al recibir eventos `consola.registro`. Cada fila muestra la campaña, el tipo, el último
resultado, la última gestión y el botón **Tomar** o **Retomar** (si ya es suyo).

---

## 4. Tomar, soltar y reservas

### Reserva

Tomar un registro (`POST /api/v1/consola/registros/{id}/tomar`) lo marca `en_gestion` y lo reserva para el
agente durante **`CONSOLA_RESERVA_MINUTOS`** (15 por defecto). Solo puede haber una reserva por agente: tomar
otro registro libera la anterior. La reserva se gestiona con estas reglas:

| Momento | Efecto sobre la reserva |
|---|---|
| Tomar el registro | 15 minutos desde ahora. Si ya era suyo, se renueva. |
| Iniciar una llamada permitida | Se renueva 15 minutos. |
| Cada webhook de estado de la llamada (ringing, answered…) | Se renueva 15 minutos. Así una llamada larga no pierde el registro. |
| Terminar la llamada | Se renueva 15 minutos, hasta que el agente tipifique. |
| Tipificar | Se libera (o pasa a `gestionado`/`pendiente` según el resultado). |
| Soltar | Se libera y vuelve a `pendiente`. |
| Caducar sin llamada pendiente | Otro agente puede tomarlo. |

**Protección hasta tipificar.** Mientras la llamada del agente esté activa **o terminada sin tipificar**,
ningún otro agente puede tomar el registro, aunque la reserva haya caducado. La API responde
`409 REGISTRO_RESERVADO`. Así no se llama dos veces al mismo cliente por un fallo de tiempo.

**Reserva concurrente.** Dos agentes que toman el mismo registro a la vez: solo uno obtiene `200`; el otro,
`409 REGISTRO_RESERVADO`.

### Soltar

`POST /api/v1/consola/registros/{id}/soltar` → `204`. Solo funciona con una reserva propia vigente.

- Con una llamada en curso sobre el registro: `409 AGENTE_EN_LLAMADA`.
- Con una llamada terminada sin tipificar: `409 TIPIFICACION_PENDIENTE`. Hay que tipificar primero.

### Cambios de asignación

Si un administrador quita al agente de la campaña, se liberan sus reservas en esa campaña. **Excepción:** el
registro con una llamada activa o sin tipificar conserva la reserva hasta que el agente tipifique (puede
cerrar la gestión, pero no tomar nuevos registros).

---

## 5. Ficha del cliente

`GET /api/v1/consola/registros/{id}` (o la respuesta de **Tomar**) devuelve la ficha. Solo se ve con reserva
propia vigente (`409 REGISTRO_NO_RESERVADO` si no). Cada vista queda auditada (`consola.ficha_ver`).

La ficha contiene:

- **Cliente**: documento completo (S-A2, necesario para verificar la identidad en la llamada), nombre, email y
  ciudad.
- **Campaña y registro**: estado, intentos y máximo, último resultado, próximo intento y reserva hasta.
- **Obligación** (campos de la importación): número de obligación, saldos, días de mora, fecha de vencimiento,
  producto, oferta y datos adicionales.
- **Teléfonos**: ordenados por prioridad. El número aparece **enmascarado**: `+57300****567` (los seis primeros
  caracteres, `****` y los tres últimos). Cada teléfono indica si es `llamable` y los motivos si no lo es:
  `EXCLUIDO` (número excluido, con su motivo) o los de cumplimiento (`FESTIVO`, `DIA_SIN_FRANJA`,
  `FUERA_DE_FRANJA`, `FRECUENCIA_DIA`, `FRECUENCIA_MEDIOS`). También es no llamable si el registro agotó sus
  intentos.
- **Cumplimiento**: el resultado de horario y frecuencia **en este momento**. Es informativo: la decisión
  definitiva la toma el servidor al iniciar la llamada.
- **Guion**: el guion de la campaña con las variables sustituidas (`{{nombre}}`, `{{primer_nombre}}`,
  `{{saldo_total}}`, `{{saldo_mora}}`, `{{dias_mora}}`, `{{fecha_vencimiento}}`, `{{numero_obligacion}}`,
  `{{producto}}`, `{{oferta}}`, `{{empresa}}`, `{{agente}}`, `{{datos.<clave>}}`). Los montos se muestran como
  `$ 1.500.000` y las fechas como `15/09/2026`. Una variable desconocida se deja tal cual.
- **Historial**: las últimas 20 gestiones del registro, de la más reciente a la más antigua, con el agente, el
  resultado, la observación y, si aplica, la promesa, la venta o la fecha de rellamada.

La consola nunca muestra un número completo en `/consola/*`.

---

## 6. Llamar

1. El agente pulsa **Llamar a +57300****567** (el número enmascarado del teléfono elegido). El botón está
   deshabilitado si el teléfono no es llamable, si el agente no está `disponible` o si el softphone no está listo.
2. El navegador envía solo ids (`campana_cliente_id`, `telefono_id`). El servidor resuelve el número.
3. El servidor aplica las comprobaciones previas de [`telefonia-twilio.md`](telefonia-twilio.md) (incluido el
   cumplimiento). Si las supera, la llamada pasa a `iniciando` y el agente a `en_llamada`.
4. Si no las supera, la llamada queda **bloqueada** y la barra muestra los motivos. El agente no pasa a
   `tipificando` y la llamada no se tipifica.
5. Durante la llamada, la barra ofrece **Silenciar** / **Quitar silencio** y **Colgar**. Muestra la duración
   desde que la llamada entra en curso (es informativa y se mide en el navegador).
6. Al terminar, la consola muestra el formulario de tipificación. Hasta enviarlo, la consola bloquea otras
   acciones.

Estados de la llamada que ve el agente: `Iniciando`, `Sonando`, `En curso`, `Completada`, `Ocupado`,
`No contesta`, `Fallida`, `Cancelada` y `Bloqueada`. Una llamada `bloqueada` no necesita tipificación.

---

## 7. Tipificaciones y sus efectos

La tipificación es **obligatoria** para cada llamada realizada (estados `completada`, `ocupado`, `no_contesta`,
`fallida`, `cancelada`). Se guarda una sola vez por llamada (`POST /api/v1/consola/tipificaciones`, `201`).

### Campos y reglas

| Campo | Cuándo | Reglas |
|---|---|---|
| `resultado` | Siempre | Uno de los siete de la tabla de efectos. |
| `observacion` | Opcional | Hasta 1000 caracteres, tras quitar los espacios de los extremos. Más de 1000 → `422 VALIDACION`. Vacía → sin observación. |
| `promesa` | Solo `promesa_pago` (obligatoria) | `monto`: decimal positivo en texto, hasta 12 enteros y 2 decimales, no mayor que `saldo_total` si existe. `fecha_pago`: entre hoy y `PROMESA_MAX_DIAS` (60 por defecto), fecha local de Bogotá. |
| `venta` | Solo `venta` (obligatoria) | `producto`: 2 a 120 caracteres (espacios colapsados). `valor`: decimal positivo, hasta 2 decimales. |
| `contacto_directo` | Solo `volver_a_llamar` (obligatorio) | Booleano. En los demás resultados debe omitirse. |
| `volver_a_llamar_en` | Solo `volver_a_llamar` (obligatorio) | Fecha y hora **con zona** (sin zona → 422). Debe estar entre 5 minutos y 30 días desde ahora, dentro del horario de la política. La consola la envía con `-05:00`. |

Reglas adicionales:

- **Coherencia técnica.** Si la llamada nunca se contestó (`no_contesta`, `ocupado`, `fallida`, `cancelada`),
  solo se admiten `no_contesta` o `numero_errado`. Otro resultado → `422 RESULTADO_INCOHERENTE`.
- **Tipo de campaña.** `promesa_pago` solo en campañas de **cobranza**; `venta` solo en campañas de **venta**.
  Otro caso → `422 RESULTADO_NO_PERMITIDO`.
- **Fuera de franja.** Una fecha de rellamada fuera del horario de la política → `422
  VOLVER_A_LLAMAR_FUERA_DE_FRANJA`, con la próxima ventana en el detalle, por ejemplo
  `Fuera de franja. Próxima ventana: 2026-10-26T07:00:00-05:00`.
- Una segunda tipificación de la misma llamada → `409 LLAMADA_YA_TIPIFICADA`.

### Efectos sobre el registro

| Resultado | Contacto directo | Estado del registro | `intentos` | Próximo intento | Otros efectos |
|---|---|---|---|---|---|
| `contactado` | sí | `gestionado` | +1 | — | Habló con el titular, sin resultado concreto. Para volver a contactar, use `volver_a_llamar` (S-A7). |
| `no_contesta` | no | `pendiente`, o `gestionado` si `intentos + 1 ≥ max_intentos` | +1 | Próxima ventana de horario tras `intervalo_reintento_minutos` (solo horario) | — |
| `numero_errado` | no | `gestionado` si `intentos + 1 ≥ max_intentos`; si no, `pendiente` si queda otro teléfono llamable, o `descartado` | +1 | — | **Excluye ese número para todas las campañas** (`numero_errado`, `aplica_a = todas`). Queda en `/exclusiones`. |
| `promesa_pago` | sí | `gestionado` | +1 | — | Crea una promesa vigente: 1 cuota, descuento 0, origen `agente`. |
| `venta` | sí | `gestionado` | +1 | — | Crea una venta: 1 unidad, origen `agente`. |
| `rechazo` | sí | `gestionado` | +1 | — | — |
| `volver_a_llamar` | según la petición | `pendiente` | +1 | `volver_a_llamar_en` | — |

En todos los casos: se guardan `ultimo_resultado` y `ultima_gestion_en`; se libera la reserva; el intento de
contacto de la llamada recibe el `contacto_directo` y el resultado; el agente pasa a `disponible`; se registra
la auditoría `tipificacion.crear` (sin observación ni teléfonos) y se emiten los eventos `agente.estado` y
`consola.registro`.

Si el registro queda `gestionado` o `descartado`, sale de la lista de trabajo.

Respuesta `201` de **POST /consola/tipificaciones**: la tipificación con su promesa o venta, y `registro`
con el estado, los intentos y el próximo intento resultantes.

### Errores de la tipificación

| HTTP | Código | Cuándo |
|---|---|---|
| 404 | `NO_ENCONTRADO` | La llamada no existe o no es del agente. |
| 409 | `LLAMADA_EN_CURSO` | La llamada aún no terminó. |
| 409 | `LLAMADA_BLOQUEADA` | La llamada nunca se realizó. |
| 409 | `LLAMADA_YA_TIPIFICADA` | Ya tiene tipificación. |
| 422 | `RESULTADO_INCOHERENTE` | Resultado imposible para el estado técnico de la llamada. |
| 422 | `RESULTADO_NO_PERMITIDO` | `promesa_pago` en venta, o `venta` en cobranza. |
| 422 | `VOLVER_A_LLAMAR_FUERA_DE_FRANJA` | Fecha de rellamada fuera de la política. |
| 422 | `VALIDACION` | Campos obligatorios, formato o rangos; `detalles` indica el campo. |

---

## 8. Supervisión en vivo y tipificaciones de campaña

### Página Supervisión (`/supervision/agentes`, administrador y supervisor)

`GET /api/v1/supervision/agentes` lista todos los agentes activos, por nombre, con:

- `estado`, `desde` (para el tiempo en estado, que la página cuenta en vivo) y `motivo_pausa`.
- `campanas`: ids de las campañas asignadas.
- `llamada`: la llamada en curso (`id`, `estado`, `campana_id`, `campana_nombre`) o `null`.

La tabla se actualiza con los eventos `agente.estado` y `llamada.estado`. Sin fila de estado, el agente aparece
como `desconectado`.

La supervisión **no** puede forzar tipificaciones ni liberar registros desde la interfaz. Esa acción está
prevista en la subfase 2F (ver [`pendientes.md`](pendientes.md), sección 5).

### Pestaña Tipificaciones de la campaña (administrador y supervisor)

`GET /api/v1/campanas/{id}/tipificaciones?resultado=&origen=&desde=&hasta=&page=&page_size=`

- Filtros: `resultado`, `origen` (`agente`, `agente_ia`, `sistema`) y rango de fechas `desde`/`hasta` en formato
  `YYYY-MM-DD`, inclusivo y en hora local de Bogotá.
- Orden: fecha de creación descendente.
- Cada fila incluye `cliente_nombre` y `agente_nombre`. No incluye el registro de la tipificación.

---

## 9. Códigos de error de la consola

| HTTP | Código | Cuándo | Qué hace el agente |
|---|---|---|---|
| 403 | `CAMPANA_NO_ASIGNADA` | El agente no está asignado a la campaña del registro. | Pedir la asignación al supervisor. |
| 409 | `REGISTRO_RESERVADO` | Otro agente tiene la reserva vigente, o hay una llamada pendiente de otro agente. | Elegir otro registro. |
| 409 | `REGISTRO_NO_DISPONIBLE` | Registro gestionado o descartado, intentos agotados, rellamada futura, o campaña no activa. | Elegir otro registro. |
| 409 | `REGISTRO_NO_RESERVADO` | La operación requiere reserva propia vigente. | Tomar el registro de nuevo. |
| 409 | `TIPIFICACION_PENDIENTE` | Hay una llamada terminada sin tipificar. | Tipificarla. |
| 409 | `AGENTE_EN_LLAMADA` | Operación incompatible con una llamada en curso. | Esperar al final de la llamada. |
| 409 | `TRANSICION_ESTADO_INVALIDA` | Cambio de estado no permitido. | Elegir otro estado. |
| 409 | `ESTADO_CONCURRENTE` | Dos cambios de estado simultáneos. | Reintentar. |
| 409 | `USUARIO_CON_GESTION_PENDIENTE` | Se intenta desactivar un agente con llamada activa o sin tipificar (`PATCH /usuarios/{id}`). | Resolver la gestión (administrador). |

---

## 10. Procedimiento de soporte: `liberar-gestion`

**Cuándo usarlo.** Cuando un agente no puede seguir por una gestión atascada. Por ejemplo, se perdieron los
webhooks de Twilio y la llamada quedó en `iniciando`, `sonando` o `en_curso`, o terminó sin tipificar y el
agente no puede resolverlo. Es una operación de **soporte**, no de uso diario. No hay endpoint HTTP: se
ejecuta en el servidor (o en el contenedor del backend).

```bash
# Desde backend/ (sin Docker)
python -m app.cli liberar-gestion --llamada-id 31 --resultado no_contesta

# Con Docker Compose
docker compose exec backend python -m app.cli liberar-gestion --llamada-id 31 --resultado no_contesta
```

| Argumento | Obligatorio | Valores |
|---|---|---|
| `--llamada-id` | sí | Id de la llamada (entero). |
| `--resultado` | sí | `no_contesta`, `numero_errado` o `contactado`. Cualquier otro valor se rechaza. |

**Comportamiento final:**

1. **Llamada inexistente.** Imprime `Llamada no encontrada.` y termina con código 1.
2. **Llamada activa** (`iniciando`, `sonando` o `en_curso`):
   - Si se inició hace **más de 3600 s** (`iniciada_en`), la cierra como `fallida` (sin duración) y la tipifica.
     En este caso **solo admite `no_contesta` o `numero_errado`**. Con `contactado` imprime un aviso,
     termina con código 1 y no modifica nada.
   - Si se inició hace 3600 s o menos, **no la toca**. El comando imprime la antigüedad de la llamada y el
     límite (`timeLimit`) y termina con código 1.
3. **Llamada terminada sin tipificar.** Se tipifica con el resultado indicado, aplicando las mismas reglas de
   coherencia de la sección 7. Si la llamada está `bloqueada` o ya tiene tipificación, el comando falla con
   `LLAMADA_BLOQUEADA` o `LLAMADA_YA_TIPIFICADA` y no modifica nada.
4. **Una sola transacción.** El cierre (si procede), la tipificación, la liberación de la reserva y el cambio
   de estado del agente se confirman juntos. Si algo falla, no queda nada a medias.
5. **Efectos.** Los de la tabla de la sección 7 para el resultado indicado, con origen `sistema`. La reserva
   se libera. El intento de contacto y los contadores se actualizan.
6. **Auditoría.** Se registra `consola.tipificacion_sistema` sin usuario actor, con la tipificación, la llamada
   y el resultado. Ningún dato personal.
7. **Estado del agente.** Pasa a `disponible`. Si su usuario está desactivado, pasa a `desconectado`.
8. **Salida correcta.** Imprime `Llamada 31 tipificada como 'no_contesta' (sistema).` y termina con código 0.

**Notas.** El comando no pide ni guarda observación. Anote el motivo en el sistema de soporte. Úselo solo
cuando el agente no pueda tipificar por sí mismo.

---

Enlaces: [`telefonia-twilio.md`](telefonia-twilio.md) · [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md) ·
[`importacion-csv.md`](importacion-csv.md) · [`pendientes.md`](pendientes.md) · [`arquitectura/fase-2.md`](arquitectura/fase-2.md) §4.3 a §4.7.
