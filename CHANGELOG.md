# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [Unreleased]

### Añadido

Fase 1 de la plataforma de campañas outbound (sin telefonía todavía).

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
  `POST /api/v1/cumplimiento/evaluar`. La frecuencia de contacto se almacena en la política pero aún no
  se evalúa.
- Auditoría de acciones sensibles (login, usuarios, campañas, importaciones, exclusiones, políticas y
  festivos) sin datos personales en el detalle.
- Comandos de administración: `python -m app.cli crear-admin` y `python -m app.cli generar-festivos`.
- Interfaz: pantallas de inicio de sesión, campañas, detalle de campaña con importación, importación y
  errores, exclusiones, cumplimiento y usuarios, con navegación según rol.
- Documentación: `README.md`, `backend/README.md`, `frontend/README.md`, `docs/importacion-csv.md` y
  `docs/pendientes.md`.

### Seguridad

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

- Las fechas extremas y los identificadores fuera de rango en las peticiones ya no provocan errores 500.
