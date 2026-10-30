# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Unreleased]

### Añadido

Subfase 2B: WhatsApp con Twilio y bandeja humana.

- Proveedor de WhatsApp tras la interfaz `ProveedorWhatsApp`, con implementación de Twilio (mensajes, Content API y
  medios) y una falsa para desarrollo. Se elige con `WHATSAPP_PROVEEDOR`.
- Webhooks firmados: entrante (`POST /api/v1/whatsapp/webhooks/entrante`) y estado de entrega
  (`POST /api/v1/whatsapp/webhooks/estado`). Son idempotentes: un `MessageSid` repetido no crea nada.
- Cola de trabajos en la base de datos (tabla `trabajos`) y worker `python -m app.worker`, con latido, `--healthcheck`,
  reintentos con espera exponencial, recuperación de bloqueos y purgas periódicas. Servicio `worker` en
  `docker-compose.yml`. Guía: `docs/whatsapp-twilio.md`.
- Conversaciones y mensajes con resolución determinista del registro de campaña, ventana de 24 h y estados de entrega
  monótonos (`enviado`, `entregado`, `leido`, `fallido`).
- Bandeja humana (`/bandeja`): cola de atención, tomar siguiente, tomar, asignar, liberar, respuesta de texto dentro de
  la ventana, plantilla fuera de ella, vincular registro, cerrar con tipificación y ficha del cliente. Capacidad máxima
  por agente (`ATENCION_MAX_CONVERSACIONES_AGENTE`).
- Plantillas de WhatsApp (`/whatsapp/plantillas`): sincronización desde la Content API, mapeo de variables a una lista
  blanca, finalidad y activación.
- Autorizaciones de WhatsApp (opt-in, `/autorizaciones`): alta con evidencia, revocación y registro desde la
  conversación. Importación con las columnas `autoriza_whatsapp` y `fecha_autorizacion_whatsapp`.
- Opt-out determinista (listas de frases, patrones y botón de baja) y manual, con alcances `whatsapp`, `todos` y `voz`.
- Exclusiones por canal (`todos`, `voz` o `whatsapp`) en la API, en la carga de archivos y en la página de Exclusiones.
- Medios entrantes por proxy autenticado (`GET /api/v1/conversaciones/{id}/mensajes/{mensaje_id}/media/{indice}`), sin
  almacenar el binario.
- Plantilla individual desde la ficha de la consola (`POST /api/v1/consola/registros/{id}/whatsapp/plantilla`) e
  insignia de WhatsApp por teléfono.
- Simulador de WhatsApp fuera de producción (`/api/v1/whatsapp/simulacion/*` y la página `/whatsapp/simulador`).
- Tiempo real: eventos `conversacion.mensaje`, `conversacion.estado`, `atencion.cola` y `trabajo.fallido`. Estado del
  worker en Supervisión (`GET /api/v1/supervision/trabajos`).
- Campañas con `whatsapp_habilitado` y `plantilla_inicial_id`.
- Migración `0003_whatsapp_bandeja`.
- Variables de entorno `WHATSAPP_*`, `WORKER_*`, `PURGA_EVENTOS_HUERFANOS_DIAS`, `CONVERSACION_INACTIVIDAD_HORAS` y
  `ATENCION_MAX_CONVERSACIONES_AGENTE`.
- Documentación: `docs/whatsapp-twilio.md` (configuración, worker y solución de problemas) y `docs/bandeja-whatsapp.md`
  (guía para agentes y supervisores).

Subfase 2A: consola del agente humano con voz Twilio.

- Asignación de agentes a campañas (`GET/PUT /api/v1/campanas/{id}/agentes`) y pestaña **Agentes** del detalle de campaña.
- Estado del agente con máquina de estados en el servidor, historial y transiciones automáticas (en llamada,
  tipificando, desconectado tras 60 s sin WebSocket). Endpoints `GET/PUT /api/v1/consola/estado`.
- Lista de trabajo con reservas de registro de 15 minutos (`CONSOLA_RESERVA_MINUTOS`), que se renuevan durante la
  llamada. Ficha del cliente con teléfonos enmascarados, guion renderizado y cumplimiento en vivo.
- Llamadas manuales desde un softphone de Twilio (`@twilio/voice-sdk`) o uno falso. El servidor valida cada llamada
  y resuelve el número antes del `<Dial>`. Las llamadas bloqueadas guardan sus motivos y se muestran en la consola.
- Aviso de grabación al cliente y grabación dual. Webhooks de estado, grabación y fin de llamada, todos con firma de
  Twilio. Guía: `docs/telefonia-twilio.md`.
- Endpoints de simulación para desarrollo sin credenciales (`/api/v1/telefonia/simulacion/*`). Solo existen con el
  proveedor falso y fuera de producción.
- Tipificaciones (`contactado`, `no_contesta`, `numero_errado`, `promesa_pago`, `venta`, `rechazo`,
  `volver_a_llamar`) con sus efectos: promesas, ventas, exclusión por número errado y rellamada. Listado por
  campaña con filtros en `GET /api/v1/campanas/{id}/tipificaciones`.
- Frecuencia de contacto de la Ley 2300 evaluada en el servidor (motor puro): máximo de contactos por día, máximo de
  medios por semana y umbral de contacto directo. Guía: `docs/cumplimiento-frecuencia.md`.
- Supervisión en vivo de agentes (`GET /api/v1/supervision/agentes`) y página de Supervisión.
- Tiempo real: WebSocket `GET /api/v1/ws?ticket=…` con un bus de eventos (`LISTEN/NOTIFY` en PostgreSQL, memoria en
  SQLite) y reconexión automática en el cliente.
- Importación de clientes y de exclusiones desde Excel `.xlsx` (primera hoja; sin macros ni fórmulas recalculadas).
- Procedimiento de soporte `python -m app.cli liberar-gestion` (tipifica como sistema una llamada atascada).
- Migración `0002_consola_y_voz`: asignaciones, estados de agente, historial, intentos de contacto, llamadas, eventos,
  grabaciones, tipificaciones, promesas, ventas y tickets de WebSocket.
- Documentación: `docs/telefonia-twilio.md`, `docs/consola-agente.md` y `docs/cumplimiento-frecuencia.md`.

Fase 1 de la plataforma de campañas outbound.

- Esqueleto del proyecto: backend FastAPI (`backend/`), frontend React + TypeScript + Vite (`frontend/`),
  `docker-compose.yml` con PostgreSQL 16 y migraciones Alembic (migración `0001_esquema_inicial`).
- Autenticación con JWT HS256 y roles `administrador`, `supervisor` y `agente`. Endpoints
  `POST /api/v1/auth/login` y `GET /api/v1/auth/me`. El rol y el estado se leen de la base de datos en
  cada petición. Contraseñas con bcrypt.
- Gestión de usuarios (solo administrador): listar, crear, editar rol, activar/desactivar y restablecer
  contraseña.
- Campañas de tipo `venta` o `cobranza` con máquina de estados (`borrador`, `activa`, `pausada`,
  `finalizada`), listado con filtros y paginación, y eliminación solo en borrador.
- Importación de clientes desde CSV a una campaña: normalización de teléfonos a E.164 (+57, móviles y
  fijos colombianos), deduplicación en archivo y en campaña, exclusiones por tipo de campaña, resumen de
  conteos y listado paginado de errores. Ver `docs/importacion-csv.md`.
- Listado de clientes de una campaña con sus teléfonos y marca de exclusión.
- Exclusiones de números por finalidad (`rne`, `solicitud_titular`, `numero_errado`, `manual`): alta,
  listado, eliminación y carga masiva desde CSV. Un RNE se asigna por defecto a `venta`.
- Cumplimiento: políticas versionadas por tipo de campaña (franjas horarias L-V 07:00-19:00 y sábado
  08:00-15:00, sin domingos ni festivos por defecto), festivos de Colombia calculados según la Ley 51 de
  1983 y tabla de festivos editable, y motor de evaluación de horario puro con endpoint
  `POST /api/v1/cumplimiento/evaluar`. La frecuencia de contacto se evalúa desde la subfase 2A.
- Auditoría de acciones sensibles (login, usuarios, campañas, importaciones, exclusiones, políticas y
  festivos) sin datos personales en el detalle.
- Comandos de administración: `python -m app.cli crear-admin` y `python -m app.cli generar-festivos`.
- Interfaz: pantallas de inicio de sesión, campañas, detalle de campaña con importación, importación y
  errores, exclusiones, cumplimiento y usuarios, con navegación según rol.
- Documentación: `README.md`, `backend/README.md`, `frontend/README.md`, `docs/importacion-csv.md` y
  `docs/pendientes.md`.

### Cambiado

Subfase 2B:

- La frecuencia de contacto cuenta las plantillas de WhatsApp como intento de contacto de la empresa (`canal
  whatsapp_mensaje`). Se registran siempre al permitirse, también cuando reutilizan una conversación abierta. Las
  respuestas de texto dentro de la ventana no consumen frecuencia.
- Las exclusiones tienen canal. La voz respeta las de `todos` y `voz`; WhatsApp, las de `todos` y `whatsapp`. La unicidad
  pasa a (número, `aplica_a`, `canal`). `creado_por` puede ser nulo cuando el origen es el sistema.
- `docker-compose.yml`: `backend` y `worker` comparten el `.env` completo mediante `env_file` (requiere Docker Compose
  2.24 o superior).
- `GET /api/v1/conversaciones/{id}` audita `conversacion.ver` solo con `apertura=true`, que la bandeja envía una vez al
  abrir la conversación.
- `GET /api/v1/exclusiones` y `POST /api/v1/exclusiones/importar` aceptan el filtro y el campo `canal`.
- Las columnas `autoriza_whatsapp` y `fecha_autorizacion_whatsapp` de la importación se aplican a los móviles de la fila.
  Una autorización anterior a una baja por opt-out se omite.
- `docs/cumplimiento-frecuencia.md`, `docs/importacion-csv.md`, `docs/pendientes.md`, `README.md` y los READMEs de
  backend y frontend describen la subfase 2B.

Subfase 2A:

- La frecuencia de contacto (Ley 2300) pasa de almacenarse en la política a evaluarse en cada llamada, antes del `<Dial>`.
- La política de cumplimiento incluye los campos `frecuencia.contar_intentos_sin_contacto` y `entrantes`. Las políticas
  guardadas antes siguen validando con sus valores por defecto. `POST /api/v1/cumplimiento/evaluar` acepta `canal` y,
  para administrador y supervisor, `cliente_id`.
- `POST /api/v1/campanas/{id}/importaciones` y `POST /api/v1/exclusiones/importar` aceptan `.xlsx` además de `.csv`.
- Variables de entorno nuevas para telefonía, consola, importación y tiempo real. Ver `backend/README.md`.
- El WebSocket de tiempo real pasa de la Fase 3 a la subfase 2A (ADR-0017).

### Seguridad

Subfase 2B:

- Firma de los webhooks de WhatsApp con `X-Twilio-Signature`, con la misma validación común que la voz. Firma ausente o
  incorrecta: `403 FIRMA_INVALIDA`, sin procesar nada.
- Anti-SSRF y path traversal en los medios: la URL debe tener el prefijo exacto de la cuenta de Twilio, sin credenciales,
  puertos, query ni `..`. Las redirecciones no se siguen de forma automática (máximo dos saltos y solo a hosts permitidos),
  y las credenciales solo viajan a `api.twilio.com`. Además hay límites de tamaño, de descargas simultáneas y de duración.
- Medios sin almacenar, con `Content-Type` del tipo guardado, `X-Content-Type-Options: nosniff`,
  `Cache-Control: private, no-store` y `Content-Security-Policy: sandbox`.
- Saneamiento de texto hostil: los caracteres NUL y los sustitutos Unicode sueltos se rechazan en la API (`422
  VALIDACION`) y se limpian en los webhooks.
- Logs sin datos personales: los avisos de WhatsApp registran solo el nombre del evento. La auditoría y los eventos de
  tiempo real no contienen texto de mensajes, teléfonos completos ni evidencias.
- Opt-out ampliado: frases en español con coincidencia exacta tras normalizar, patrones de baja por WhatsApp, por todos
  los canales y por voz ("no me llamen"), y el botón de baja. "Cancelar" queda fuera de la lista, porque en Colombia
  significa pagar.
- Revalidación antes de cada envío de plantilla: exclusión, autorización, plantilla enviable, franja y festivos. Si ya no
  se cumple, el mensaje falla sin llamar al proveedor.
- Autorizaciones revocadas por opt-out: una autorización con fecha anterior a la baja no se puede crear
  (`AUTORIZACION_REVOCADA_POR_OPT_OUT`).
- Cola robusta ante caídas: los envíos son "como mucho una vez" (un envío interrumpido se marca `ENVIO_INCIERTO` y no se
  reenvía). Los trabajos de instancias muertas del mismo host se devuelven a la cola, y un trabajo que agota sus intentos
  pasa a `fallido` con auditoría. La toma de trabajos usa `SKIP LOCKED` en PostgreSQL.
- Los endpoints de simulación de WhatsApp no existen con `ENTORNO=produccion` ni con `WHATSAPP_PROVEEDOR=twilio` (404).

Subfase 2A:

- Tickets de un solo uso para el WebSocket: `POST /api/v1/ws/ticket` emite un ticket de 30 s que se guarda como hash
  SHA-256. El JWT ya no viaja en la URL, y `?token=` deja de admitirse. Un ticket inválido, caducado o usado cierra la
  conexión con 4401.
- Revalidación de cada conexión WebSocket cada `WS_REVALIDAR_SEGUNDOS`: el usuario debe seguir activo y con el mismo
  rol. Cola acotada a 1000 eventos; si se desborda, cierre 1013.
- Credenciales enmascaradas en logs: los logs de uvicorn sustituyen `token=`, `ticket=` y `access_token=` por `***`.
- Firma de los webhooks de Twilio (HMAC-SHA1 con comparación en tiempo constante). Firma ausente o incorrecta: `403
  FIRMA_INVALIDA`, sin procesar nada. La URL firmada es `PUBLIC_BASE_URL` más la ruta.
- `TWILIO_AUTH_TOKEN` vacío o con el valor de ejemplo se rechaza en producción. Con `TELEFONIA_PROVEEDOR=twilio` se
  exigen todas las credenciales, y `PUBLIC_BASE_URL` debe ser `https://` y no terminar en barra.
- Bloqueos contra llamadas duplicadas: las llamadas toman bloqueos de fila en un orden fijo (estado del agente y
  cliente) antes de validar. El `CallSid` es idempotente. Una llamada terminada sin tipificar impide nuevas llamadas
  del agente. Una finalización única aunque lleguen señales simultáneas.
- Protección de reservas: un registro con una llamada activa o sin tipificar no se puede tomar aunque la reserva
  haya caducado. La reserva se renueva con la llamada. La asignación del agente se comprueba en la misma sentencia
  que la reserva.
- Teléfonos enmascarados en `/consola/*` (`+57300****567`). El navegador envía solo ids y el servidor resuelve el
  número. El número de destino nunca viene de la petición. La URL de la grabación no se expone al navegador.
- Los eventos de llamada no guardan números de teléfono. La auditoría no contiene datos personales.
- Importación Excel: sin macros ni fórmulas recalculadas, límite de tamaño descomprimido
  (`IMPORTACION_MAX_BYTES_DESCOMPRIMIDO`, 100 MiB) y comprobación previa del ZIP. `.xls` y `.xlsm` se rechazan.
- Simulación de llamadas inexistente (404) con `TELEFONIA_PROVEEDOR=twilio` o `ENTORNO=produccion`.

Endurecimiento tras la revisión de la Fase 1:

- Datos personales fuera de los logs: los errores no controlados solo registran el tipo de excepción y las
  líneas del traceback, nunca el mensaje de la excepción (que puede incluir documentos o teléfonos). Los
  mensajes de error de importación y exclusiones enmascaran documentos y teléfonos (`***4567`).
- Respuesta 409 en lugar de 500 ante conflictos de concurrencia al importar, al importar exclusiones y al
  actualizar políticas o generar festivos (`IMPORTACION_CONCURRENTE`, `EXCLUSION_CONCURRENTE`,
  `POLITICA_CONCURRENTE`, `FESTIVOS_CONCURRENTE`).
- Límite del tamaño del cuerpo antes de autenticar: un middleware responde `413
  ARCHIVO_DEMASIADO_GRANDE` si el cuerpo supera `IMPORTACION_MAX_BYTES` más 1 MiB de margen, sin
  necesidad de token.
- Docker: el backend se ejecuta como usuario sin privilegios (`app`, uid 1000). PostgreSQL se publica solo
  en `127.0.0.1`.
- Festivos calculados como respaldo: si un año no tiene festivos calculados en la tabla, el evaluador de
  cumplimiento usa el cálculo de la Ley 51 de 1983. Los festivos manuales y los calculados desactivados se
  respetan.

### Corregido

- Subfase 2A (deuda): las variables de telefonía, Twilio, consola y tiempo real del `.env` no llegaban a los contenedores
  de Docker. Ahora sí, mediante `env_file` en `backend` y `worker`.
- Las fechas extremas y los identificadores fuera de rango en las peticiones ya no provocan errores 500.
