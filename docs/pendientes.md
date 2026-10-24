# Pendientes y decisiones para próximas fases

Deuda técnica, supuestos sin confirmar y validaciones pendientes tras la Fase 1. El detalle de riesgos
de cada fase está en `docs/arquitectura/fase-1.md` (§7) y en `docs/arquitectura/README.md` (§9).

---

## 1. Validación legal pendiente

Las normas del motor de cumplimiento se contrastaron **solo mediante búsquedas web**. Ningún abogado las
ha revisado. Hasta que el área jurídica del cliente las confirme, las reglas deben tratarse como
configurables y no como definitivas (ver `docs/arquitectura/README.md`, §10).

- **Frecuencia de la Ley 2300 de 2023**:
  - ¿"semana" es la semana calendario o una ventana móvil de 7 días?
  - ¿Cuentan los intentos sin contacto directo o solo los contactos?
  - ¿Aplica igual a ventas que a cobranza?
  - Desde la subfase 2A la frecuencia **se evalúa** en cada llamada, con las lecturas de S-A1 (ver
    [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)). Las lecturas siguen sin validar por el área
    jurídica, y deben cerrarse antes de la Fase 3.
- **Excepción de horario por autorización del consumidor**: ¿se gestionará en la plataforma? ¿cómo se
  acredita el documento de autorización? Afecta a la fase 3.
- **RNE para clientes con relación contractual**: ¿las ofertas a clientes actuales son comerciales y
  están sujetas al RNE? Por defecto se asume que sí (criterio más restrictivo).

---

## 2. Supuestos a confirmar con negocio

Se adoptaron como supuestos de la Fase 1 (fase-1.md, §7, S1 a S3). Pueden cambiarse después con coste bajo.

- **Documento obligatorio también en venta.** El documento (`tipo_documento` + `numero_documento`) es la
  clave del cliente global y de los límites de frecuencia entre campañas. Si las bases de venta llegan
  sin documento, la alternativa es usar `telefono_1` normalizado como clave (cambio acotado al servicio
  de importación).
- **Un registro por cliente y campaña.** `UNIQUE(campana_id, cliente_id)`. Un deudor con varias
  obligaciones en la misma campaña conserva solo la primera fila; las demás cuentan como duplicadas.
  Si el negocio necesita varias obligaciones, habrá que añadir una tabla `obligaciones` en la fase 2.
- **RNE cargado por CSV.** Las exclusiones RNE se cargan desde un CSV exportado de la plataforma de la
  CRC (consulta manual, lotes de hasta 10 000 números). La integración con el webservice queda para la
  fase 5.

---

## 3. Seguridad (fase 2)

- Límite de intentos de login (hoy no hay limitación por usuario ni por IP).
- Revocar los tokens de acceso al cambiar la contraseña (hoy los JWT siguen válidos hasta su expiración;
  solo se invalida el acceso si el usuario se desactiva, porque el rol y el estado se leen de BD).
- Carrera que puede dejar el sistema sin administradores activos (dos desactivaciones simultáneas).
- Refresh tokens y cookies `httpOnly`, y una política de seguridad de contenido (CSP). Hoy el token va en
  `sessionStorage`.
- `connection: close` tras la respuesta 413, para no reutilizar una conexión con un cuerpo cortado.
- Registrar la cadena de excepciones (`__cause__`) sin datos personales. Hoy solo se registran el tipo y
  las líneas del traceback (`registrar_error_interno`).
- Unicidad del nombre de campaña sin distinguir mayúsculas, con `lower(nombre)` en BD. Hoy la unicidad
  está en `nombre` tal cual.

---

## 4. Otros

- **Mensajes 422 de Pydantic en inglés.** Los tipos de error no mapeados (`errores.py`,
  `_MENSAJES_TIPO`) devuelven el mensaje original de Pydantic. Solo `missing` y `extra_forbidden` tienen
  traducción.
- **`telefonos.py` acepta texto pegado.** Extrae todos los dígitos, así que `tel 3001234567` se acepta.
  Puede ser deseable o no; decidir si la importación debe ser estricta.
- **Contraseñas truncadas a 72 bytes.** bcrypt solo considera los primeros 72 bytes. Se trunca de forma
  explícita en `seguridad.py`, pero dos contraseñas que comparten esos 72 primeros bytes son equivalentes.
  Valorar un pre-hash (p. ej. SHA-256 antes de bcrypt) o limitar la longitud en los esquemas.
- **Zona horaria fija en el evaluador del frontend.** La hora del evaluador se interpreta siempre como
  `-05:00` (`frontend/src/utilidades/formato.ts`, `OFFSET_BOGOTA`), sin importar la zona del navegador.
  Si el sistema se usa en otra zona, habrá que parametrizarlo.
- **La imagen Docker instala también dependencias de desarrollo.** `backend/requirements.lock` incluye
  `pytest`, `ruff` y `httpx`. Separar un lock de producción.
- **Volumen `./backend:/app` con usuario `app` (uid 1000).** Si el uid del host no es 1000, el contenedor
  puede no tener permiso para escribir en `./backend` (p. ej. `.pytest_cache` o `.coverage` al ejecutar tests).
- **Migración `0001` editada tras crearse.** Si existía un volumen `pgdata` creado con la versión anterior,
  bórrelo antes de arrancar (`docker compose down -v`).
- **Tests de PostgreSQL real y `docker compose up` no ejecutados en CI.** El repositorio no tiene
  configuración de CI. El test de migraciones contra PostgreSQL (`pytest -m postgres`) requiere
  `TEST_DATABASE_URL` y no se ha ejecutado en un pipeline.
- **E2E de Playwright no incluido en el repositorio.** Las pruebas de interfaz usan Vitest y Testing
  Library con `fetch` simulado.
- **Importación síncrona hasta 50 000 filas.** La petición bloquea el proceso durante toda la importación.
  Si las bases son mayores, pasar a procesamiento en segundo plano con estado `procesando` (fase 2).

---

## 5. Subfase 2A: pendientes de telefonía, consola y tiempo real

Pendientes técnicos y de validación de la subfase 2A (consola del agente con voz Twilio). Lo que no se pudo
validar en el repositorio, sin Twilio real, aparece aquí con su alcance.

- **Desconexión por inactividad no es multiinstancia.** El temporizador de `CONSOLA_DESCONEXION_SEGUNDOS` (60 s)
  y el registro de sockets viven en la memoria de cada proceso de la API. Con varias instancias, un agente puede
  seguir conectado por otra instancia y no pasar a `desconectado`, o al revés. Hace falta un registro compartido
  (por ejemplo, la tabla de estado con latido) antes de escalar la API.
- **Validar con Twilio real la «contestada prematura».** La regla S2 (`completed` con `DialCallDuration > 0`
  cuenta como contestada aunque no llegue `answered`) no se ha probado con tráfico real. Ver
  [`telefonia-twilio.md`](telefonia-twilio.md), sección «Estados de la llamada».
- **Validar con Twilio real el softphone sin `register()`.** El navegador no llama a `device.register()` porque
  el token lleva `incoming_allow = False`. Comprobar que las llamadas salientes funcionan así en un navegador real
  y que los eventos `tokenWillExpire` renuevan el token sin cortar una llamada.
- **Acción de supervisor para forzar tipificación o liberar un registro.** Hoy solo el procedimiento de soporte
  `python -m app.cli liberar-gestion` lo hace (ver [`consola-agente.md`](consola-agente.md), sección 10). Una
  acción de supervisor en la interfaz llega en la subfase 2F.
- **Filtrar los eventos `consola.registro` por asignación.** Hoy cada agente recibe todos los eventos
  `consola.registro` (solo traen ids, pero revelan actividad de otras campañas). Filtrarlos por campañas asignadas
  llega en la subfase 2F.
- **Validación con Twilio real de la firma a través del túnel y del aviso de grabación.** Comprobar que la firma
  válida pasa con la URL pública exacta, que el aviso de grabación se oye antes de unir al agente y que la
  grabación dual se guarda. Ver [`telefonia-twilio.md`](telefonia-twilio.md), apartados «Firma de los webhooks» y «Configuración de Twilio paso a paso» (paso 7).
- **`docker-compose.yml` no pasa las variables de telefonía.** Ninguna de las `TELEFONIA_*`, `TWILIO_*`,
  `PUBLIC_BASE_URL`, `CONSOLA_*`, `PROMESA_MAX_DIAS`, `WS_REVALIDAR_SEGUNDOS` ni `BUS_EVENTOS` está en el servicio
  `backend`. Con Docker no llegan al contenedor aunque estén en el `.env` de la raíz. Añadirlas a `environment`.
  La subfase 2A no modificó `docker-compose.yml`.
- **Aviso de grabación ligado a `TELEFONIA_GRABAR`.** Con `TELEFONIA_GRABAR=false` no hay aviso. Decidir con el área
  jurídica si el aviso debe existir con independencia de la grabación. Ver
  [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md), sección 9.
- **Verificar `liberar-gestion` contra su comportamiento final.** La guía
  ([`consola-agente.md`](consola-agente.md), sección 10) describe el comportamiento acordado: umbral de 3600 s,
  restricción a `no_contesta` o `numero_errado` en llamadas atascadas, transacción única. Revisar `backend/app/cli.py`
  tras el ajuste.
- **Documentación de arquitectura desactualizada.** ADR-0003 dice `incoming_allow=true` y la implementación usa
  `False` en 2A. ADR-0017 menciona `GET /api/v1/ws?token=` y la revisión B3 lo sustituyó por tickets
  (`POST /api/v1/ws/ticket`). Los documentos de `docs/` siguen el código. Corregir los ADR es tarea del arquitecto.
- **Tiempos del WebSocket.** `WS_REVALIDAR_SEGUNDOS` (60) y la cola de 1000 eventos por conexión son valores sin
  prueba de carga. Medir con varias conexiones (subfase 2F).

---

## 6. Negocio y requisitos externos (subfases 2B a 2F)

Preguntas de negocio y técnicas de [`fase-2.md`](arquitectura/fase-2.md) §8, que no bloquean la subfase 2A. Las
preguntas legales están en [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md), sección 10.

**Negocio**

- **Reglas de negociación por campaña** (descuentos, cuotas, plazos, mínimos) y catálogo de ofertas con precios.
  ¿Quién las aprueba?
- **Presupuesto de IA** por campaña y mes, y modelo y esfuerzo por defecto (Opus 5.5 `medium` frente a Sonnet o
  Haiku por coste). Subfase 2C.
- **Horario y dotación de agentes humanos** para la cola de traspaso, con su SLA. Subfase 2C.
- **Varias obligaciones por cliente** en la misma campaña (S2 de Fase 1). Afecta a `consultar_obligacion`.
- **Notas de voz** de WhatsApp: ¿se transcriben en una fase futura? Hoy se pide texto o se deriva. Subfase 2C.

**Autonomía del agente IA** (subfase 2C). Legal y de negocio a la vez:

- ¿Puede un agente IA celebrar acuerdos de pago y ventas vinculantes? ¿Qué constancia se exige (mensaje de
  constancia del servidor, aceptación con cita literal, conservación de la transcripción)?
- ¿Derecho de retracto en ventas a distancia (Ley 1480) y cómo se informa?

**WhatsApp** (subfases 2B, 2D y 2E). Requisitos de negocio y de Meta:

- Contenido de plantillas de cobranza (sin montos por defecto) y la frontera de lo que puede decir el primer
  contacto.
- Calidad del número y bloqueos por reportes de spam.
- Requisitos del permiso de llamada (2E). La duración del permiso y cómo notifica Twilio la respuesta del usuario
  no están confirmadas: las fuentes discrepan (72 horas frente a 7 días). Verificar al iniciar 2E.

**Requisitos externos para operar con Twilio real (2A)**

- Cuenta Twilio sin *trial*, API Key y Secret, y TwiML App configurada (ver [`telefonia-twilio.md`](telefonia-twilio.md)).
- Número de voz `+57` con su paquete regulatorio aprobado para Colombia, o caller ID verificado. Confirmar que el
  caller ID cumple lo que exija la CRC.
- URL pública HTTPS para webhooks (túnel en desarrollo) y `PUBLIC_BASE_URL` exacta.
- Texto del aviso de grabación aprobado por el área jurídica.
- Tarifa por minuto a móviles y fijos de Colombia.

**Requisitos externos para 2B a 2E**

- **Meta:** portafolio de negocio verificado; cuenta de WhatsApp Business vinculada a Twilio; remitente `+57`
  registrado (no usado en la aplicación de WhatsApp); nombre visible aprobado; perfil completo; método de pago.
- **Plantillas** creadas y aprobadas (Content API) por categoría (marketing o utility). Las de marketing llevan
  botón de baja. Plantilla de solicitud de permiso de llamada (2E).
- **Límite de mensajería** del portafolio adecuado al volumen. Para llamadas de WhatsApp salientes (2E), al menos
  2 000 por 24 horas. Calidad del número.
- **Twilio:** remitente de WhatsApp habilitado; webhooks de mensajería (entrante y estado) apuntando a
  `PUBLIC_BASE_URL`; TwiML App asignada al remitente para llamadas (2E).
- **Anthropic:** organización o workspace; `ANTHROPIC_API_KEY` como secreto; límites de tasa del nivel contratado;
  acuerdo de tratamiento de datos y, si está disponible, retención cero.
- **Precios** oficiales de Meta para Colombia. Según fuentes secundarias, marketing ≈ US$0,0125 y utility ≈ US$0,0008.
  Desde octubre de 2026 también se cobran servicio y utility dentro de la ventana. Más US$0,005 por mensaje de Twilio.
  Verificar contra las tarifas oficiales.

**Técnicos**

- Exactitud de la guarda de montos del agente IA (falsos positivos). Medir en la evaluación de 2C.
- `LISTEN/NOTIFY` con varias instancias de la API. El worker necesitará su propio healthcheck (2B).
- Importación síncrona (hasta 50 000 filas). Si las bases crecen, pasarla a la cola de trabajos de 2B.
- Deuda de seguridad de Fase 1 (sección 3) programada en 2F. Si la plataforma se expone a Internet antes, adelantar
  el límite de intentos de login.
