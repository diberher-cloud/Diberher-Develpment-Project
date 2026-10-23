# Fase 1 — Cimientos sin telefonía

> Fuente de verdad para backend, frontend, QA y documentación durante la Fase 1.
> Visión general y fases siguientes: [`README.md`](README.md). Decisiones: ADR-0001 a ADR-0009.

## 0. Alcance

**Incluye**
1. Esqueleto: `backend/` (FastAPI), `frontend/` (React + TS + Vite), `docker-compose.yml` con PostgreSQL 16,
   migraciones Alembic.
2. Autenticación JWT con roles (`administrador`, `supervisor`, `agente`) y gestión de usuarios (admin).
3. CRUD de campañas con máquina de estados.
4. Importación de clientes desde **CSV** a una campaña: validación, normalización de teléfonos +57
   (E.164), deduplicación, exclusiones, resumen y detalle de errores.
5. Exclusiones de números (alta individual, carga masiva CSV, baja).
6. Cumplimiento: políticas versionadas por tipo de campaña, festivos (cálculo + tabla editable) y **motor
   puro** de franjas + festivos con endpoint de evaluación.
7. Auditoría básica.

**No incluye** (fases posteriores): Twilio, consola del agente, Excel, marcador, frecuencia (solo se
guarda en la política), WebSocket, reportes, asignación de agentes a campañas.

**Sin credenciales reales**: ninguna. Los tests del backend corren **sin Docker** (SQLite en memoria +
lógica pura; ver ADR-0006).

---

## 1. Estructura de carpetas

```
.
├── docker-compose.yml
├── .env.example
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_esquema_inicial.py      # tablas + semillas de políticas
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # crea FastAPI, routers, manejadores de error, CORS
│   │   ├── config.py               # Settings (pydantic-settings)
│   │   ├── db.py                   # engine, SessionLocal, Base, get_db, FechaHoraUTC
│   │   ├── errores.py              # ErrorApp + manejadores → formato de error común
│   │   ├── seguridad.py            # hash bcrypt, crear/decodificar JWT
│   │   ├── dependencias.py         # usuario_actual, requiere_rol(...)
│   │   ├── paginacion.py           # parámetros y respuesta paginada
│   │   ├── cli.py                  # crear-admin, generar-festivos
│   │   └── modulos/
│   │       ├── auth/               router.py, esquemas.py, servicio.py
│   │       ├── usuarios/           modelos.py, esquemas.py, servicio.py, router.py
│   │       ├── campanas/           modelos.py, esquemas.py, servicio.py, router.py
│   │       ├── clientes/           modelos.py (Cliente, Telefono, CampanaCliente), esquemas.py, servicio.py, router.py
│   │       ├── importacion/
│   │       │   ├── telefonos.py    # PURO: normalizar_telefono
│   │       │   ├── normalizacion.py# PURO: cabeceras, documento, montos, enteros, fechas, email
│   │       │   ├── lector_csv.py   # PURO: decodificación, delimitador, filas
│   │       │   ├── modelos.py, esquemas.py, servicio.py, router.py
│   │       ├── exclusiones/        modelos.py, esquemas.py, servicio.py, router.py
│   │       ├── cumplimiento/
│   │       │   ├── politica.py     # PURO: modelos Pydantic de la política
│   │       │   ├── festivos.py     # PURO: festivos_colombia(anio)
│   │       │   ├── motor.py        # PURO: evaluar_horario, proxima_ventana
│   │       │   ├── modelos.py, esquemas.py, servicio.py, router.py
│   │       └── auditoria/          modelos.py, servicio.py
│   └── tests/
│       ├── conftest.py             # SQLite memoria, TestClient, fábricas de usuarios/tokens
│       ├── unit/
│       │   ├── test_telefonos.py
│       │   ├── test_normalizacion.py
│       │   ├── test_lector_csv.py
│       │   ├── test_festivos.py
│       │   ├── test_politica.py
│       │   └── test_motor_cumplimiento.py
│       ├── api/
│       │   ├── test_salud.py
│       │   ├── test_auth.py
│       │   ├── test_usuarios.py
│       │   ├── test_campanas.py
│       │   ├── test_importacion.py
│       │   ├── test_exclusiones.py
│       │   └── test_cumplimiento.py
│       ├── fixtures/               # CSV de ejemplo (utf-8, utf-8-bom, cp1252, ';' y ',')
│       └── test_migraciones.py     # alembic upgrade head sobre SQLite temporal
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts              # proxy /api → VITE_PROXY_TARGET (def. http://localhost:8000); config de vitest
    ├── eslint.config.js
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx                 # rutas
        ├── api/
        │   ├── cliente.ts          # fetch con token, parseo del error común → ErrorApi
        │   ├── tipos.ts            # tipos TS de los contratos (sección 4)
        │   └── endpoints.ts        # funciones por endpoint
        ├── auth/
        │   ├── AuthContext.tsx     # sesión en memoria + sessionStorage
        │   └── RutaProtegida.tsx   # exige sesión y rol
        ├── componentes/            # Layout, Tabla, Paginador, MensajeError, Cargando, ...
        ├── paginas/
        │   ├── Login.tsx
        │   ├── Campanas.tsx        # listado + filtros + crear
        │   ├── CampanaFormulario.tsx
        │   ├── CampanaDetalle.tsx  # datos, cambio de estado, importar CSV, historial importaciones, clientes
        │   ├── ImportacionDetalle.tsx # resumen + errores paginados
        │   ├── Exclusiones.tsx
        │   ├── Cumplimiento.tsx    # políticas (lectura), festivos, evaluador
        │   └── Usuarios.tsx        # solo administrador
        └── test/setup.ts
```

Convenciones: identificadores de dominio en español sin tildes ni `ñ` (`campana`, `anio`), API en
`snake_case`, rutas con prefijo `/api/v1`.

## 2. Dependencias

Las versiones son rangos compatibles; el backend debe fijar las versiones exactas resueltas (lock o
`pip freeze` en `requirements.lock`) y documentarlas.

### Backend (Python 3.12) — `backend/pyproject.toml`

| Paquete | Versión | Uso |
|---|---|---|
| fastapi | `>=0.115,<0.116` | API |
| uvicorn[standard] | `>=0.32,<0.35` | servidor ASGI |
| sqlalchemy | `>=2.0.36,<2.1` | ORM |
| alembic | `>=1.14,<1.17` | migraciones |
| psycopg[binary] | `>=3.2,<3.3` | driver PostgreSQL |
| pydantic | `>=2.10,<2.12` | esquemas |
| pydantic-settings | `>=2.6,<2.10` | configuración |
| email-validator | `>=2.2,<3` | `EmailStr` |
| pyjwt | `>=2.10,<3` | JWT |
| bcrypt | `>=4.2,<5` | hash de contraseñas |
| python-multipart | `>=0.0.18,<0.1` | subida de archivos |
| phonenumbers | `>=8.13,<9` | teléfonos (ADR-0007) |
| tzdata | `>=2024.2` | zona `America/Bogota` en sistemas sin base tz (Windows/contenedores slim) |

Dev (`[project.optional-dependencies] dev`): `pytest>=8.3,<9`, `httpx>=0.27,<0.29` (TestClient),
`ruff>=0.8,<0.13`, `pytest-cov>=6,<7`.

Herramientas: `ruff` (lint + formato, `line-length = 100`), `pytest` (`testpaths = ["tests"]`,
marcador `postgres` registrado).

### Frontend (Node 22 LTS) — `frontend/package.json`

| Paquete | Versión |
|---|---|
| react, react-dom | `^18.3.1` |
| react-router-dom | `^6.28.0` |
| typescript | `~5.6.3` |
| vite | `^6.0.0` |
| @vitejs/plugin-react | `^4.3.4` |
| vitest | `^2.1.8` |
| @testing-library/react | `^16.1.0` |
| @testing-library/user-event | `^14.5.2` |
| @testing-library/jest-dom | `^6.6.3` |
| jsdom | `^25.0.1` |
| eslint + typescript-eslint + eslint-plugin-react-hooks | `^9` / `^8` / `^5` |

Sin librería de componentes ni de estado en Fase 1 (CSS propio sencillo, `fetch` nativo). Scripts:
`dev`, `build` (`tsc -b && vite build`), `test` (`vitest`), `lint` (`eslint .`).

### Infraestructura
`postgres:16-alpine`, imagen backend `python:3.12-slim`, imagen frontend `node:22-alpine`.

---

## 3. Esquema de base de datos (migración `0001_esquema_inicial`)

Todas las tablas: PK `id INTEGER` autoincremental. `FechaHoraUTC` = `DateTime(timezone=True)` vía
TypeDecorator (ADR-0006). Enumeraciones = `VARCHAR` + `CHECK`.

### `usuarios`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| email | varchar(254) | NOT NULL, UNIQUE, guardado en minúsculas |
| nombre | varchar(120) | NOT NULL |
| rol | varchar(20) | NOT NULL, CHECK in (`administrador`,`supervisor`,`agente`) |
| password_hash | varchar(255) | NOT NULL |
| activo | boolean | NOT NULL default true |
| creado_en, actualizado_en | FechaHoraUTC | NOT NULL |

### `campanas`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| nombre | varchar(120) | NOT NULL, UNIQUE |
| tipo | varchar(20) | NOT NULL, CHECK in (`venta`,`cobranza`) |
| descripcion | text | NULL |
| estado | varchar(20) | NOT NULL default `borrador`, CHECK in (`borrador`,`activa`,`pausada`,`finalizada`) |
| fecha_inicio | date | NULL |
| fecha_fin | date | NULL, CHECK `fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio` |
| guion | text | NULL |
| max_intentos | integer | NOT NULL default 3, CHECK 1..10 |
| intervalo_reintento_minutos | integer | NOT NULL default 60, CHECK 5..10080 |
| creado_por | integer | FK usuarios.id, NOT NULL |
| creado_en, actualizado_en | FechaHoraUTC | NOT NULL |

### `clientes` (global, ver README §4)
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| tipo_documento | varchar(5) | NOT NULL, CHECK in (`CC`,`CE`,`NIT`,`PA`,`TI`,`PPT`) |
| numero_documento | varchar(20) | NOT NULL |
| nombre | varchar(200) | NOT NULL |
| email | varchar(254) | NULL |
| ciudad | varchar(100) | NULL |
| creado_en, actualizado_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`tipo_documento`, `numero_documento`) |

### `telefonos`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| cliente_id | integer | FK clientes.id ON DELETE CASCADE, NOT NULL |
| numero_e164 | varchar(16) | NOT NULL, INDEX |
| tipo_linea | varchar(10) | NOT NULL, CHECK in (`movil`,`fijo`) |
| prioridad | integer | NOT NULL (1 = `telefono_1`, 2, 3) |
| creado_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`cliente_id`, `numero_e164`) |

### `campana_clientes`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| campana_id | integer | FK campanas.id ON DELETE CASCADE, NOT NULL, INDEX |
| cliente_id | integer | FK clientes.id, NOT NULL |
| importacion_id | integer | FK importaciones.id, NULL |
| estado | varchar(20) | NOT NULL default `pendiente`, CHECK in (`pendiente`,`en_gestion`,`gestionado`,`descartado`) — en fase 1 solo `pendiente` |
| numero_obligacion | varchar(50) | NULL (cobranza) |
| saldo_total | numeric(14,2) | NULL (cobranza) |
| saldo_mora | numeric(14,2) | NULL (cobranza) |
| dias_mora | integer | NULL (cobranza), CHECK >= 0 |
| fecha_vencimiento | date | NULL (cobranza) |
| producto | varchar(120) | NULL (venta) |
| oferta | text | NULL (venta) |
| datos_adicionales | JSON | NOT NULL default `{}` (máx. 20 claves, valores texto ≤ 500 car.) |
| intentos | integer | NOT NULL default 0 |
| proximo_intento_en | FechaHoraUTC | NULL |
| creado_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`campana_id`, `cliente_id`) |

### `importaciones`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| campana_id | integer | FK campanas.id ON DELETE CASCADE, NOT NULL |
| nombre_archivo | varchar(255) | NOT NULL |
| estado | varchar(20) | NOT NULL, CHECK in (`completada`,`fallida`) |
| total_filas, filas_importadas, filas_duplicadas, filas_invalidas, filas_excluidas | integer | NOT NULL default 0 |
| creado_por | integer | FK usuarios.id, NOT NULL |
| creado_en | FechaHoraUTC | NOT NULL |

### `importacion_errores`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| importacion_id | integer | FK importaciones.id ON DELETE CASCADE, NOT NULL, INDEX |
| fila | integer | NOT NULL (número de línea del archivo; la cabecera es la 1) |
| campo | varchar(50) | NULL |
| codigo | varchar(40) | NOT NULL |
| mensaje | varchar(300) | NOT NULL (sin el valor completo de documento/teléfono) |
| severidad | varchar(12) | NOT NULL, CHECK in (`error`,`advertencia`) |

### `exclusiones`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| numero_e164 | varchar(16) | NOT NULL, INDEX |
| motivo | varchar(30) | NOT NULL, CHECK in (`rne`,`solicitud_titular`,`numero_errado`,`manual`) |
| aplica_a | varchar(10) | NOT NULL, CHECK in (`venta`,`cobranza`,`todas`) |
| observacion | varchar(300) | NULL |
| creado_por | integer | FK usuarios.id, NOT NULL |
| creado_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`numero_e164`, `aplica_a`) |

Un número está excluido para una campaña de tipo `T` si existe fila con `aplica_a in (T, 'todas')`.

### `politicas_cumplimiento`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| tipo_campana | varchar(20) | NOT NULL, CHECK in (`venta`,`cobranza`) |
| version | integer | NOT NULL |
| configuracion | JSON | NOT NULL (esquema §4.7) |
| activa | boolean | NOT NULL |
| creado_por | integer | FK usuarios.id, NULL (NULL = semilla) |
| creado_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`tipo_campana`, `version`) |

Semilla en la migración: versión 1 activa para `venta` y para `cobranza` con la configuración por
defecto (§4.7). Invariante (servicio): exactamente una activa por tipo.

### `festivos`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| fecha | date | NOT NULL, UNIQUE |
| nombre | varchar(200) | NOT NULL |
| origen | varchar(12) | NOT NULL, CHECK in (`calculado`,`manual`) |
| activo | boolean | NOT NULL default true |
| creado_en | FechaHoraUTC | NOT NULL |

La migración **no** siembra festivos (los genera la CLI/endpoint); el `docker-compose` ejecuta
`python -m app.cli generar-festivos --desde 2025 --hasta 2028` tras migrar (idempotente).

### `auditoria`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| usuario_id | integer | FK usuarios.id, NULL |
| accion | varchar(60) | NOT NULL (p. ej. `auth.login_ok`, `auth.login_fallido`, `usuario.crear`, `campana.crear`, `campana.estado`, `importacion.crear`, `exclusion.crear`, `exclusion.eliminar`, `exclusion.importar`, `politica.actualizar`, `festivo.crear`, `festivo.actualizar`, `festivos.generar`) |
| entidad | varchar(40) | NULL |
| entidad_id | varchar(40) | NULL |
| detalle | JSON | NOT NULL default `{}` (sin datos personales) |
| creado_en | FechaHoraUTC | NOT NULL |

---

## 4. Contratos de API

### 4.1 Convenciones comunes
- Base: `/api/v1`. JSON UTF-8. Fechas `YYYY-MM-DD`; fecha-hora ISO-8601 **con zona**; el servidor
  responde fecha-hora en UTC con sufijo `Z`, salvo los campos `*_local` / `proxima_ventana_inicio` que van
  en `-05:00`.
- Autenticación: `Authorization: Bearer <jwt>` en todo salvo `GET /salud` y `POST /auth/login`.
- **Formato de error único** (todas las respuestas 4xx/5xx, incluidos 404 de ruta y 422 de validación de
  FastAPI, que se sobrescribe):

```json
{
  "error": {
    "codigo": "VALIDACION",
    "mensaje": "Los datos enviados no son válidos.",
    "detalles": [ { "campo": "nombre", "mensaje": "Debe tener entre 3 y 120 caracteres." } ]
  }
}
```
`detalles` es siempre una lista (vacía si no aplica). `campo` usa la ruta del campo con puntos
(`configuracion.franjas.lunes.0.inicio`).

- Códigos genéricos:

| HTTP | codigo | Cuándo |
|---|---|---|
| 401 | `NO_AUTENTICADO` | falta token, token inválido/expirado, usuario inexistente o inactivo |
| 401 | `CREDENCIALES_INVALIDAS` | login fallido (mismo mensaje si el usuario está inactivo o no existe) |
| 403 | `PERMISO_DENEGADO` | rol sin permiso |
| 404 | `NO_ENCONTRADO` | recurso o ruta inexistente |
| 409 | (específico) | conflicto de negocio |
| 413 | `ARCHIVO_DEMASIADO_GRANDE` | archivo > `IMPORTACION_MAX_BYTES` (10 MiB) |
| 422 | `VALIDACION` | cuerpo/parámetros inválidos |
| 500 | `ERROR_INTERNO` | no controlado (sin trazas en la respuesta) |

- **Paginación** (listados): query `page` (≥1, def. 1), `page_size` (1..100, def. 20). Respuesta:
```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

- Matriz de permisos (A = administrador, S = supervisor, G = agente):

| Recurso | A | S | G |
|---|---|---|---|
| `auth/*` | ✓ | ✓ | ✓ |
| usuarios | ✓ | – | – |
| campañas: leer | ✓ | ✓ | ✓ (solo `estado=activa`) |
| campañas: crear/editar/eliminar/estado | ✓ | ✓ | – |
| importaciones y clientes de campaña | ✓ | ✓ | – |
| exclusiones: leer/crear/importar/eliminar | ✓ | ✓ | – |
| políticas y festivos: leer | ✓ | ✓ | ✓ |
| políticas y festivos: modificar/generar | ✓ | – | – |
| cumplimiento/evaluar | ✓ | ✓ | ✓ |

### 4.2 Salud
`GET /api/v1/salud` → `200 {"estado": "ok", "version": "0.1.0"}` (sin acceso a BD).

### 4.3 Autenticación

**`POST /api/v1/auth/login`**
```json
// petición
{ "email": "admin@empresa.co", "password": "ClaveSegura123" }
// 200
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 28800,
  "usuario": { "id": 1, "email": "admin@empresa.co", "nombre": "Ana Admin", "rol": "administrador", "activo": true }
}
```
Errores: 401 `CREDENCIALES_INVALIDAS`; 422 `VALIDACION`. El email se compara en minúsculas. Registra
`auth.login_ok` / `auth.login_fallido` (detalle sin contraseña).

**`GET /api/v1/auth/me`** → `200` objeto `Usuario` (como `usuario` arriba). 401 `NO_AUTENTICADO`.

### 4.4 Usuarios (solo administrador)

Objeto `Usuario`:
```json
{ "id": 2, "email": "sup@empresa.co", "nombre": "Sara Supervisora", "rol": "supervisor", "activo": true,
  "creado_en": "2026-10-23T15:00:00Z", "actualizado_en": "2026-10-23T15:00:00Z" }
```
(En `login`/`me` pueden omitirse `creado_en`/`actualizado_en`.)

- `GET /api/v1/usuarios?rol=&activo=&page=&page_size=` → paginado de `Usuario`, orden `nombre`.
- `POST /api/v1/usuarios`
  ```json
  { "email": "agente1@empresa.co", "nombre": "Pedro Agente", "rol": "agente", "password": "ClaveSegura123" }
  ```
  → `201 Usuario`. Validación: email válido; nombre 2..120; rol válido; password 10..128.
  Errores: 409 `EMAIL_DUPLICADO`; 422.
- `PATCH /api/v1/usuarios/{id}` (todos opcionales): `{ "nombre": "...", "rol": "supervisor", "activo": false, "password": "..." }`
  → `200 Usuario`. Errores: 404; 409 `NO_PUEDE_DESACTIVARSE` (un administrador no puede desactivarse ni
  quitarse el rol a sí mismo); 422.

### 4.5 Campañas

Objeto `Campana`:
```json
{
  "id": 1,
  "nombre": "Cobranza cartera octubre",
  "tipo": "cobranza",
  "descripcion": "Mora 30-90 días",
  "estado": "borrador",
  "fecha_inicio": "2026-11-01",
  "fecha_fin": null,
  "guion": "Buenos días, {{nombre}}...",
  "max_intentos": 3,
  "intervalo_reintento_minutos": 60,
  "total_clientes": 0,
  "creado_por": 1,
  "creado_en": "2026-10-23T15:00:00Z",
  "actualizado_en": "2026-10-23T15:00:00Z"
}
```

- `GET /api/v1/campanas?estado=&tipo=&q=&page=&page_size=` → paginado de `Campana`, orden `creado_en`
  desc. `q` busca en `nombre` sin distinguir mayúsculas. Para agentes se fuerza `estado=activa`.
- `POST /api/v1/campanas` (A, S)
  ```json
  { "nombre": "Cobranza cartera octubre", "tipo": "cobranza", "descripcion": null,
    "fecha_inicio": "2026-11-01", "fecha_fin": null, "guion": null,
    "max_intentos": 3, "intervalo_reintento_minutos": 60 }
  ```
  Requeridos: `nombre` (3..120, se recorta), `tipo`. Opcionales con defaults mostrados. `guion` ≤ 20000.
  → `201 Campana` con `estado: "borrador"`. Errores: 409 `NOMBRE_DUPLICADO`; 422.
- `GET /api/v1/campanas/{id}` → `200 Campana`; 404.
- `PATCH /api/v1/campanas/{id}` (A, S). Campos opcionales: `nombre`, `descripcion`, `fecha_inicio`,
  `fecha_fin`, `guion`, `max_intentos`, `intervalo_reintento_minutos`, `estado`. `tipo` **no** es editable
  (si se envía → 422 con detalle en `tipo`).
  Transiciones de `estado` válidas: `borrador→activa`, `activa→pausada`, `pausada→activa`,
  `activa→finalizada`, `pausada→finalizada`. Misma → sin cambio (200).
  Errores: 404; 409 `NOMBRE_DUPLICADO`; 409 `TRANSICION_INVALIDA`; 409 `CAMPANA_SIN_CLIENTES`
  (activar sin clientes); 409 `CAMPANA_FINALIZADA` (cualquier cambio sobre una finalizada); 422
  (incluye `fecha_fin < fecha_inicio`).
- `DELETE /api/v1/campanas/{id}` (A, S) → `204`. Solo en `borrador`; borra en cascada sus importaciones
  y `campana_clientes` (no los `clientes` globales). Errores: 404; 409 `CAMPANA_NO_ELIMINABLE`.

### 4.6 Importación de clientes

**`POST /api/v1/campanas/{id}/importaciones`** (A, S) — `multipart/form-data`, campo `archivo`.

Reglas del archivo:
- Extensión `.csv` (sin distinguir mayúsculas). Otra → 422 `FORMATO_ARCHIVO_INVALIDO`.
- Tamaño ≤ 10 MiB (`IMPORTACION_MAX_BYTES`) → si no, 413 `ARCHIVO_DEMASIADO_GRANDE`.
- Codificación: UTF-8 (con o sin BOM); si falla la decodificación, `cp1252`.
- Delimitador: `;` o `,`, detectado en la línea de cabecera (el que más aparezca; empate → `,`).
  Comillas dobles estándar CSV.
- Cabeceras normalizadas: minúsculas, sin tildes, espacios/guiones → `_`, recortadas.
- Líneas completamente vacías se ignoran (no cuentan en `total_filas`).
- Máx. 50 000 filas de datos (`IMPORTACION_MAX_FILAS`) → si no, 422 `DEMASIADAS_FILAS`.
- Sin filas de datos → 422 `ARCHIVO_VACIO`.
- Falta alguna columna obligatoria → 422 `COLUMNAS_FALTANTES` con `detalles: [{"campo":"telefono_1","mensaje":"Columna obligatoria ausente."}]`.
- Campaña inexistente → 404; campaña `finalizada` → 409 `CAMPANA_FINALIZADA`.
Los errores a nivel de archivo **no** crean registro de importación.

Columnas:

| Columna | Obligatoria | Regla |
|---|---|---|
| `tipo_documento` | sí | mayúsculas, uno de `CC CE NIT PA TI PPT` → si no `TIPO_DOCUMENTO_INVALIDO` |
| `numero_documento` | sí | CC/TI/NIT: quitar espacios, `.` y `-`; solo dígitos, 4..15. CE/PA/PPT: quitar espacios, mayúsculas, alfanumérico 3..20 → si no `DOCUMENTO_INVALIDO` |
| `nombre` | sí | recortar, colapsar espacios, 2..200 → si no `CAMPO_REQUERIDO`/`VALOR_INVALIDO` |
| `telefono_1` | sí | ADR-0007 |
| `telefono_2`, `telefono_3` | no | ADR-0007; si inválido → advertencia y se ignora ese teléfono |
| `email` | no | si inválido → advertencia `EMAIL_INVALIDO` y se guarda NULL |
| `ciudad` | no | texto ≤ 100 |
| `numero_obligacion` | no (cobranza) | texto ≤ 50 |
| `saldo_total`, `saldo_mora` | no (cobranza) | monto (regla abajo) → si no `MONTO_INVALIDO` (error) |
| `dias_mora` | no (cobranza) | entero ≥ 0 → si no `ENTERO_INVALIDO` (error) |
| `fecha_vencimiento` | no (cobranza) | `YYYY-MM-DD` o `DD/MM/YYYY` → si no `FECHA_INVALIDA` (error) |
| `producto` | no (venta) | texto ≤ 120 |
| `oferta` | no (venta) | texto ≤ 2000 |
| otras | no | a `datos_adicionales` (máx. 20 claves; excedentes → advertencia `COLUMNAS_ADICIONALES_IGNORADAS` una sola vez, fila 1) |

Columnas de cobranza en campaña de venta (o viceversa) se aceptan y van a `datos_adicionales`.

Regla de **monto**: quitar `$` y espacios; si coincide `^\d{1,3}(\.\d{3})+(,\d{1,2})?$` → formato
colombiano (`.` miles, `,` decimales); si coincide `^\d+([.,]\d{1,2})?$` → separador decimal `.` o `,`;
otro → inválido. Ej.: `1.234.567,89` → 1234567.89; `1500000` → 1500000; `1500.5` → 1500.50;
`1,234.56` → inválido. Negativos inválidos.

Procesamiento por fila (en orden de archivo):
1. Validar; cualquier error de severidad `error` → fila **inválida** (`filas_invalidas`). Si `telefono_1`
   es inválido pero `telefono_2`/`telefono_3` son válidos, la fila **es válida** (advertencia sobre
   `telefono_1`). Sin ningún teléfono válido → error `SIN_TELEFONO_VALIDO`.
2. Clave de dedupe `(tipo_documento, numero_documento normalizado)`:
   - ya vista antes en el mismo archivo → `filas_duplicadas`, advertencia `DUPLICADO_EN_ARCHIVO`
     (gana la primera aparición);
   - el cliente ya está en la campaña → `filas_duplicadas`, advertencia `DUPLICADO_EN_CAMPANA`
     (no se actualiza).
3. Exclusiones: si **todos** los teléfonos válidos están excluidos para el tipo de la campaña →
   `filas_excluidas`, advertencia `TODOS_TELEFONOS_EXCLUIDOS` (no se añade a la campaña). Si solo algunos
   → se importa y advertencia `TELEFONO_EXCLUIDO` por cada uno (se guardan; el marcador volverá a
   comprobar exclusiones al marcar).
4. Importar: upsert de `clientes` por documento (actualiza `nombre`, y `email`/`ciudad` si vienen no
   vacíos), añade teléfonos nuevos (dedupe por `numero_e164` dentro del cliente; `prioridad` = posición
   de columna), crea `campana_clientes` (`filas_importadas`).
- Invariante: `total_filas = filas_importadas + filas_duplicadas + filas_invalidas + filas_excluidas`.
- Todo en **una transacción**; si ocurre un error inesperado → rollback y 500 (no queda importación
  parcial).
- `fila` en errores = número de línea física del registro en el archivo (cabecera = 1).
- Los mensajes no incluyen documento ni teléfono completos (enmascarar: `***4567`).

Respuesta `201` — objeto `Importacion`:
```json
{
  "id": 7,
  "campana_id": 1,
  "nombre_archivo": "cartera_octubre.csv",
  "estado": "completada",
  "total_filas": 5,
  "filas_importadas": 2,
  "filas_duplicadas": 1,
  "filas_invalidas": 1,
  "filas_excluidas": 1,
  "creado_por": 2,
  "creado_en": "2026-10-23T15:10:00Z",
  "errores": [
    { "fila": 3, "campo": "telefono_1", "codigo": "TELEFONO_INVALIDO", "mensaje": "Teléfono inválido (***4567).", "severidad": "error" },
    { "fila": 3, "campo": null, "codigo": "SIN_TELEFONO_VALIDO", "mensaje": "La fila no tiene ningún teléfono válido.", "severidad": "error" },
    { "fila": 4, "campo": "numero_documento", "codigo": "DUPLICADO_EN_ARCHIVO", "mensaje": "Documento repetido en el archivo (primera aparición en la fila 2).", "severidad": "advertencia" },
    { "fila": 6, "campo": "telefono_1", "codigo": "TODOS_TELEFONOS_EXCLUIDOS", "mensaje": "Todos los teléfonos están excluidos para campañas de venta.", "severidad": "advertencia" }
  ],
  "errores_truncados": false
}
```
`errores` incluye como máximo los **100 primeros** (`errores_truncados: true` si hay más); el detalle
completo se consulta paginado. `estado` es siempre `completada` en Fase 1 (`fallida` reservado).

Códigos de error/advertencia de fila: `CAMPO_REQUERIDO`, `VALOR_INVALIDO`, `TIPO_DOCUMENTO_INVALIDO`,
`DOCUMENTO_INVALIDO`, `TELEFONO_REQUERIDO`, `TELEFONO_INVALIDO`, `TELEFONO_NO_COLOMBIANO`,
`TELEFONO_TIPO_NO_PERMITIDO`, `SIN_TELEFONO_VALIDO`, `EMAIL_INVALIDO`, `MONTO_INVALIDO`,
`ENTERO_INVALIDO`, `FECHA_INVALIDA`, `DUPLICADO_EN_ARCHIVO`, `DUPLICADO_EN_CAMPANA`,
`TELEFONO_EXCLUIDO`, `TODOS_TELEFONOS_EXCLUIDOS`, `COLUMNAS_ADICIONALES_IGNORADAS`.
Severidad `error` para los que invalidan la fila; `advertencia` para el resto (incluido
`TELEFONO_INVALIDO` en `telefono_2`/`telefono_3` o en `telefono_1` cuando otro es válido).

- `GET /api/v1/campanas/{id}/importaciones?page=&page_size=` (A, S) → paginado de `Importacion`
  **sin** `errores`/`errores_truncados`, orden `creado_en` desc.
- `GET /api/v1/importaciones/{id}` (A, S) → `Importacion` sin `errores`; 404.
- `GET /api/v1/importaciones/{id}/errores?severidad=&page=&page_size=` (A, S) → paginado de
  `{ "fila", "campo", "codigo", "mensaje", "severidad" }` orden `fila`, `id`.

**Clientes de una campaña** — `GET /api/v1/campanas/{id}/clientes?q=&estado=&page=&page_size=` (A, S)
→ paginado de:
```json
{
  "id": 15,
  "estado": "pendiente",
  "intentos": 0,
  "cliente": { "id": 9, "tipo_documento": "CC", "numero_documento": "1020304050", "nombre": "María Pérez", "email": null, "ciudad": "Bogotá" },
  "telefonos": [ { "id": 21, "numero_e164": "+573001234567", "tipo_linea": "movil", "prioridad": 1, "excluido": false } ],
  "numero_obligacion": "OB-001",
  "saldo_total": "1500000.00",
  "saldo_mora": "250000.50",
  "dias_mora": 45,
  "fecha_vencimiento": "2026-09-15",
  "producto": null,
  "oferta": null,
  "datos_adicionales": { "segmento": "A" },
  "importacion_id": 7,
  "creado_en": "2026-10-23T15:10:00Z"
}
```
Montos como **string decimal** con 2 decimales (evita pérdida de precisión). `excluido` se calcula en
la consulta contra `exclusiones` para el tipo de la campaña. `q` busca por nombre (sin distinguir
mayúsculas), número de documento exacto o teléfono (normalizado con ADR-0007; si `q` no es un teléfono
válido se ignora esa parte). Orden: `id` asc.

### 4.7 Exclusiones (A, S)

Objeto `Exclusion`:
```json
{ "id": 3, "numero_e164": "+573001234567", "motivo": "rne", "aplica_a": "venta",
  "observacion": "Carga RNE 2026-10", "creado_por": 2, "creado_en": "2026-10-23T15:20:00Z" }
```
- `GET /api/v1/exclusiones?q=&motivo=&aplica_a=&page=&page_size=` → paginado; `q` = teléfono en cualquier
  formato (se normaliza; si no es válido → lista vacía).
- `POST /api/v1/exclusiones` `{ "telefono": "300 123 4567", "motivo": "manual", "aplica_a": "todas", "observacion": null }`
  → `201 Exclusion`. Si `motivo=rne` y no se envía `aplica_a` → `venta`; resto → obligatorio.
  Errores: 422 `VALIDACION` con detalle en `telefono` (mensaje con el código de ADR-0007);
  409 `EXCLUSION_DUPLICADA`.
- `DELETE /api/v1/exclusiones/{id}` → `204`; 404.
- `POST /api/v1/exclusiones/importar` — multipart: `archivo` (CSV con columna obligatoria `telefono`,
  mismas reglas de archivo que §4.6, máx. 200 000 filas), `motivo`, `aplica_a` (form fields; mismas
  reglas que el alta individual) →
  ```json
  { "total_filas": 1000, "creadas": 990, "duplicadas": 8, "invalidas": 2,
    "errores": [ { "fila": 17, "campo": "telefono", "codigo": "TELEFONO_INVALIDO", "mensaje": "Teléfono inválido (***1234).", "severidad": "error" } ],
    "errores_truncados": false }
  ```
  `200`. Duplicadas = ya existía `(numero_e164, aplica_a)` o repetido en el archivo. Una transacción.

### 4.8 Cumplimiento

**Política (JSON `configuracion`)** — modelo Pydantic `PoliticaCumplimiento`, `extra="forbid"`:
```json
{
  "zona_horaria": "America/Bogota",
  "franjas": {
    "lunes":     [ { "inicio": "07:00", "fin": "19:00" } ],
    "martes":    [ { "inicio": "07:00", "fin": "19:00" } ],
    "miercoles": [ { "inicio": "07:00", "fin": "19:00" } ],
    "jueves":    [ { "inicio": "07:00", "fin": "19:00" } ],
    "viernes":   [ { "inicio": "07:00", "fin": "19:00" } ],
    "sabado":    [ { "inicio": "08:00", "fin": "15:00" } ],
    "domingo":   []
  },
  "permitir_festivos": false,
  "frecuencia": {
    "max_contactos_dia": 1,
    "max_canales_semana": 1,
    "semana": "calendario",
    "solo_tras_contacto_directo": true
  }
}
```
Validación: `zona_horaria` debe existir en `zoneinfo`; las 7 claves de día son obligatorias (`lunes,
martes, miercoles, jueves, viernes, sabado, domingo`); horas `HH:MM` 24 h; `inicio < fin`; franjas de un
día ordenadas y sin solaparse; `max_contactos_dia` 1..10; `max_canales_semana` 1..10; `semana` ∈
{`calendario`,`movil_7_dias`}. La frecuencia **se almacena pero no se evalúa** en Fase 1.

Objeto `Politica`:
```json
{ "id": 1, "tipo_campana": "cobranza", "version": 1, "activa": true,
  "configuracion": { "...": "como arriba" }, "creado_por": null, "creado_en": "2026-10-23T15:00:00Z" }
```
- `GET /api/v1/cumplimiento/politicas` (todos) → `200 [Politica, Politica]` (solo activas; orden `tipo_campana`).
- `GET /api/v1/cumplimiento/politicas/{tipo_campana}/versiones` (A, S) → `200 [Politica]` orden `version` desc. 422 si el tipo no es válido.
- `PUT /api/v1/cumplimiento/politicas/{tipo_campana}` (A) cuerpo = `configuracion` → `201 Politica`
  (nueva versión `max+1`, activa; la anterior queda `activa=false`). Errores: 422 `VALIDACION`
  (tipo de campaña inválido o configuración inválida, con `detalles`).

**Festivos** — objeto `Festivo`:
```json
{ "id": 10, "fecha": "2026-11-02", "nombre": "Todos los Santos", "origen": "calculado", "activo": true }
```
- `GET /api/v1/festivos?anio=2026` (todos) → `200 [Festivo]` orden `fecha` (incluye inactivos). `anio`
  obligatorio, 1984..2100.
- `POST /api/v1/festivos/generar` (A) `{ "anio": 2027 }` → `200 { "anio": 2027, "creados": 18, "existentes": 0 }`.
  Idempotente: no modifica fechas existentes (ni manuales ni desactivadas). 422 si `anio` fuera de 1984..2100.
- `POST /api/v1/festivos` (A) `{ "fecha": "2026-12-31", "nombre": "Día cívico" }` → `201 Festivo`
  (`origen: "manual"`). 409 `FESTIVO_DUPLICADO`.
- `PATCH /api/v1/festivos/{id}` (A) `{ "activo": false, "nombre": "..." }` → `200 Festivo`; 404.

**Evaluación** — `POST /api/v1/cumplimiento/evaluar` (todos)
```json
// petición
{ "tipo_campana": "cobranza", "momento": "2026-11-02T10:00:00-05:00" }
// 200
{
  "permitido": false,
  "motivos": [ { "codigo": "FESTIVO", "mensaje": "2026-11-02 es festivo (Todos los Santos)." } ],
  "momento_local": "2026-11-02T10:00:00-05:00",
  "proxima_ventana_inicio": "2026-11-03T07:00:00-05:00",
  "politica_version": 1
}
```
`momento` opcional (por defecto: ahora); si se envía sin zona → 422 `VALIDACION`. Si `permitido=true`,
`motivos=[]` y `proxima_ventana_inicio=null`. Usa la política activa del tipo y los festivos **activos**
de la tabla. Códigos de motivo: `FESTIVO`, `DIA_SIN_FRANJA`, `FUERA_DE_FRANJA` (se devuelven todos los
que apliquen, en ese orden).

### 4.9 Motor puro (contrato interno, `app/modulos/cumplimiento/motor.py`)

```python
DiaSemana = Literal["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]

@dataclass(frozen=True)
class Motivo:
    codigo: Literal["FESTIVO", "DIA_SIN_FRANJA", "FUERA_DE_FRANJA"]
    mensaje: str

@dataclass(frozen=True)
class ResultadoEvaluacion:
    permitido: bool
    motivos: tuple[Motivo, ...]
    momento_local: datetime                    # en la zona de la política
    proxima_ventana_inicio: datetime | None    # None si permitido o si no hay ventana en el horizonte

def evaluar_horario(momento: datetime, politica: PoliticaCumplimiento,
                    festivos: Mapping[date, str]) -> ResultadoEvaluacion: ...
def proxima_ventana(momento: datetime, politica: PoliticaCumplimiento,
                    festivos: Mapping[date, str], horizonte_dias: int = 14) -> datetime | None: ...
```
- `momento` sin `tzinfo` → `ValueError`.
- Permitido ⇔ (no es festivo **o** `permitir_festivos`) **y** existe franja del día con
  `inicio <= hora_local < fin`.
- `proxima_ventana`: el instante más temprano `>= momento` en que la evaluación sería permitida (inicio de
  franja, o `momento` mismo si ya lo es), buscando hasta `horizonte_dias`; `None` si no existe.
- Sin E/S, sin `datetime.now()` (el llamador inyecta el momento).

`app/modulos/cumplimiento/festivos.py`:
```python
def festivos_colombia(anio: int) -> dict[date, str]: ...   # ValueError fuera de 1984..2100
```
- Fijos (no se trasladan): 1-ene Año Nuevo; 1-may Día del Trabajo; 20-jul Independencia; 7-ago Batalla
  de Boyacá; 8-dic Inmaculada Concepción; 25-dic Navidad.
- Trasladables al lunes siguiente si no caen en lunes: 6-ene Reyes Magos; 19-mar San José; 29-jun San
  Pedro y San Pablo; 15-ago Asunción de la Virgen; 12-oct Día de la Raza; 1-nov Todos los Santos;
  11-nov Independencia de Cartagena.
- Según Pascua (P, algoritmo gregoriano anónimo): Jueves Santo P−3; Viernes Santo P−2; Ascensión P+43;
  Corpus Christi P+64; Sagrado Corazón P+71 (ya caen en lunes).
- Si dos festivos coinciden en fecha, un solo registro con nombres unidos por `"; "` en orden alfabético.

`app/modulos/importacion/telefonos.py`:
```python
@dataclass(frozen=True)
class TelefonoNormalizado:
    numero_e164: str            # "+573001234567"
    tipo_linea: Literal["movil", "fijo"]

class ErrorTelefono(Exception):
    codigo: Literal["TELEFONO_REQUERIDO","TELEFONO_INVALIDO","TELEFONO_NO_COLOMBIANO","TELEFONO_TIPO_NO_PERMITIDO"]

def normalizar_telefono(crudo: str | None) -> TelefonoNormalizado: ...   # lanza ErrorTelefono
```

### 4.10 Tipos TypeScript (`frontend/src/api/tipos.ts`)

```ts
export type Rol = 'administrador' | 'supervisor' | 'agente';
export type TipoCampana = 'venta' | 'cobranza';
export type EstadoCampana = 'borrador' | 'activa' | 'pausada' | 'finalizada';
export type Severidad = 'error' | 'advertencia';
export type MotivoExclusion = 'rne' | 'solicitud_titular' | 'numero_errado' | 'manual';
export type AplicaA = 'venta' | 'cobranza' | 'todas';
export type DiaSemana = 'lunes'|'martes'|'miercoles'|'jueves'|'viernes'|'sabado'|'domingo';

export interface ErrorRespuesta { error: { codigo: string; mensaje: string; detalles: { campo: string | null; mensaje: string }[] } }
export interface Pagina<T> { items: T[]; total: number; page: number; page_size: number }

export interface Usuario { id: number; email: string; nombre: string; rol: Rol; activo: boolean; creado_en?: string; actualizado_en?: string }
export interface RespuestaLogin { access_token: string; token_type: 'bearer'; expires_in: number; usuario: Usuario }

export interface Campana {
  id: number; nombre: string; tipo: TipoCampana; descripcion: string | null; estado: EstadoCampana;
  fecha_inicio: string | null; fecha_fin: string | null; guion: string | null;
  max_intentos: number; intervalo_reintento_minutos: number; total_clientes: number;
  creado_por: number; creado_en: string; actualizado_en: string;
}
export type CampanaCrear = Pick<Campana, 'nombre' | 'tipo'> & Partial<Pick<Campana,
  'descripcion' | 'fecha_inicio' | 'fecha_fin' | 'guion' | 'max_intentos' | 'intervalo_reintento_minutos'>>;
export type CampanaActualizar = Partial<Omit<CampanaCrear, 'tipo'> & { estado: EstadoCampana }>;

export interface ErrorImportacion { fila: number; campo: string | null; codigo: string; mensaje: string; severidad: Severidad }
export interface Importacion {
  id: number; campana_id: number; nombre_archivo: string; estado: 'completada' | 'fallida';
  total_filas: number; filas_importadas: number; filas_duplicadas: number; filas_invalidas: number; filas_excluidas: number;
  creado_por: number; creado_en: string; errores?: ErrorImportacion[]; errores_truncados?: boolean;
}
export interface Telefono { id: number; numero_e164: string; tipo_linea: 'movil' | 'fijo'; prioridad: number; excluido: boolean }
export interface CampanaCliente {
  id: number; estado: 'pendiente' | 'en_gestion' | 'gestionado' | 'descartado'; intentos: number;
  cliente: { id: number; tipo_documento: string; numero_documento: string; nombre: string; email: string | null; ciudad: string | null };
  telefonos: Telefono[];
  numero_obligacion: string | null; saldo_total: string | null; saldo_mora: string | null; dias_mora: number | null;
  fecha_vencimiento: string | null; producto: string | null; oferta: string | null;
  datos_adicionales: Record<string, string>; importacion_id: number | null; creado_en: string;
}
export interface Exclusion { id: number; numero_e164: string; motivo: MotivoExclusion; aplica_a: AplicaA; observacion: string | null; creado_por: number; creado_en: string }
export interface ResultadoImportacionExclusiones { total_filas: number; creadas: number; duplicadas: number; invalidas: number; errores: ErrorImportacion[]; errores_truncados: boolean }

export interface Franja { inicio: string; fin: string }
export interface ConfiguracionPolitica {
  zona_horaria: string; franjas: Record<DiaSemana, Franja[]>; permitir_festivos: boolean;
  frecuencia: { max_contactos_dia: number; max_canales_semana: number; semana: 'calendario' | 'movil_7_dias'; solo_tras_contacto_directo: boolean };
}
export interface Politica { id: number; tipo_campana: TipoCampana; version: number; activa: boolean; configuracion: ConfiguracionPolitica; creado_por: number | null; creado_en: string }
export interface Festivo { id: number; fecha: string; nombre: string; origen: 'calculado' | 'manual'; activo: boolean }
export interface ResultadoEvaluacion {
  permitido: boolean; motivos: { codigo: 'FESTIVO' | 'DIA_SIN_FRANJA' | 'FUERA_DE_FRANJA'; mensaje: string }[];
  momento_local: string; proxima_ventana_inicio: string | null; politica_version: number;
}
```

---

## 5. Configuración (`.env.example`)

```
# Backend
ENTORNO=desarrollo                 # desarrollo | test | produccion
DATABASE_URL=postgresql+psycopg://outbound:outbound@db:5432/outbound
JWT_SECRETO=cambia-esto-por-un-secreto-de-32-caracteres-o-mas
JWT_EXPIRACION_MINUTOS=480
BCRYPT_COSTE=12
CORS_ORIGENES=http://localhost:5173
IMPORTACION_MAX_BYTES=10485760
IMPORTACION_MAX_FILAS=50000
ADMIN_PASSWORD=                    # opcional para `crear-admin` no interactivo
# Postgres
POSTGRES_USER=outbound
POSTGRES_PASSWORD=outbound
POSTGRES_DB=outbound
# Frontend
VITE_PROXY_TARGET=http://backend:8000
```

`docker-compose.yml`: servicios `db` (healthcheck `pg_isready`, volumen `pgdata`, puerto 5432),
`backend` (depende de `db` healthy; comando `alembic upgrade head && python -m app.cli generar-festivos --desde 2025 --hasta 2028 && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`;
puerto 8000; monta `./backend`), `frontend` (`npm ci && npm run dev -- --host 0.0.0.0`; puerto 5173;
monta `./frontend` con `node_modules` en volumen anónimo). Sin secretos reales en el repositorio.

---

## 6. Tareas

### [backend]

**B1 — Esqueleto y configuración.** `backend/pyproject.toml`, `app/main.py`, `app/config.py`,
`app/db.py` (incl. `FechaHoraUTC`), `app/errores.py`, `app/paginacion.py`, `Dockerfile`,
`docker-compose.yml`, `.env.example`, `.gitignore`.
*Acepta*: `pip install -e ".[dev]"` y `pytest` funcionan **sin Docker ni PostgreSQL**; `GET /api/v1/salud`
→ 200; toda respuesta de error sigue §4.1 (incl. 404 de ruta y 422 de FastAPI); `ruff check .` limpio;
la app no arranca con `JWT_SECRETO` < 32 caracteres salvo `ENTORNO=test`.

**B2 — Modelos y migración inicial.** Modelos SQLAlchemy de §3 y `alembic/versions/0001_esquema_inicial.py`
(con semilla de políticas). `render_as_batch=True`.
*Acepta*: `alembic upgrade head` funciona en SQLite y PostgreSQL; `alembic downgrade base` también;
`test_migraciones.py` verifica tablas y las 2 políticas sembradas; `alembic check` no detecta
diferencias entre modelos y migración.

**B3 — Autenticación y usuarios.** `app/seguridad.py`, `app/dependencias.py`, módulos `auth` y
`usuarios`, `app/cli.py crear-admin`.
*Acepta*: contratos §4.3-4.4; rol efectivo leído de BD; usuario desactivado recibe 401 con token aún
vigente; token expirado o firmado con otro secreto → 401 `NO_AUTENTICADO`; auditoría de login.

**B4 — Campañas.** Módulo `campanas` según §4.5.
*Acepta*: todas las transiciones válidas e inválidas de la tabla; `total_clientes` correcto; agente solo
ve activas y recibe 403 al escribir; `DELETE` solo en borrador.

**B5 — Lógica pura de importación.** `importacion/telefonos.py`, `normalizacion.py`, `lector_csv.py`.
*Acepta*: casos de §7 (QA) en verde sin BD.

**B6 — Servicio y API de importación + clientes de campaña.** §4.6.
*Acepta*: invariante de conteos; dedupe en archivo y en campaña; upsert de cliente global entre
campañas; exclusiones por tipo; transacción única; 413/422/409 de archivo; `errores` truncado a 100;
listado de clientes con `excluido` calculado.

**B7 — Exclusiones.** §4.7.
*Acepta*: normalización del teléfono antes de guardar; `rne` → `aplica_a=venta` por defecto;
409 duplicado; importación masiva con conteos correctos; auditoría.

**B8 — Cumplimiento.** `cumplimiento/politica.py`, `festivos.py`, `motor.py` (puros) + servicio, router y
`cli.py generar-festivos --desde --hasta`. §4.8-4.9.
*Acepta*: casos de §7 en verde; `PUT` crea nueva versión y desactiva la anterior; `evaluar` usa solo
festivos activos; generación idempotente.

**B9 — Auditoría.** Módulo `auditoria` y llamadas desde B3/B4/B6/B7/B8 con las acciones de §3.
*Acepta*: cada acción listada genera una fila sin datos personales en `detalle`.

### [frontend]

**F1 — Esqueleto.** Vite + React + TS, ESLint, Vitest + Testing Library, `Dockerfile`, proxy `/api`.
*Acepta*: `npm run build`, `npm run lint`, `npm test -- --run` en verde.

**F2 — Cliente API y sesión.** `api/cliente.ts`, `api/tipos.ts` (§4.10 literal), `api/endpoints.ts`,
`auth/AuthContext.tsx`, `auth/RutaProtegida.tsx`, `paginas/Login.tsx`.
*Acepta*: login guarda sesión en `sessionStorage`; 401 en cualquier llamada → cierra sesión y va a
`/login`; errores muestran `error.mensaje` y `detalles` junto al campo; navegación según rol (agente solo
ve Campañas y Cumplimiento).

**F3 — Campañas.** `Campanas.tsx`, `CampanaFormulario.tsx`, `CampanaDetalle.tsx`.
*Acepta*: listar con filtros (estado, tipo, búsqueda) y paginación; crear/editar con validación en
cliente equivalente a §4.5; botones de transición solo para las válidas del estado actual; eliminar
solo en borrador con confirmación; estados de carga/vacío/error.

**F4 — Importación y clientes.** En `CampanaDetalle.tsx` + `ImportacionDetalle.tsx`.
*Acepta*: subir `.csv` (input con `accept=".csv"`, aviso si > 10 MiB antes de enviar); mostrar resumen
(5 contadores) y tabla de errores con severidad; historial de importaciones; tabla de clientes con
teléfonos (marcando excluidos), búsqueda y paginación; montos formateados como COP (`Intl.NumberFormat('es-CO', {style:'currency', currency:'COP'})`).

**F5 — Exclusiones.** `Exclusiones.tsx`: listar/buscar/filtrar, alta individual, eliminar con
confirmación, carga masiva con resumen.

**F6 — Cumplimiento.** `Cumplimiento.tsx`: políticas activas en lectura (tabla por día), festivos por
año (admin: generar año, añadir manual, activar/desactivar), evaluador (tipo + fecha/hora local
Bogotá → muestra permitido, motivos y próxima ventana).
*Acepta*: el `momento` enviado lleva siempre offset `-05:00`; las horas se muestran en
`America/Bogota` independientemente de la zona del navegador.

**F7 — Usuarios.** `Usuarios.tsx` (solo admin): listar, crear, cambiar rol, activar/desactivar,
restablecer contraseña.

Accesibilidad mínima en todo: `label` asociado a cada campo, foco visible, mensajes de error con
`role="alert"`, tablas con `<th scope>`.

### [qa]

Backend (`pytest`, sin Docker):
- **Teléfonos**: `3001234567`, `300 123 4567`, `+57 300-123-4567`, `573001234567`,
  `3001234567.0` → `+573001234567`/`movil`; `6012345678`, `(601) 234 5678` → `+576012345678`/`fijo`;
  `""`/`None` → `TELEFONO_REQUERIDO`; `2345678`, `12345`, `abc` → `TELEFONO_INVALIDO`;
  `+1 415 555 2671` → `TELEFONO_NO_COLOMBIANO`; `018000123456` → `TELEFONO_TIPO_NO_PERMITIDO` o
  `TELEFONO_INVALIDO` (verificar qué devuelve `phonenumbers` y documentarlo en el test).
- **Montos/fechas/documentos**: `1.234.567,89`→1234567.89; `$ 1.500.000`→1500000; `1500.5`→1500.50;
  `1,234.56`, `-5`, `abc` → inválido; `2026-09-15` y `15/09/2026` válidos; `31/02/2026` inválido; NIT
  `900.123.456-7` → `9001234567`; CC `1.020.304.050` → `1020304050`.
- **CSV**: UTF-8, UTF-8 con BOM, cp1252 (tildes en nombres), separador `;` y `,`, cabeceras con tildes y
  mayúsculas (`Teléfono 1` → `telefono_1`), líneas vacías, columna obligatoria faltante (422), 0 filas
  (422), > máx. filas (422, con límite bajado por configuración en el test), > tamaño (413), extensión
  `.txt` (422).
- **Festivos**: 2026 = 18 fechas exactas (1-ene, 12-ene, 23-mar, 2-abr, 3-abr, 1-may, 18-may, 8-jun,
  15-jun, 29-jun, 20-jul, 7-ago, 17-ago, 12-oct, 2-nov, 16-nov, 8-dic, 25-dic); 2025 = 17 fechas (1-ene,
  6-ene, 24-mar, 17-abr, 18-abr, 1-may, 2-jun, 23-jun, 30-jun con nombres unidos "Sagrado Corazón; San
  Pedro y San Pablo", 20-jul domingo no trasladado, 7-ago, 18-ago, 13-oct, 3-nov, 17-nov, 8-dic, 25-dic);
  `1983` y `2101` → `ValueError`.
- **Motor** (política por defecto, festivos 2026):
  - vie 2026-10-23 06:59 −05 → no, `FUERA_DE_FRANJA`, próxima `2026-10-23T07:00-05:00`;
  - vie 07:00 → sí; vie 18:59:59 → sí; vie 19:00 → no, próxima `2026-10-24T08:00-05:00`;
  - sáb 2026-10-24 14:59 → sí; 15:00 → no, próxima `2026-10-26T07:00-05:00`;
  - dom 2026-10-25 10:00 → no, `DIA_SIN_FRANJA`, próxima `2026-10-26T07:00-05:00`;
  - lun 2026-11-02 10:00 → no, `FESTIVO`, próxima `2026-11-03T07:00-05:00`;
  - jue 2026-04-02 10:00 → no, `FESTIVO`, próxima `2026-04-04T08:00-05:00` (viernes santo intermedio);
  - `2026-10-23T12:00:00Z` (=07:00 Bogotá) → sí; datetime ingenuo → `ValueError`;
  - `permitir_festivos=true` → lun 2026-11-02 10:00 sí;
  - política con dos franjas (07:00-12:00, 14:00-19:00): 13:00 → no, próxima 14:00 mismo día;
  - política con todos los días vacíos → no, `proxima_ventana_inicio=None`.
- **Política**: rechaza solapes, `inicio >= fin`, día faltante, clave extra, zona inexistente, `25:00`.
- **API**: matriz de permisos completa de §4.1 (un test parametrizado por rol × endpoint); login ok/
  fallido/inactivo; token expirado y con firma ajena; usuario desactivado con token vigente → 401;
  campañas (CRUD, transiciones válidas/ inválidas, `CAMPANA_SIN_CLIENTES`, `CAMPANA_FINALIZADA`,
  `NOMBRE_DUPLICADO`, `tipo` no editable, borrar no-borrador → 409); importación con un CSV de fixture que
  produzca a la vez filas importadas, duplicadas en archivo, duplicadas en campaña (segunda importación),
  inválidas y excluidas, verificando la invariante de conteos y que el mismo cliente en dos campañas es un
  único `clientes`; `errores_truncados` con > 100 errores; exclusiones (alta, duplicado, rne por defecto
  venta, importación masiva); políticas (PUT crea versión, la anterior queda inactiva, 422 inválida);
  festivos (generar idempotente, manual duplicado 409, desactivar y verificar que `evaluar` lo ignora);
  `evaluar` sin zona → 422; formato de error común en 401/403/404/409/413/422.
- **Migraciones**: `upgrade head` + `downgrade base` en SQLite temporal.

Frontend (Vitest + Testing Library, `fetch` simulado):
- Login: éxito redirige; error 401 muestra mensaje; 422 muestra detalle por campo.
- `RutaProtegida`: sin sesión → `/login`; agente en `/usuarios` → no autorizado.
- Cliente API: 401 limpia `sessionStorage`.
- Campañas: botones de transición correctos por estado; formulario valida `fecha_fin >= fecha_inicio`.
- Importación: muestra los 5 contadores y la tabla de errores; rechaza archivo > 10 MiB sin llamar a la API.
- Evaluador: envía `momento` con `-05:00` y muestra motivos/próxima ventana.

Criterio global: `cd backend && pytest` y `cd frontend && npm test -- --run && npm run build && npm run lint`
en verde; `docker compose up` arranca y permite hacer login con un admin creado por CLI.

### [docs]
- `README.md` raíz: descripción del producto, requisitos (Python 3.12, Node 22, Docker opcional),
  arranque con Docker Compose, arranque sin Docker (backend con SQLite/PostgreSQL local), crear admin,
  generar festivos, ejecutar tests, formato CSV de importación con ejemplo y lista de códigos de error.
- `backend/README.md` breve (estructura, comandos) y `frontend/README.md` breve.
- `docs/importacion-csv.md`: columnas, reglas de normalización, ejemplos de archivo válido para venta y
  cobranza.
- `CHANGELOG.md` con sección `[Unreleased]` describiendo la Fase 1.
- Enlazar `docs/arquitectura/README.md` y los ADR desde el README raíz.

---

## 7. Riesgos y preguntas abiertas

### Bloquean la Fase 1
Ninguna bloquea: se adoptan los supuestos marcados como **(S)**, que el orquestador debe confirmar con
el usuario pero que pueden cambiarse después con coste bajo.

- **(S1)** El **documento** (`tipo_documento` + `numero_documento`) es obligatorio en el CSV, también en
  campañas de venta. Es la clave del cliente global y de los límites de frecuencia entre campañas. Si las
  bases de venta llegan sin documento, alternativa: clave por `telefono_1` normalizado (cambio acotado al
  servicio de importación).
- **(S2)** Un registro por cliente y campaña (`UNIQUE(campana_id, cliente_id)`); un deudor con varias
  obligaciones en la misma campaña conserva solo la primera fila (las demás cuentan como duplicadas). Si se
  necesitan varias obligaciones, se añadirá una tabla `obligaciones` en fase 2.
- **(S3)** Las exclusiones RNE se cargan por CSV exportado de la plataforma de la CRC (consulta manual,
  lotes de hasta 10 000 números); la integración con el webservice queda para fase 5.
- **(S4)** Los agentes no ven clientes ni importaciones en Fase 1 (la asignación agente↔campaña llega en fase 2).

### No bloquean (fases posteriores)
- **Frecuencia Ley 2300**: interpretación de "semana" (calendario vs. 7 días móviles), si los intentos
  sin contacto cuentan, si aplica igual a ventas que a cobranza, y cómo se consolida entre canales si en el
  futuro hay SMS/WhatsApp. Configurable; requiere criterio del área legal antes de fase 3.
- **Autorización de otros horarios por el consumidor** (excepción art. 3): ¿se gestionará? ¿cómo se
  acredita el documento? Afecta fase 3.
- **RNE y clientes con relación contractual**: ¿las ofertas a clientes actuales se consideran
  comerciales sujetas a RNE? Por defecto sí (más restrictivo).
- **Frecuencia de actualización/consulta del RNE**: no se encontró plazo explícito; la CRC emitió
  conceptos en 2026 sobre frecuencia de consulta. Confirmar con el área legal.
- **Twilio**: número/caller ID colombiano (+57) y requisitos regulatorios del número; cuenta y TwiML App;
  URL pública para webhooks; coste por minuto; dónde se almacenan las grabaciones (Twilio vs. propio,
  retención).
- **Cumplimiento de promesas de pago**: requiere los pagos reales; ¿llegarán por CSV periódico o por
  integración con el sistema de cartera del cliente? Afecta fase 4.
- **Reglas de reintento** por resultado y horario preferente por cliente.
- **Volumen**: importación síncrona hasta 50 000 filas; si las bases son mayores, pasar a importación en
  segundo plano (fase 2) con estado `procesando`.
- **Seguridad**: limitación de intentos de login, refresh tokens/cookies httpOnly y CSP (fase 2).
- **Retención y supresión** de datos de campañas finalizadas (política del responsable del tratamiento).
- **Precisión del cierre de franja**: la franja limita el inicio de la llamada; si se exige que termine
  antes de las 19:00/15:00, configurar un `fin` anticipado (p. ej. 18:50).
- **Metadatos de `phonenumbers`**: rangos nuevos de numeración podrían no reconocerse hasta actualizar la
  librería.
