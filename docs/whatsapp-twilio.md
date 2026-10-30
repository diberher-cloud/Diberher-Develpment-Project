# WhatsApp con Twilio (subfase 2B)

> **Estado.** La subfase 2B está implementada y probada con el proveedor falso (SQLite y PostgreSQL 16).
> La integración con una cuenta real de Twilio y de Meta **no está verificada**: las secciones marcadas
> con **[verificar]** dependen de la consola de Twilio o de Meta, que no se ha comprobado en una cuenta
> real. Lo pendiente está en [`pendientes.md`](pendientes.md), sección 5.
>
> Decisiones: [ADR-0010](arquitectura/adr-0010-proveedor-whatsapp-twilio.md) (proveedor),
> [ADR-0013](arquitectura/adr-0013-webhooks-y-cola-de-trabajos.md) (webhooks y cola),
> [ADR-0019](arquitectura/adr-0019-whatsapp-bandeja-humana.md) (bandeja y envío) y
> [`fase-2b.md`](arquitectura/fase-2b.md) (contratos completos). Uso diario de la bandeja:
> [`bandeja-whatsapp.md`](bandeja-whatsapp.md). Reglas de cumplimiento:
> [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md).

Índice: [1. Cómo funciona](#1-cómo-funciona) · [2. Configuración de Twilio y Meta](#2-configuración-de-twilio-y-meta) ·
[3. Variables de entorno](#3-variables-de-entorno) · [4. Worker](#4-worker) · [5. Simulación](#5-simulación-solo-fuera-de-producción) ·
[6. Solución de problemas](#6-solución-de-problemas)

---

## 1. Cómo funciona

### 1.1 Piezas

| Pieza | Dónde | Función |
|---|---|---|
| Webhook entrante | `POST /api/v1/whatsapp/webhooks/entrante` | Valida la firma, guarda el mensaje y encola su procesamiento. No hace llamadas externas (el diseño fija un objetivo de 300 ms). |
| Webhook de estado | `POST /api/v1/whatsapp/webhooks/estado` | Aplica el estado de entrega de un mensaje saliente. Siempre responde `204` tras validar la firma. |
| Cola `trabajos` | Tabla de la base de datos | Guarda los trabajos pendientes. Con PostgreSQL varios workers la consumen sin pisarse. |
| Worker | `python -m app.worker` | Procesa los entrantes, envía los salientes y ejecuta los trabajos periódicos (sección 4). |
| Proveedor | `WHATSAPP_PROVEEDOR=twilio` o `falso` | Con `twilio` usa el SDK `twilio` (mensajes y Content API) y `httpx` para los medios. Con `falso`, nada sale a la red (sección 5). |

Los webhooks no tienen JWT: se autentican solo con la firma de Twilio.

### 1.2 Mensaje entrante

1. Twilio llama a `POST /api/v1/whatsapp/webhooks/entrante` con un formulario (`MessageSid`, `From`, `To`,
   `Body`, `ProfileName`, `NumMedia`, `MediaUrl{i}`, `ButtonPayload`…).
2. La API valida la firma (si falla, `403 FIRMA_INVALIDA`), comprueba que `AccountSid` sea el de
   `TWILIO_ACCOUNT_SID` y que `To` sea `WHATSAPP_NUMERO_EMPRESA`. Si algo no cuadra, responde `200` sin
   efectos y registra solo el nombre del evento en el log.
3. Guarda el mensaje (`direccion=entrante`, `autor=cliente`, `estado=recibido`, sin conversación) y encola
   `whatsapp.procesar_entrante` con la clave `entrante:<id>`. Responde `200` con
   `<?xml version="1.0" encoding="UTF-8"?><Response/>`.
4. Un `MessageSid` repetido (reintento de Twilio) responde `200` sin crear nada.
5. El worker resuelve el registro de campaña, abre o reutiliza la conversación abierta del par
   cliente/empresa, aplica el opt-out determinista, enruta la conversación a la cola de atención y, si no hay
   ningún agente disponible, envía el aviso de espera.

Un mensaje entrante **nunca se rechaza** por cumplimiento: el cliente siempre puede escribir. Lo que
cumplimiento limita es lo que la empresa responde (sección 1.5).

Tipo del mensaje, en este orden: `boton` (hay `ButtonPayload`), `media` (hay adjuntos; el `Body` es el pie),
`texto` (hay `Body`) y `no_soportado` (ubicación, contacto, reacción…).

### 1.3 Mensaje saliente

- **Texto libre:** `POST /api/v1/conversaciones/{id}/mensajes`, solo dentro de la ventana de 24 h.
- **Plantilla:** `POST /api/v1/conversaciones/{id}/plantillas` (desde la bandeja) o
  `POST /api/v1/consola/registros/{id}/whatsapp/plantilla` (desde la ficha de la consola de voz).
- La API guarda el mensaje (`pendiente`, o `retenido` con `programado_para` si debe esperar a la franja) y
  encola `whatsapp.enviar_mensaje` con la clave `enviar:<id>`.
- El worker revalida el envío (sección 1.5), marca el mensaje `enviando`, confirma y llama a Twilio con
  `status_callback = PUBLIC_BASE_URL + /api/v1/whatsapp/webhooks/estado`.
- Si Twilio acepta el mensaje, se guarda su `MessageSid` y el estado pasa a `enviado`. Los estados de
  entrega llegan después por el webhook de estado.

### 1.4 Estados de los mensajes y de la entrega

Estados guardados en `mensajes.estado`:

| Estado | Significado |
|---|---|
| `recibido` | Entrante guardado, pendiente de que el worker lo asocie a una conversación. |
| `pendiente` | Saliente guardado, pendiente de envío. |
| `retenido` | Saliente programado para la próxima franja (`programado_para`). |
| `enviando` | El worker lo está enviando. Si queda así, el envío se da por incierto (sección 4.4). |
| `enviado` | Twilio lo ha aceptado (`MessageSid` guardado). |
| `entregado` | Twilio informa de entrega al dispositivo. |
| `leido` | Leído por el cliente. El estado `read` no siempre llega (privacidad del usuario). |
| `fallido` | No se envió o no se pudo entregar. Guarda `error_codigo`. |
| `cancelado` | No se envió porque la conversación se cerró antes (salvo la confirmación de baja) o por un opt-out. |

Estados de entrega que recibe el webhook (`MessageStatus` → estado):

| `MessageStatus` de Twilio | Estado |
|---|---|
| `accepted`, `scheduled`, `queued`, `sending`, `sent` | `enviado` |
| `delivered` | `entregado` |
| `read` | `leido` |
| `failed`, `undelivered`, `canceled` | `fallido` (con `ErrorCode`) |
| Otros (p. ej. `receiving`) | Se ignoran (`204`, sin efectos) |

**Orden monótono.** Los estados solo avanzan: `enviando` < `enviado` < `entregado` < `leido`. Un estado igual
o anterior no cambia el mensaje, pero el evento se guarda. `fallido` solo se aplica si el mensaje aún no está
`entregado` ni `leido`; así un `failed` tardío no tumba un mensaje ya entregado. Un evento repetido (mismo SID y
mismo estado) no tiene efecto.

**Estados antes del SID.** Si el estado llega antes de que el envío guarde el `MessageSid`, se guarda sin
enlazar y se aplica en orden en cuanto el SID se guarda.

**Códigos de error que ve el agente** (`error_codigo` y su texto en la bandeja, `conversaciones/salidas.py`):

| Código | Texto en la bandeja |
|---|---|
| `63016` | Fuera de la ventana de 24 h. |
| `63003` | El número no está disponible en WhatsApp. |
| `VENTANA_CERRADA` | La ventana de 24 h se cerró antes de enviar. |
| `CLIENTE_OPT_OUT` | El cliente pidió no recibir más mensajes. |
| `CONTACTO_NO_PERMITIDO` | El contacto ya no está permitido (exclusión o sin autorización). |
| `FUERA_DE_FRANJA` | La plantilla ya no se podía enviar: fuera de la franja horaria. |
| `PLANTILLA_NO_ENVIABLE` | La plantilla dejó de estar disponible antes de enviarse. |
| `ENVIO_INCIERTO` | No se pudo confirmar el envío; revise antes de reenviar. |
| `RESPUESTA_FUERA_DE_FRANJA` | La respuesta quedó fuera de la franja horaria permitida. |
| Cualquier otro | Error del proveedor (`<codigo>`). |

### 1.5 Ventana de 24 h, respuestas fuera de franja y revalidación

- **Ventana.** `ventana_expira_en` = último mensaje del cliente + 24 h. Sin mensajes del cliente no hay
  ventana: solo se pueden enviar plantillas.
- **Margen.** El texto libre exige `ahora < ventana_expira_en − WHATSAPP_MARGEN_VENTANA_SEGUNDOS` (60 s por
  defecto). Quedan 60 s o menos, la ventana se considera cerrada.
- **Texto fuera de ventana.** Al crearlo, `409 VENTANA_CERRADA`. Si la ventana se cierra mientras el mensaje
  espera en la cola, queda `fallido` con `VENTANA_CERRADA`.
- **Respuestas fuera de franja.** Se rigen por `entrantes.responder_fuera_de_franja` de la política
  (por defecto `true`, que responde en cualquier momento). Con `false`, la respuesta se retiene hasta la
  próxima franja si esa franja cae dentro de la ventana; si no cabe, `409 RESPUESTA_FUERA_DE_FRANJA`. La
  base legal sigue abierta (supuesto S-B1 de [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)).
- **Revalidación al enviar.** El worker vuelve a comprobar en el momento del envío lo que pudo cambiar desde
  que se creó el mensaje:
  - Texto de agente: opt-out posterior al último mensaje del cliente (`CLIENTE_OPT_OUT`) y franja
    (`retenido` de nuevo o `RESPUESTA_FUERA_DE_FRANJA`).
  - Plantilla: exclusión aplicable al canal (`CLIENTE_OPT_OUT` si es de la persona, `CONTACTO_NO_PERMITIDO`
    si es otra), autorización vigente, plantilla todavía enviable (`PLANTILLA_NO_ENVIABLE`) y franja y
    festivos (`FUERA_DE_FRANJA`). Si algo ya no se cumple, el mensaje queda `fallido` **sin llamar a Twilio**.
- **Automáticos** (confirmación de baja, aviso de espera, aviso de fuera de franja): son texto de
  `autor=sistema`. Se envían solo con ventana abierta y, al enviarse, la ventana se vuelve a comprobar como
  cualquier texto. No crean intentos de contacto.

### 1.6 Plantillas y su sincronización

Las plantillas se crean y se aprueban en Twilio/Meta (sección 2.5). La aplicación solo las lee y las
configura.

**Sincronizar** (`POST /api/v1/whatsapp/plantillas/sincronizar`, solo administrador). Lee la Content API
(`content.v1.content_and_approvals`) y hace un upsert por `content_sid`. Responde
`{ "creadas": n, "actualizadas": n, "desactivadas": n }`. Un error del proveedor responde
`502 PROVEEDOR_NO_DISPONIBLE`.

Reglas de la sincronización:

| Caso | Efecto |
|---|---|
| Plantilla nueva | Se crea con `activa=false`, sin finalidad y sin mapeo. |
| Cambia `cuerpo` o la lista de variables | Se vacía `mapeo_variables` y se desactiva. |
| Deja de estar `aprobada` | Se desactiva. |
| Es `marketing` y no tiene botón de baja | Se desactiva y se audita `whatsapp.plantilla_desactivada`. |
| Ya no existe en remoto | `estado_aprobacion=eliminada` y desactivada. |

`tiene_boton_baja` es verdadero si algún botón tiene `payload` igual a `WHATSAPP_PAYLOAD_BAJA` (por defecto
`BAJA`).

**Configurar** (`PUT /api/v1/whatsapp/plantillas/{id}`, administrador y supervisor). Campos opcionales
(`finalidad`, `mapeo_variables`, `activa`); cualquier otro campo se rechaza.

- `finalidad`: `venta`, `cobranza` o `todas`.
- `mapeo_variables`: las claves deben ser exactamente las variables de la plantilla (`"1"`, `"2"`…) y los
  valores, campos de la lista blanca: `primer_nombre`, `empresa`, `agente`, `producto`. Si no, `422
  PLANTILLA_MAPEO_INVALIDO` con el detalle `mapeo_variables.<clave>`.
- `activa=true` exige aprobada, finalidad y mapeo completo (`422 PLANTILLA_NO_DISPONIBLE`) y, si es
  `marketing`, botón de baja (`422 PLANTILLA_SIN_BAJA`).

Una plantilla es **enviable** si está activa, aprobada, tiene finalidad, mapeo completo y, si es marketing,
botón de baja. Solo las enviables aparecen para los agentes, y solo las de la finalidad de su campaña.

Valores de las variables (calculados en el servidor; nunca montos, saldos ni fechas de deuda):

| Campo | Valor |
|---|---|
| `primer_nombre` | Primera palabra del nombre del cliente. |
| `empresa` | `EMPRESA_NOMBRE`. |
| `agente` | Primera palabra del nombre del agente que envía. |
| `producto` | `producto` del registro de campaña. Si está vacío, `422 PLANTILLA_VARIABLE_VACIA`. |

### 1.7 Medios entrantes (proxy autenticado)

Un adjunto del cliente no se guarda en el servidor ni se expone al navegador. La URL de Twilio queda en la
base de datos y el navegador pide el archivo a la API:

`GET /api/v1/conversaciones/{id}/mensajes/{mensaje_id}/media/{indice}` (dueño de la conversación,
administrador o supervisor).

**Tipos aceptados** (`whatsapp/medios.py`). Cualquier otro tipo se guarda como `no_soportado` y no se
descarga.

| Categoría | Tipos de contenido |
|---|---|
| `imagen` | `image/jpeg`, `image/png`, `image/webp` |
| `audio` | `audio/ogg`, `audio/mpeg`, `audio/mp4`, `audio/aac`, `audio/amr` |
| `documento` | `application/pdf` |
| `no_soportado` | Todo lo demás (vídeo, vCard, Office, SVG…). |

**Validación de la URL antes de descargar (anti-SSRF y path traversal).** Debe cumplir todo esto:

- `https`, host `api.twilio.com`, sin puerto, sin credenciales, sin query ni fragmento y sin caracteres de
  control.
- Ruta exacta `/2010-04-01/Accounts/<TWILIO_ACCOUNT_SID>/Messages/MM…` con `/Media/ME…` opcional. Sin `.`,
  `..` ni codificaciones.

**Descarga.**

- Autenticación: Basic Auth con `TWILIO_API_KEY_SID` y `TWILIO_API_KEY_SECRET`, enviada solo a la URL válida
  de `api.twilio.com`.
- Sin redirecciones automáticas: se siguen a mano, como máximo dos saltos. Cada destino de redirección debe
  ser `https`, sin credenciales ni puerto, y su host debe ser `api.twilio.com` (con ruta válida) o uno de
  `WHATSAPP_HOSTS_MEDIOS`. Cualquier otro destino responde `404 MEDIA_NO_DISPONIBLE`. Las credenciales no
  viajan a un host que no sea la ruta válida de `api.twilio.com`.
- Límite de tamaño `WHATSAPP_MEDIA_MAX_BYTES` (16 MiB): `413 MEDIA_DEMASIADO_GRANDE`.
- Concurrencia `WHATSAPP_MEDIA_CONCURRENCIA` (4 por proceso): si se excede, `429 DEMASIADAS_DESCARGAS`.
- Duración máxima `WHATSAPP_MEDIA_DURACION_SEGUNDOS` (30 s) y timeouts de 10 s (5 s de conexión): `502
  PROVEEDOR_NO_DISPONIBLE`.
- `404` o `410` de Twilio → `404 MEDIA_NO_DISPONIBLE`. `429` o `5xx` → `502`.

**Respuesta.** El binario se devuelve tal cual, con `Content-Type` del tipo guardado,
`Content-Disposition: inline` (imagen y audio) o `attachment` (PDF), `X-Content-Type-Options: nosniff`,
`Cache-Control: private, no-store` y `Content-Security-Policy: sandbox; default-src 'none'`. Se audita
`whatsapp.media_ver` con ids y con el índice, sin datos personales.

> **Advertencia: host del redirect de medios sin verificar.** El valor por defecto de `WHATSAPP_HOSTS_MEDIOS`
> es `media.twiliocdn.com`. **No está verificado con una cuenta real** de Twilio. Si Twilio redirige la descarga
> a otro host, el adjunto dará `404 MEDIA_NO_DISPONIBLE` aunque la URL sea correcta. Para comprobarlo, con un
> adjunto real recibido en la base de datos (su `url_proveedor`), pida la cabecera `Location` sin seguir la
> redirección, por ejemplo con `curl -sS -D - -o /dev/null -u "$TWILIO_API_KEY_SID:$TWILIO_API_KEY_SECRET" "<url>"`
> **[verificar]**. Solo añada a `WHATSAPP_HOSTS_MEDIOS` el host que compruebe (https, sin puertos, separado
> por comas). Lo mismo ocurre con la política "Enforce HTTP Auth on Media URLs" de Twilio **[verificar]**.

### 1.8 Opt-out, autorización y exclusiones

Resumen (detalle en [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md), secciones 8 y 10):

- **Opt-out determinista** del texto del cliente (lista de frases y patrones) y del botón de baja
  (`ButtonPayload` igual a `WHATSAPP_PAYLOAD_BAJA`). Crea una exclusión `solicitud_titular`, revoca las
  autorizaciones de WhatsApp del número, cancela los salientes pendientes, envía la confirmación si hay
  ventana y cierra la conversación. Un "no me llamen" solo excluye la voz.
- **Opt-out manual** por el agente: `POST /api/v1/conversaciones/{id}/opt-out` con
  `{"alcance": "whatsapp" | "todos"}`.
- **Autorizaciones** (opt-in) por número, canal y finalidad. Son necesarias para enviar plantillas. Se
  registran desde la bandeja, desde la página Autorizaciones o desde la importación de clientes.

### 1.9 Cola y worker

Véase la sección 4.

---

## 2. Configuración de Twilio y Meta

> **[verificar]** Los nombres de menús y pantallas de Twilio y Meta cambian con el tiempo. Los pasos siguientes
> describen lo que necesita la aplicación; los nombres exactos de la consola deben confirmarse en una cuenta real.

### 2.1 Requisitos previos

- Cuenta de Twilio con su **Account SID** (`AC…`), una **API Key** (SID `SK…` y secreto) para la aplicación y el
  **Auth Token**. El Auth Token valida la firma de los webhooks, tanto de voz como de WhatsApp.
- Negocio **verificado** en Meta Business Manager, con una cuenta de WhatsApp Business (WABA) vinculada a
  Twilio, perfil completo y nombre visible aprobado.
- Un número `+57…` registrado como remitente de la API de WhatsApp (no usado en la aplicación de WhatsApp).
- Una URL pública HTTPS para la API (en desarrollo, un túnel).

### 2.2 Paso 1: remitente de WhatsApp

Registre el número como remitente de WhatsApp en Twilio **[verificar]**. Anote el número en formato E.164 y
póngalo en `WHATSAPP_NUMERO_EMPRESA`. El backend solo acepta mensajes cuyo `To` sea ese número.

### 2.3 Paso 2: URLs de webhooks

| Qué | URL exacta | Quién la llama | Cómo se configura |
|---|---|---|---|
| Mensaje entrante | `https://<host>/api/v1/whatsapp/webhooks/entrante#rc=3&rp=ct,rt,5xx` | Twilio, en `POST` | En el remitente, campo de la URL de mensajes entrantes **[verificar nombre del campo]**. |
| Estado de entrega | `https://<host>/api/v1/whatsapp/webhooks/estado` | El backend, en cada envío (`status_callback`) | No se configura a mano. |

- `<host>` es `PUBLIC_BASE_URL` sin barra final. Debe ser idéntica a la URL pública por la que Twilio llama.
- `#rc=3&rp=ct,rt,5xx` es una indicación para Twilio: reintentar ante errores de conexión, timeout o 5xx. El
  fragmento (`#…`) **no se envía al servidor ni se firma**. Lo recomienda [ADR-0019](arquitectura/adr-0019-whatsapp-bandeja-humana.md).
  Que Twilio lo respete **[verificar]**. Los reintentos son seguros: un `MessageSid` repetido no crea nada.
- Los webhooks no llevan JWT: la única autenticación es la firma de Twilio.

### 2.4 Paso 3: firma

- Twilio firma cada petición con `X-Twilio-Signature` (HMAC-SHA1 de la URL completa y de los parámetros del
  formulario, con el Auth Token).
- La API reconstruye la URL como `PUBLIC_BASE_URL + ruta + query`. Por eso `PUBLIC_BASE_URL` debe coincidir
  **exactamente** con la URL que Twilio usa. Causas típicas del `403 FIRMA_INVALIDA`:
  - `PUBLIC_BASE_URL` con `http://`, con barra final o con otro host (por ejemplo, el de un túnel que ya no es el
    mismo).
  - Un Auth Token rotado o copiado mal.
  - Un proxy que reescribe la URL antes de llegar a la API.
- La validación de firma tiene pruebas unitarias. Que la firma real pase a través del túnel **no está verificado**
  **[verificar]**.

### 2.5 Paso 4: plantillas y aprobación

1. Cree cada plantilla en la Content API de Twilio **[verificar]**, con las variables numeradas `{{1}}`, `{{2}}`…
2. Envíela a aprobación de WhatsApp (Meta). Categorías: `utility`, `marketing` o `authentication`.
3. **Marketing:** incluya un botón de respuesta rápida cuyo `payload` sea `BAJA` (o el valor de
   `WHATSAPP_PAYLOAD_BAJA`). Sin botón de baja, la plantilla no puede activarse (`PLANTILLA_SIN_BAJA`).
4. **Cobranza:** el contenido no debe incluir montos ni datos de la deuda. Es una decisión de producto y
   jurídica pendiente (ver [`pendientes.md`](pendientes.md), sección 6).
5. Cuando Meta la apruebe, ejecute **Sincronizar** (`POST /api/v1/whatsapp/plantillas/sincronizar`, administrador)
   y, en la página **Plantillas de WhatsApp**, asigne finalidad, mapeo de variables y actívela.

### 2.6 Paso 5: configuración de la aplicación

Ejemplo de `.env` para Twilio (valores inventados, sustitúyalos):

```bash
ENTORNO=produccion                              # o desarrollo, con PUBLIC_BASE_URL en https
PUBLIC_BASE_URL=https://api.ejemplo.co          # exacta, https, sin barra final
WHATSAPP_PROVEEDOR=twilio
WHATSAPP_NUMERO_EMPRESA=+573001234567           # remitente registrado
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...                           # no puede ser el valor de ejemplo fuera de test/desarrollo
TWILIO_API_KEY_SID=SK...
TWILIO_API_KEY_SECRET=...
WHATSAPP_HOSTS_MEDIOS=media.twiliocdn.com       # verificar con cuenta real (sección 1.7)
```

Con `WHATSAPP_PROVEEDOR=twilio` la aplicación **no arranca** si falta alguna de estas variables: `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` o `PUBLIC_BASE_URL`. El error lo indica. Con
`ENTORNO` distinto de `test`, `PUBLIC_BASE_URL` debe empezar por `https://`. `WHATSAPP_NUMERO_EMPRESA` debe estar
en E.164 con cualquier proveedor.

Si usa Docker Compose, el `.env` de la raíz llega a los servicios `backend` y `worker` mediante `env_file`
(requiere Docker Compose 2.24 o superior). Tras cambiar el `.env`, reinicie los servicios.

### 2.7 Paso 6: prueba de extremo a extremo

Compruebe, en este orden, con un móvil real y el remitente configurado:

1. Un mensaje del móvil aparece en **Bandeja** en la cola de atención, tras el procesamiento del worker.
2. Un agente lo toma y responde dentro de la ventana; el estado pasa a `entregado` y después a `leido`, si el
   cliente lo permite.
3. Una plantilla aprobada se envía fuera de ventana; aparece con su estado.
4. Un `STOP` cierra la conversación y deja la exclusión de WhatsApp.
5. Una imagen y un PDF se muestran en la conversación.
6. La firma es válida a través del túnel o del dominio público.

Estas pruebas están **pendientes**: no se han ejecutado con credenciales reales (QA las documenta como prueba manual
guiada).

---

## 3. Variables de entorno

Todas se leen en `backend/app/config.py` y se documentan en `.env.example`. Los rangos se validan al arrancar.

### 3.1 WhatsApp

| Variable | Por defecto | Rango o formato | Uso |
|---|---|---|---|
| `WHATSAPP_PROVEEDOR` | `falso` | `falso`, `twilio` | Proveedor. `falso` es el modo de desarrollo y pruebas. |
| `WHATSAPP_NUMERO_EMPRESA` | `+573000000001` | E.164 | Remitente de la empresa. Filtra los entrantes. |
| `WHATSAPP_MARGEN_VENTANA_SEGUNDOS` | `60` | 0 a 3600 | Margen antes del cierre de la ventana de 24 h. |
| `WHATSAPP_MEDIA_MAX_BYTES` | `16777216` | 1 KiB a 64 MiB | Tamaño máximo de un adjunto descargado. |
| `WHATSAPP_MEDIA_CONCURRENCIA` | `4` | 1 a 100 | Descargas de adjuntos simultáneas por proceso. |
| `WHATSAPP_MEDIA_DURACION_SEGUNDOS` | `30` | 5 a 300 | Duración total máxima de una descarga. |
| `WHATSAPP_HOSTS_MEDIOS` | `media.twiliocdn.com` | Hosts separados por comas | Hosts adicionales permitidos en redirecciones de medios. `api.twilio.com` siempre está permitido. **Sin verificar** (sección 1.7). |
| `WHATSAPP_DIAS_RESOLUCION_PLANTILLA` | `30` | 1 a 365 | Días en los que una plantilla enviada decide a qué registro pertenece un número. |
| `WHATSAPP_PAYLOAD_BAJA` | `BAJA` | Texto | `payload` del botón de baja de las plantillas. |
| `WHATSAPP_FRASES_OPT_OUT` | vacío | Frases separadas por `\|` | Sustituye la lista de opt-out de WhatsApp. Vacío = lista por defecto. |
| `WHATSAPP_FRASES_OPT_OUT_TODOS` | vacío | Frases separadas por `\|` | Sustituye la lista de opt-out de todos los canales. Vacío = lista por defecto. |
| `WHATSAPP_MENSAJE_OPT_OUT` | texto de ejemplo | máx. 1000 caracteres | Confirmación de baja de WhatsApp. Vacío la desactiva. |
| `WHATSAPP_MENSAJE_OPT_OUT_TODOS` | texto de ejemplo | máx. 1000 caracteres | Confirmación de baja de todos los canales. |
| `WHATSAPP_MENSAJE_ESPERA` | texto de ejemplo | máx. 1000 caracteres | Aviso de espera cuando no hay agentes disponibles. Vacío lo desactiva. |
| `WHATSAPP_MENSAJE_FUERA_DE_FRANJA` | texto de ejemplo | máx. 1000 caracteres | Aviso al retener una respuesta fuera de franja (una vez por conversación). Vacío lo desactiva. |
| `CONVERSACION_INACTIVIDAD_HORAS` | `24` | 1 a 168 | Horas sin mensajes tras las que se cierra una conversación. |
| `ATENCION_MAX_CONVERSACIONES_AGENTE` | `5` | 1 a 50 | Conversaciones abiertas simultáneas por agente. |

Los textos de los automáticos son de ejemplo y deben aprobarse (pendiente de negocio).

### 3.2 Twilio (compartidas con la voz)

| Variable | Por defecto | Uso con WhatsApp |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL pública exacta. Base de la firma y del `status_callback`. Sin barra final. |
| `TWILIO_ACCOUNT_SID` | vacío | Obligatoria con `twilio`. Se compara con el `AccountSid` de los entrantes. |
| `TWILIO_AUTH_TOKEN` | `token-falso-solo-desarrollo` | Firma de los webhooks. Fuera de `test` y `desarrollo` no puede estar vacía ni ser el valor de ejemplo. |
| `TWILIO_API_KEY_SID` | vacío | Obligatoria con `twilio`. Cliente REST y Basic Auth de medios. |
| `TWILIO_API_KEY_SECRET` | vacío | Obligatoria con `twilio`. |

### 3.3 Worker y purgas

| Variable | Por defecto | Rango | Uso |
|---|---|---|---|
| `WORKER_INTERVALO_SEGUNDOS` | `1` | 0.1 a 60 | Espera cuando no hay trabajos. |
| `WORKER_LOTE` | `10` | 1 a 100 | Trabajos que toma en cada vuelta. |
| `WORKER_BLOQUEO_SEGUNDOS` | `300` | 30 a 3600 | Tiempo que un trabajo queda reservado por un worker antes de poder retomarlo. |
| `PURGA_EVENTOS_HUERFANOS_DIAS` | `7` | 1 a 365 | Días tras los que se borran los estados que nunca se enlazaron a un mensaje. |

---

## 4. Worker

### 4.1 Arranque

**Con Docker Compose.** El servicio `worker` se levanta con el resto (`docker compose up -d`) y espera a que
`backend` esté sano (las migraciones las aplica `backend`).

```bash
docker compose up -d worker
docker compose logs -f worker                       # Ctrl+C para salir de los logs
docker compose exec worker python -m app.worker --healthcheck; echo $?   # 0 = sano
```

El servicio `worker` tiene `restart: unless-stopped`, `stop_grace_period: 30s` y un healthcheck que ejecuta
`python -m app.worker --healthcheck` cada 30 s.

**Sin Docker.** Desde `backend/`, con la base migrada (`alembic upgrade head`) y el `.env` configurado:

```bash
source .venv/bin/activate
python -m app.worker                                # bucle; Ctrl+C o SIGTERM para parar
python -m app.worker --healthcheck; echo $?         # 0 = hay latido de los últimos 60 s
```

El worker no necesita parámetros. La API y el worker deben apuntar a la **misma base de datos**.

**Varios workers.** Con PostgreSQL pueden ejecutarse varios a la vez: la toma de trabajos usa `FOR UPDATE SKIP
LOCKED` y cada trabajo se ejecuta una sola vez (probado con dos workers sobre 50 trabajos en PostgreSQL 16).
Con SQLite, use un solo worker.

**Identificador.** Cada proceso se identifica como `<hostname>-<pid>-<8 caracteres hexadecimales>`. Ese
sufijo aleatorio distingue cada arranque, también en contenedores que reinician con el mismo pid.

**Latido.** Cada vuelta y cada trabajo actualizan `latidos_worker`. `--healthcheck` sale con `0` si hay un
latido de los últimos 60 s, y con `1` si no. Un worker parado da `1` tras 60 s.

**Señales.** `SIGTERM` y `SIGINT` piden la parada: el trabajo en curso termina, los trabajos ya tomados y no
iniciados vuelven a `pendiente` sin gastar intento, y el proceso sale con `0`.

### 4.2 Trabajos que ejecuta

| Tipo | Quién lo encola | Clave única | Qué hace |
|---|---|---|---|
| `whatsapp.procesar_entrante` | Webhook entrante (o simulación) | `entrante:<mensaje_id>` | Resuelve el contexto, abre o reutiliza la conversación, aplica el opt-out, enruta y avisa de espera. |
| `whatsapp.enviar_mensaje` | Envío de texto o plantilla | `enviar:<mensaje_id>` | Revalida y envía a Twilio. Si el mensaje está retenido, se reprograma sin gastar intento. |
| `conversaciones.cerrar_inactivas` | Periódico | `periodico:…` | Cierra por inactividad cada 300 s (ver abajo). |
| `trabajos.purgar` | Periódico | `periodico:…` | Purga cada 24 h (ver abajo). |

Los payloads solo llevan ids y catálogos, nunca texto de mensajes ni números. `clave_unica` deduplica solo
mientras el trabajo está `pendiente`; al tomarlo, la clave se libera para que pueda llegar otro igual.

**Cierre por inactividad.** Cierra (motivo `inactividad`, sin tipificación) las conversaciones abiertas cuya
ventana ya expiró y que no tienen mensajes desde hace `CONVERSACION_INACTIVIDAD_HORAS`. Los mensajes
`pendiente` y `retenido` de esas conversaciones pasan a `cancelado`.

**Purgas** (`trabajos.purgar`):

| Qué borra | Cuándo |
|---|---|
| Trabajos `completado` o `cancelado` | Más de 7 días tras su última actualización. |
| Trabajos `fallido` | Más de 30 días tras su última actualización. |
| Latidos de workers | Más de 7 días. |
| Eventos de estado sin mensaje enlazado | Más de `PURGA_EVENTOS_HUERFANOS_DIAS` días. |

### 4.3 Reintentos, bloqueos y fallos

- **Intentos.** Cada trabajo tiene `max_intentos` = 5. Un fallo transitorio lo devuelve a `pendiente` con espera
  `5 s · 2^(intentos−1)`, con máximo de 600 s (5 s, 10 s, 20 s, 40 s…).
- **Transitorio:** `429` o `503` de Twilio, error de conexión previo al envío (`CONEXION`, por ejemplo DNS o
  conexión rechazada) y cualquier excepción no prevista (`INESPERADO`).
- **No transitorio:** otro error de Twilio (por ejemplo `63003`) o una excepción controlada no reintentable. El
  trabajo pasa a `fallido` en el primer intento.
- **Agotado:** tras `max_intentos`, o cuando un trabajo ha tomado más veces de su máximo (está matando al
  worker), pasa a `fallido`. Se audita `trabajo.fallido` y se emite el evento `trabajo.fallido` con
  `{trabajo_id, tipo, codigo}`. Para los envíos, el mensaje también pasa a `fallido`.
- **Bloqueo.** Mientras un worker ejecuta un trabajo, lo reserva `WORKER_BLOQUEO_SEGUNDOS`. Si el worker muere,
  al caducar la reserva otro worker puede retomarlo.
- **Liberación de instancias muertas.** Cada 30 s y al arrancar, el worker devuelve a la cola los trabajos
  reservados por instancias **del mismo host exacto** que llevan más de 60 s sin latido y cuya reserva ya ha
  caducado. Nunca toca los de un worker vivo, ni los de otro host con un nombre parecido.

### 4.4 Envío "como mucho una vez" y `ENVIO_INCIERTO`

El envío sigue este orden:

1. Transacción 1: el worker revalida, marca el mensaje `enviando` y **confirma antes** de llamar a Twilio.
2. Llamada a Twilio.
3. Transacción 2: si Twilio acepta, guarda el `MessageSid` y el estado pasa a `enviado`.

Si el proceso muere entre el paso 1 y el 3, el mensaje queda `enviando`. El sistema **no reenvía**: cuando un
reintento lo encuentra en `enviando`, o cuando el trabajo se agota en ese estado, el mensaje pasa a
`fallido` con `error_codigo = ENVIO_INCIERTO`. Un error transitorio que ocurre **antes** de que Twilio
acepte (429, 503, conexión) sí se reintenta, porque el mensaje no salió.

**Qué debe hacer un agente ante `ENVIO_INCIERTO`:**

1. **No reenviar en automático.** La bandeja muestra "No se pudo confirmar el envío; revise antes de reenviar".
2. **Comprobar si el cliente lo recibió**, preguntándole. El sistema no guarda un identificador de Twilio para ese
   mensaje, así que la búsqueda en el registro de mensajes de Twilio solo puede hacerse por número y hora
   **[verificar]**.
3. **Si no llegó,** puede enviar un mensaje nuevo: es un envío distinto, con su propia clave de idempotencia.
   Una plantilla nueva vuelve a pasar todas las comprobaciones de cumplimiento.
4. **Si se repite,** avise a un supervisor: puede haber un problema de red o del worker. El supervisor puede
   consultar `GET /api/v1/supervision/trabajos` (sección 4.5).

El intento de contacto de una plantilla se registra al crearla (ver
[`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)). Si el envío después falla o se cancela, el intento
ya consta.

### 4.5 Supervisión del worker

`GET /api/v1/supervision/trabajos` (administrador y supervisor) devuelve:

- `trabajadores`: workers con latido en la última hora. `activo` es `true` si el latido tiene 60 s o menos.
- `por_estado`: número de trabajos por tipo y estado.
- `fallidos_recientes`: hasta 20 trabajos fallidos de las últimas 24 horas (`id`, `tipo`, `ultimo_error`,
  `intentos`, `actualizado_en`).

La página **Supervisión** muestra la tarjeta de estado del worker. Si no hay ningún worker activo, aparece un aviso.

### 4.6 Limitaciones

- Con **SQLite** el worker no entrega eventos de tiempo real a la API (su bus vive en el proceso del worker). Con
  **PostgreSQL** sí, mediante `pg_notify`.
- Cada worker ejecuta sus trabajos en serie.
- La importación de clientes sigue siendo síncrona y no usa la cola (pendiente).

---

## 5. Simulación (solo fuera de producción)

La simulación exige **`WHATSAPP_PROVEEDOR=falso` y `ENTORNO` distinto de `produccion`**. Si no se cumple, las rutas
de simulación no se registran y responden `404`. Con `WHATSAPP_PROVEEDOR=twilio` no existe ninguna.

**Endpoints** (cualquier usuario autenticado con JWT):

- `POST /api/v1/whatsapp/simulacion/entrante`: simula un mensaje del cliente. Ejecuta el mismo servicio que el
  webhook.

  ```json
  { "numero": "3001234567", "texto": "Hola", "nombre_perfil": "María",
    "media": [ { "tipo_contenido": "image/png" } ], "boton_payload": null, "boton_texto": null }
  ```

  Respuesta `200`: `{ "mensaje_id": 101, "proveedor_id": "SMsim…" }`. El procesamiento lo hace el worker.

- `POST /api/v1/whatsapp/simulacion/mensajes/{mensaje_id}/estado`: simula el estado de un saliente.

  ```json
  { "estado": "delivered", "error_codigo": "63016" }
  ```

  `estado` admite `delivered`, `read`, `failed` y `undelivered`. Respuesta `204`. `404` si el mensaje no tiene
  `MessageSid`.

Ejemplo completo con `curl` (cambie las credenciales):

```bash
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@empresa.co","password":"su-contraseña"}' | python -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -sS -X POST http://localhost:8000/api/v1/whatsapp/simulacion/entrante \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"numero":"3001234567","texto":"Hola, quiero información"}'
```

**Reglas del proveedor falso** (`integraciones/whatsapp/falso.py`):

- El envío no sale a la red. Los mensajes quedan en memoria del proceso.
- Un destino que termina en `0000` responde el error permanente `63003` (sin reintentos).
- Un destino que termina en `9999` responde el error transitorio `429` (reintenta con espera y, tras 5
  intentos, queda `fallido`).
- Plantillas fijas: `HXfalso0001` `recordatorio_cobranza` (utility, aprobada), `HXfalso0002` `oferta_venta`
  (marketing, aprobada, con botón `BAJA`), `HXfalso0003` `seguimiento` (utility, pendiente) y `HXfalso0004`
  `marketing_sin_baja` (marketing, aprobada, sin botón).
- Los adjuntos simulados se sirven desde `https://media.falso.invalid/…`: `image/*` (PNG de 1×1), `audio/*` (OGG
  mínimo) y `application/pdf` (PDF mínimo). Una URL con `/grande/` responde `413`.

**Simulador en la interfaz.** La página **Simulador WhatsApp** (`/whatsapp/simulador`) aparece en el menú solo
si `GET /api/v1/whatsapp/configuracion` devuelve `simulacion: true`. Tiene dos secciones: **Enviar como cliente**
(número, texto, adjunto simulado y botón de baja) y **Cambiar el estado de los mensajes salientes** de una
conversación.

---

## 6. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `403 FIRMA_INVALIDA` en el webhook de entrada | `PUBLIC_BASE_URL` distinta de la URL que Twilio llama (http, barra final, otro host de túnel), o Auth Token incorrecto. | Compare `PUBLIC_BASE_URL` con la URL del remitente. Revise el token. Reinicie el backend tras cambiar el `.env`. |
| Un mensaje del cliente no aparece en la bandeja | El worker no está procesando, o el mensaje no pasó la comprobación de cuenta o número. | Compruebe `--healthcheck` y los logs del worker. Los avisos son solo nombres de evento: `whatsapp.entrante_cuenta_ajena`, `whatsapp.entrante_numero_ajeno`, `whatsapp.entrante_invalido`. |
| El entrante está en `recibido` y no pasa a una conversación | El worker no está en marcha, o no puede conectarse a la base de datos. | Arranque el worker (sección 4.1). El trabajo se reintenta solo. |
| `docker compose` no levanta `worker` | `backend` no está sano todavía (migraciones) o el healthcheck falla. | Mire `docker compose logs backend`. Espere al estado `healthy`. |
| `--healthcheck` devuelve `1` | No hay latido en 60 s: el worker está parado o no llega a la base de datos. | Revise `docker compose logs worker` o el proceso local. |
| Texto rechazado con `409 VENTANA_CERRADA` | Pasaron más de 24 h desde el último mensaje del cliente, o quedan menos de 60 s. | Use una plantilla aprobada. |
| Texto rechazado con `409 RESPUESTA_FUERA_DE_FRANJA` | `responder_fuera_de_franja=false` y la próxima franja cae fuera de la ventana. | Use una plantilla dentro de la franja. |
| Un mensaje queda `retenido` | Respuesta fuera de franja con `responder_fuera_de_franja=false`. | Se envía solo en la franja. La conversación muestra el aviso de mensajes retenidos. |
| Error `63016` del proveedor | Fuera de la ventana de 24 h. | Use una plantilla. |
| Error `63003` del proveedor | El número no está disponible en WhatsApp (no tiene cuenta o no acepta mensajes del remitente). No reintentable. | Pida al agente que verifique el número. No insista con el mismo número. |
| `429` o `503` del proveedor | Límite o indisponibilidad de Twilio. Transitorio. | El worker reintenta con espera. Si se agotan, el mensaje queda `fallido` con el código. |
| `ENVIO_INCIERTO` | El worker murió durante un envío, o el envío se agotó en ese estado. | Sección 4.4. |
| `POST .../plantillas/sincronizar` devuelve `502` | Error al consultar la Content API. | Compruebe la API Key y los permisos de la cuenta. Reintente. |
| Una plantilla no se puede activar (`PLANTILLA_NO_DISPONIBLE`) | No aprobada, sin finalidad o con mapeo incompleto. | Revise el estado de aprobación y el mapeo. |
| Una plantilla no aparece para un agente | No es enviable, o es de otra finalidad. | Revise la finalidad de la campaña y el estado de la plantilla. |
| Un adjunto da `404 MEDIA_NO_DISPONIBLE` | Tipo no soportado (`no_soportado`), URL fuera del formato válido, o la redirección va a un host no permitido. | Sección 1.7: revise `WHATSAPP_HOSTS_MEDIOS` tras comprobarlo con la cuenta real. |
| Un adjunto da `413 MEDIA_DEMASIADO_GRANDE` | Supera `WHATSAPP_MEDIA_MAX_BYTES`. | Subir el límite dentro del rango, o informar al cliente. |
| Un adjunto da `429 DEMASIADAS_DESCARGAS` | Hay más descargas simultáneas que `WHATSAPP_MEDIA_CONCURRENCIA`. | Reintente en unos segundos. |
| Un adjunto da `502 PROVEEDOR_NO_DISPONIBLE` | Timeout, error 5xx o descarga demasiado lenta. | Reintente. Si es persistente, revise la conectividad con Twilio. |
| Los eventos en tiempo real no llegan (desarrollo) | SQLite: el bus del worker no llega a la API. | Use PostgreSQL (sección 4.6). |
| La configuración no arranca | Una variable obligatoria falta o está fuera de rango. | El mensaje de error indica la variable. Sección 2.6 y sección 3. |
| Una variable del `.env` llega con un valor extraño al contenedor | Comentario en la misma línea de una variable sin valor: Compose lo toma como valor. | Escriba el comentario en su propia línea, o use una variable con valor no vacío (`.env.example`). |
</content>
