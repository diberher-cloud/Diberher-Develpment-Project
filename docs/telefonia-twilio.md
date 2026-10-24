# Telefonía con Twilio (subfase 2A)

Guía de la voz de la consola: cómo funciona, cómo configurar Twilio paso a paso, variables de entorno,
proveedor falso para desarrollo y solución de problemas. Diseño: [ADR-0003](arquitectura/adr-0003-integracion-twilio.md)
(integración), [ADR-0013](arquitectura/adr-0013-webhooks-y-cola-de-trabajos.md) (firma de webhooks),
[ADR-0017](arquitectura/adr-0017-consola-agente-y-tipificaciones.md) (consola) y
[`fase-2.md`](arquitectura/fase-2.md) §4.5 (contratos).

> **Estado.** La voz está implementada y probada con el proveedor falso (sin red ni credenciales).
> La integración con **Twilio real** (llamada a un móvil, firma validada a través de un túnel, aviso de
> grabación audible) **no está validada todavía**. Ver [`pendientes.md`](pendientes.md), sección 5.

Índice: [Cómo funciona](#cómo-funciona) · [Firma de los webhooks](#firma-de-los-webhooks) ·
[Configuración de Twilio](#configuración-de-twilio-paso-a-paso) · [Variables de entorno](#variables-de-entorno) ·
[Proveedor falso y simulación](#proveedor-falso-y-simulación) · [Estados y regla de «contestada»](#estados-de-la-llamada-y-regla-de-contestada) ·
[Solución de problemas](#solución-de-problemas)

---

## Cómo funciona

Participan tres partes: el **softphone** del navegador (`@twilio/voice-sdk`), el **backend** y **Twilio**.
El navegador nunca envía un número de teléfono: envía solo ids y el servidor decide si la llamada se permite
y a qué número se marca.

### Token del softphone

1. El agente abre `/consola`. El frontend llama a `POST /api/v1/telefonia/token` (rol `agente`).
2. Con `TELEFONIA_PROVEEDOR=twilio` el servidor emite un Access Token de Twilio firmado con la API Key:
   identidad `agente_<usuario_id>`, TTL `TELEFONIA_TOKEN_TTL_SEGUNDOS` (3600 por defecto) y un
   `VoiceGrant` con `outgoing_application_sid = TWILIO_TWIML_APP_SID` e `incoming_allow = False`
   (las llamadas entrantes llegan en la subfase 2E).
3. Respuesta (`200`):
   ```json
   { "proveedor": "twilio", "token": "<jwt>", "identity": "agente_5", "expira_en": "2026-10-23T16:00:00Z" }
   ```
4. El softphone crea `new Device(token, { codecPreferences: ['opus', 'pcmu'], closeProtection: true })`.
   Cuando el SDK emite `tokenWillExpire`, el frontend pide otro token y llama a `device.updateToken`.
   **No se llama a `device.register()`**: solo hace falta para llamadas entrantes, que aún no existen.

### Flujo de una llamada saliente

1. El agente, con reserva propia del registro y estado `disponible`, pulsa **Llamar** junto a un teléfono
   enmascarado. El navegador ejecuta `device.connect({ params: { campana_cliente_id, telefono_id } })`
   (ambos valores como cadenas).
2. Twilio hace `POST` a la **Voice URL** de la TwiML App: `{PUBLIC_BASE_URL}/api/v1/telefonia/twiml/saliente`,
   con el formulario `CallSid`, `From` (`client:agente_<id>`), `AccountSid` y los parámetros personalizados.
3. El backend valida la firma y ejecuta las comprobaciones previas, en este orden. **La primera que falla
   decide**, salvo el paso 12, que devuelve todos sus motivos.

   | # | Comprobación | Código si falla |
   |---|---|---|
   | 1 | Firma `X-Twilio-Signature` válida | `403 FIRMA_INVALIDA`, sin TwiML |
   | 2 | `AccountSid` = `TWILIO_ACCOUNT_SID` (solo proveedor `twilio`) y `From` = `client:agente_<id>` de un usuario activo con rol `agente` | `AGENTE_INVALIDO` |
   | 3 | `campana_cliente_id` y `telefono_id` existen y el teléfono pertenece al cliente del registro | `PARAMETROS_INVALIDOS` |
   | 4 | Ya existe una llamada con ese `CallSid` (reintento de Twilio) | Devuelve el mismo TwiML (idempotencia) |
   | 5 | El agente no tiene una llamada terminada sin tipificar | `TIPIFICACION_PENDIENTE` |
   | 6 | El agente está en `disponible` | `AGENTE_NO_DISPONIBLE` |
   | 7 | La campaña está `activa` | `CAMPANA_NO_ACTIVA` |
   | 8 | El agente está asignado a la campaña | `CAMPANA_NO_ASIGNADA` |
   | 9 | El registro tiene reserva propia vigente | `REGISTRO_NO_RESERVADO` |
   | 10 | `intentos < max_intentos` del registro | `INTENTOS_AGOTADOS` |
   | 11 | El número no está excluido para el tipo de campaña | `EXCLUIDO` |
   | 12 | Horario y frecuencia de contacto (ver [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)) | `FESTIVO`, `DIA_SIN_FRANJA`, `FUERA_DE_FRANJA`, `FRECUENCIA_DIA`, `FRECUENCIA_MEDIOS` |

   Un fallo en los pasos 5 a 12 deja una llamada con `estado = bloqueada` y sus motivos, visible en la
   consola. Un fallo en los pasos 2 y 3 no crea ninguna fila: solo queda un registro en el log.

4. **Permitida**. En una transacción el servidor crea el intento de contacto (`intentos_contacto`, canal
   `voz`, iniciado por la empresa, con la versión de la política) y la llamada en estado `iniciando`; pasa el
   agente a `en_llamada`, renueva la reserva del registro y registra la auditoría `llamada.iniciada`.
   Responde con TwiML. Con `TELEFONIA_GRABAR=true` (`{B}` = `PUBLIC_BASE_URL`):

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response>
     <Dial callerId="+576015550000" answerOnBridge="true" timeout="30" timeLimit="3600"
           record="record-from-answer-dual"
           recordingStatusCallback="{B}/api/v1/telefonia/webhooks/grabacion?llamada_id=31"
           recordingStatusCallbackEvent="completed"
           action="{B}/api/v1/telefonia/twiml/dial-terminado?llamada_id=31" method="POST">
       <Number url="{B}/api/v1/telefonia/twiml/aviso-grabacion?llamada_id=31" method="POST"
               statusCallback="{B}/api/v1/telefonia/webhooks/estado?llamada_id=31"
               statusCallbackEvent="initiated ringing answered completed"
               statusCallbackMethod="POST">+573001234567</Number>
     </Dial>
   </Response>
   ```

   El número de destino se lee de la base de datos, **nunca** de la petición. `callerId` es
   `TWILIO_NUMERO_SALIENTE`. Con `TELEFONIA_GRABAR=false` se omiten `record`, `recordingStatusCallback*`,
   y los atributos `url` y `method` de `<Number>`.

5. **Bloqueada** (pasos 5 a 12). Responde con un mensaje y colgado. El agente ve el motivo en la consola:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response><Say language="es-MX">No es posible realizar la llamada en este momento.</Say><Hangup/></Response>
   ```

   El texto sale de `TELEFONIA_MENSAJE_BLOQUEO` y el idioma de `TELEFONIA_IDIOMA_VOZ`.

6. **Aviso de grabación.** Cuando el cliente contesta, Twilio pide `{B}/api/v1/telefonia/twiml/aviso-grabacion?llamada_id=N`
   (atributo `url` de `<Number>`) y reproduce el aviso **en la pierna del cliente, antes de unirla con el agente**:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response><Say language="es-MX">Le informamos que esta llamada será grabada y monitoreada con fines de calidad y seguridad.</Say></Response>
   ```

   > **Importante.** El aviso solo existe cuando `TELEFONIA_GRABAR=true`. Si se desactiva la grabación,
   > también desaparece el aviso. El texto debe estar aprobado por el área jurídica (ver
   > [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)). Que se oiga bien en una llamada real no está validado.

7. **Finalización.** La llamada termina cuando llega la primera señal terminal (ver
   [Estados](#estados-de-la-llamada-y-regla-de-contestada)). El agente pasa a `tipificando` y debe tipificar antes
   de tomar otro registro.

### Webhooks de Twilio

Todos están bajo `/api/v1/telefonia/`, no usan JWT y **validan la firma antes de cualquier otra cosa**.

| Endpoint | Quién lo llama | Parámetros (formulario) | Respuesta | Efecto |
|---|---|---|---|---|
| `POST /twiml/saliente` | Voice URL de la TwiML App | `CallSid`, `From`, `AccountSid`, `campana_cliente_id`, `telefono_id` | `200 application/xml` | Permite o bloquea la llamada (tabla anterior). |
| `POST /twiml/aviso-grabacion?llamada_id=` | `<Number url>` al contestar el cliente | firma | `200 application/xml` | Reproduce el aviso. |
| `POST /twiml/dial-terminado?llamada_id=` | `action` de `<Dial>` | `CallSid`, `DialCallStatus`, `DialCallDuration`, `DialCallSid` | `200 <Response><Hangup/></Response>` | Registra `dial-terminado` y finaliza la llamada. |
| `POST /webhooks/estado[?llamada_id=]` | `statusCallback` de `<Number>` (pierna del cliente, con `llamada_id`) y Status Callback de la TwiML App (pierna del agente, sin `llamada_id`) | `CallSid`, `CallStatus`, `SequenceNumber`, `CallDuration`, `ParentCallSid` | `204` | Guarda el evento y aplica la transición de estado. |
| `POST /webhooks/grabacion?llamada_id=` | `recordingStatusCallback` de `<Dial>` | `RecordingSid`, `RecordingUrl`, `RecordingStatus`, `RecordingDuration`, `RecordingChannels` | `204` | Guarda o actualiza la grabación (clave `RecordingSid`). |

- Un webhook de estado duplicado (mismo `CallSid`, estado y `SequenceNumber`) se ignora.
- Un webhook de una llamada desconocida responde `204` sin efectos y sin registrar parámetros en el log.
- La URL de la grabación se guarda en servidor y **no se expone al navegador** en 2A.
- Los eventos de llamada guardan solo `CallDuration`, `SipResponseCode` y `DialCallStatus`/`DialCallDuration`,
  nunca números de teléfono.

---

## Firma de los webhooks

Twilio firma cada petición con `X-Twilio-Signature`. El backend recalcula la firma con el mismo algoritmo
(`backend/app/integraciones/twilio_firma.py`, función pura):

```
firma = base64( HMAC-SHA1( TWILIO_AUTH_TOKEN, url + Σ (clave + valor) ) )
```

- `url` = `PUBLIC_BASE_URL` + ruta + query original, **exactamente** como la llamó Twilio. No se usa la
  URL que ve el servidor detrás de un proxy.
- Los parámetros van ordenados por clave. Valores repetidos idénticos cuentan una sola vez, como en el
  validador oficial de Twilio.
- La comparación es en tiempo constante. Firma ausente o incorrecta → `403`:
  ```json
  { "error": { "codigo": "FIRMA_INVALIDA", "mensaje": "Firma inválida.", "detalles": [] } }
  ```
- La firma se valida también con el proveedor falso, usando `TWILIO_AUTH_TOKEN` (por defecto el valor de
  desarrollo `token-falso-solo-desarrollo`).

**Por eso `PUBLIC_BASE_URL` debe ser exacta.** Cualquier diferencia (`http` por `https`, barra final, otro
dominio, un túnel que cambió de dirección, un proxy que reescribe el host) hace que todas las firmas fallen.

---

## Configuración de Twilio paso a paso

Los nombres de menú de la consola de Twilio cambian con el tiempo. Busque cada elemento por su nombre.
Lo que sigue es lo que la aplicación necesita, no una captura de pantalla.

### 1. Cuenta

- Use una cuenta de pago. Una cuenta de prueba (*trial*) solo llama a números verificados y no sirve para
  campañas reales (requisito del plan, [`fase-2.md`](arquitectura/fase-2.md) §8.1).
- Anote el **Account SID** (empieza por `AC`) y el **Auth Token**. El token es el secreto con el que se firman
  los webhooks. Va en `TWILIO_AUTH_TOKEN`.

### 2. API Key

- Cree una **API Key** de tipo estándar. Twilio muestra el **secret** una sola vez: guárdelo.
- `TWILIO_API_KEY_SID` (empieza por `SK`) y `TWILIO_API_KEY_SECRET` se usan para firmar los tokens del
  softphone. No son el Auth Token.

### 3. TwiML App

Cree una **TwiML App** (aplicación de voz) con estas dos URLs. Son las rutas exactas que monta la API:

| Campo | Método | URL |
|---|---|---|
| **Voice Request URL** (voz) | `POST` | `{PUBLIC_BASE_URL}/api/v1/telefonia/twiml/saliente` |
| **Status Callback URL** | `POST` | `{PUBLIC_BASE_URL}/api/v1/telefonia/webhooks/estado` |

- `{PUBLIC_BASE_URL}` es el valor de la variable, sin barra final. Ejemplo:
  `https://abcd-1234.ejemplo-tunel.app/api/v1/telefonia/twiml/saliente`.
- Anote el identificador de la TwiML App en `TWILIO_TWIML_APP_SID`.
- Los eventos que deben marcarse en el Status Callback de la TwiML App **no están validados con Twilio real**
  (ver [`pendientes.md`](pendientes.md), sección 5). Como mínimo, marque los eventos de fin de llamada.
- Las URLs de la TwiML App son absolutas. **Si cambia el dominio o el túnel, debe actualizarlas aquí también.**

### 4. Número de voz (+57)

- Compre o asigne en la cuenta un número de voz colombiano (`+57…`) con capacidad de voz saliente.
  Su valor en E.164 va en `TWILIO_NUMERO_SALIENTE` y es el *caller ID* que ve el cliente.
- Colombia exige un **paquete regulatorio** (*Regulatory Bundle*) aprobado para el número, o un caller ID
  verificado. Confirme que el caller ID cumple lo que exija la CRC. Son requisitos externos del plan, no
  comprobados por el código.

### 5. `PUBLIC_BASE_URL`

- Es la URL pública **exacta** con la que Twilio llama a la API: `https://`, sin barra final, sin ruta.
  Ejemplo: `PUBLIC_BASE_URL=https://abcd-1234.ejemplo-tunel.app`.
- Con `TELEFONIA_PROVEEDOR=twilio` debe empezar por `https://` (salvo `ENTORNO=test`). En `ENTORNO=produccion`
  también es obligatoria con cualquier proveedor.
- Una barra final (`…app/`) hace que el arranque falle con «PUBLIC_BASE_URL no debe terminar en barra».

### 6. Túnel HTTPS para desarrollo

Twilio solo puede llamar a una URL pública. En desarrollo, exponga el puerto del backend con un túnel.
Son ejemplos habituales (no verificados en este repositorio):

```bash
# ngrok
ngrok http 8000

# cloudflared (túnel rápido)
cloudflared tunnel --url http://localhost:8000
```

Después:

1. Copie la URL `https://…` que muestra el túnel en `PUBLIC_BASE_URL` (sin barra final).
2. Reinicie el backend. La configuración se lee al arrancar (`get_settings` está en caché), así que un cambio
   sin reinicio no surte efecto.
3. Actualice las URLs de la TwiML App con la nueva base.
4. Si el túnel cambia en cada arranque (plan gratuito de ngrok), repita los pasos 1 a 3 cada vez.

### 7. Verificación

1. `GET /api/v1/salud` responde `200`.
2. `POST /api/v1/telefonia/token` con un agente devuelve `"proveedor": "twilio"`.
3. Llame desde la consola a un móvil de prueba. Confirme que suena el móvil, que se oye el aviso de
   grabación antes de que el agente se una y que la llamada aparece en el historial. Este paso es el que
   queda pendiente de validar.

---

## Variables de entorno

Se leen en `backend/app/config.py`. Plantilla: `.env.example`.

| Variable | Por defecto | Descripción |
|---|---|---|
| `TELEFONIA_PROVEEDOR` | `falso` | `falso` (sin red ni credenciales) o `twilio`. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL pública exacta de la API. Sin barra final. Con `twilio` debe ser `https://` (salvo `ENTORNO=test`). |
| `TWILIO_ACCOUNT_SID` | vacío | Account SID (`AC…`). Obligatoria con `twilio`. Se compara con `AccountSid` de cada TwiML. |
| `TWILIO_AUTH_TOKEN` | `token-falso-solo-desarrollo` | Auth Token. Valida todas las firmas. Obligatoria con `twilio`. En `ENTORNO=produccion` no puede estar vacía ni ser el valor de ejemplo. |
| `TWILIO_API_KEY_SID` | vacío | API Key SID (`SK…`). Obligatoria con `twilio`. |
| `TWILIO_API_KEY_SECRET` | vacío | Secret de la API Key. Obligatoria con `twilio`. |
| `TWILIO_TWIML_APP_SID` | vacío | Identificador de la TwiML App. Obligatoria con `twilio`. |
| `TWILIO_NUMERO_SALIENTE` | vacío | Número de voz en E.164 (`+57…`). Caller ID. Obligatoria con `twilio`. |
| `TELEFONIA_TOKEN_TTL_SEGUNDOS` | `3600` | Vida del token del softphone. |
| `TELEFONIA_GRABAR` | `true` | Graba la llamada (`record-from-answer-dual`) y reproduce el aviso. Con `false`, no hay grabación ni aviso. |
| `TELEFONIA_AVISO_GRABACION` | texto legal de ejemplo | Texto del aviso que oye el cliente. Pendiente de aprobación jurídica. |
| `TELEFONIA_IDIOMA_VOZ` | `es-MX` | Idioma de los `<Say>`. |
| `TELEFONIA_MENSAJE_BLOQUEO` | `No es posible realizar la llamada en este momento.` | Mensaje de las llamadas bloqueadas. |

Validación al arrancar (`Settings`):

- `TELEFONIA_PROVEEDOR=twilio` exige las seis variables `TWILIO_*` no vacías (la lista de faltantes aparece
  en el mensaje de error), `TWILIO_NUMERO_SALIENTE` en E.164 y `PUBLIC_BASE_URL` con `https://` (salvo `ENTORNO=test`).
- `PUBLIC_BASE_URL` no puede terminar en barra (con cualquier proveedor).
- `ENTORNO=produccion` exige `PUBLIC_BASE_URL` con `https://` y un `TWILIO_AUTH_TOKEN` real.

> **Docker Compose.** `docker-compose.yml` pasa al servicio `backend` una lista fija de variables, y ninguna de
> las `TELEFONIA_*`, `TWILIO_*`, `PUBLIC_BASE_URL`, `CONSOLA_*`, `PROMESA_MAX_DIAS`, `WS_REVALIDAR_SEGUNDOS`
> ni `BUS_EVENTOS` está en esa lista. Aunque estén en el `.env` de la raíz, **no llegan al contenedor**. Para
> usar Twilio con Docker, añádalas a `environment` del servicio `backend` o copie el `.env` en `backend/`
> (el directorio se monta en `/app`). Ver [`pendientes.md`](pendientes.md), sección 5.

---

## Proveedor falso y simulación

Con `TELEFONIA_PROVEEDOR=falso` (valor por defecto) no hay red ni credenciales:

- `POST /telefonia/token` devuelve `"proveedor": "falso"` y un token `falso.agente_<id>.<aleatorio>`.
- El softphone del navegador es `SoftphoneFalso`. No usa audio: cada acción llama a los endpoints de
  simulación, que ejecutan **los mismos servicios** que los webhooks de Twilio.
- Los endpoints de Twilio (`/twiml/*`, `/webhooks/*`) siguen montados y validan firma con `TWILIO_AUTH_TOKEN`.

### Endpoints de simulación

Solo existen si `TELEFONIA_PROVEEDOR=falso` **y** `ENTORNO` no es `produccion`. En cualquier otro caso
responden `404`. Requieren rol `agente`.

**`POST /api/v1/telefonia/simulacion/llamadas`**

```json
{ "campana_cliente_id": 15, "telefono_id": 21 }
```

Ejecuta el mismo servicio que el TwiML saliente, con `From = client:agente_<yo>` y un `CallSid` aleatorio
(`CAsim…`). Respuesta `200`:

```json
{ "llamada_id": 31, "permitida": true, "motivos": [] }
```

Si la llamada se bloquea, `llamada_id` es `32` (se crea la fila bloqueada) o `null` (pasos 2 y 3), y
`motivos` lista los códigos, por ejemplo `{ "codigo": "FUERA_DE_FRANJA", "mensaje": "…" }`.

**`POST /api/v1/telefonia/simulacion/llamadas/{id}/eventos`** → `204`

```json
{ "evento": "contestada" }
```

```json
{ "evento": "finalizada", "resultado": "completed", "duracion_segundos": 42 }
```

- `resultado` ∈ `completed | busy | no-answer | failed | canceled`. Por defecto, `completed`.
- `duracion_segundos` entre 0 y 86400.
- Solo llamadas propias; si la llamada es de otro agente, `404`.
- `contestada` simula el callback «en curso» de la pierna del cliente. `finalizada` simula
  `dial-terminado`.

En la consola, con la llamada permitida, aparecen los botones **Contesta**, **No contesta** y **Ocupado**
(solo en modo falso). **Colgar** envía `finalizada` con `completed` y la duración calculada en el navegador.

---

## Estados de la llamada y regla de «contestada»

Estados (`ESTADOS_LLAMADA`): `iniciando`, `sonando`, `en_curso` (activos); `completada`, `ocupado`,
`no_contesta`, `fallida`, `cancelada`, `bloqueada` (terminales).

| Señal | Efecto |
|---|---|
| Webhook de estado con `ringing` | `iniciando` → `sonando`. |
| `in-progress` o `answered` | `iniciando` o `sonando` → `en_curso`, y se fija `contestada_en`. |
| `dial-terminado` con `DialCallStatus` terminal, o estado terminal de la pierna del cliente o del agente | Finalización (una sola vez). |

**Estado final según la señal terminal** (`_estado_final`):

| Proveedor | Final |
|---|---|
| `completed` con `contestada_en` | `completada` |
| `completed` sin `contestada_en` | `no_contesta` |
| `busy` | `ocupado` |
| `no-answer` | `no_contesta` |
| `failed` | `fallida` |
| `canceled` | `cancelada` |

**Regla de «contestada» (S2, revisión post-QA).** Una llamada `completed` cuenta como contestada si
`DialCallDuration > 0` en `dial-terminado`, aunque no haya llegado el callback `answered`. En ese caso
`contestada_en = ahora − duración`. La duración es la de la pierna del cliente (`DialCallDuration`). La
`CallDuration` de la pierna del agente, que incluye el tiempo de marcado, **no se usa**.

Resumen: `completed` + `DialCallDuration > 0` → `completada`. `completed` sin duración → `no_contesta`.

La regla está pensada porque el callback `answered` puede perderse. **No está validada con Twilio real**
(ver [`pendientes.md`](pendientes.md), sección 5).

La finalización es idempotente. Dos señales terminales simultáneas finalizan la llamada una sola vez
(`UPDATE … WHERE estado NOT IN (terminales)`). Los webhooks de estado y `dial-terminado` bloquean la fila
de la llamada (`FOR UPDATE`).

---

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `403 FIRMA_INVALIDA` en todos los webhooks | `PUBLIC_BASE_URL` distinta de la URL que llama Twilio, o `TWILIO_AUTH_TOKEN` incorrecto | Compare la base con la URL del túnel (`https`, sin barra final, mismo dominio). Revise el Auth Token. Reinicie el backend tras cambiar el `.env`. |
| `403 FIRMA_INVALIDA` solo en el túnel | El túnel cambió de dirección, o un proxy reescribe el host | Actualice `PUBLIC_BASE_URL` y las URLs de la TwiML App. Si hay proxy, no debe reescribir la URL pública. |
| La consola dice «no es posible realizar la llamada» | Llamada bloqueada: revise el motivo en la consola | `FUERA_DE_FRANJA`, `FESTIVO` o `FRECUENCIA_DIA` son bloqueos correctos. Para pruebas, use horario permitido. |
| `404` en `/telefonia/simulacion/…` | Proveedor `twilio` o `ENTORNO=produccion` | Es lo esperado. La simulación solo existe con el proveedor falso fuera de producción. |
| El softphone dice que no se pudo iniciar | Token inválido o error de SDK | Revise `POST /telefonia/token`. Con `twilio`, compruebe `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` y `TWILIO_TWIML_APP_SID`. |
| Arranque: «TELEFONIA_PROVEEDOR=twilio exige: …» | Falta una variable obligatoria | Complete la lista del mensaje. |
| Arranque: «PUBLIC_BASE_URL no debe terminar en barra» | URL con `/` final | Quítela. |
| La llamada no genera eventos de estado en el backend | Las URLs de la TwiML App no coinciden con la base, o Docker no pasa la variable | Revise la TwiML App y la sección de Docker de [Variables de entorno](#variables-de-entorno). |
| La llamada queda en `iniciando` o `en_curso` | Se perdieron webhooks | El agente no puede tipificar mientras la llamada esté activa. Use el procedimiento de soporte `liberar-gestion` ([`consola-agente.md`](consola-agente.md), sección 10). |

Enlaces: [`consola-agente.md`](consola-agente.md) · [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md) ·
[`pendientes.md`](pendientes.md) · [`arquitectura/fase-2.md`](arquitectura/fase-2.md) §4.5 y §5.
