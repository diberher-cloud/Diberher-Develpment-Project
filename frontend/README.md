# Frontend — interfaz de la plataforma outbound

SPA en React 18 + TypeScript + Vite, sin librerías de componentes ni de estado (Fase 1). Consume la API
de `backend/` bajo `/api/v1`. La visión general está en el [README raíz](../README.md).

Requisitos: Node 22 LTS.

## Estructura

```
frontend/
├── index.html
├── vite.config.ts           # puerto 5173, proxy /api → VITE_PROXY_TARGET, configuración de Vitest
├── eslint.config.js
├── tsconfig.json
├── Dockerfile
└── src/
    ├── main.tsx             # arranque de React
    ├── App.tsx              # rutas y restricciones por rol
    ├── api/
    │   ├── cliente.ts       # fetch con token; convierte el error común en ErrorApi
    │   ├── endpoints.ts     # funciones por endpoint
    │   ├── tipos.ts         # tipos TypeScript de los contratos de la API
    │   └── sesion.ts        # sesión en sessionStorage
    ├── auth/
    │   ├── AuthContext.tsx  # sesión en memoria, login y cierre de sesión
    │   └── RutaProtegida.tsx# exige sesión y, si se indica, un rol
    ├── componentes/         # Layout, Campo, Cargando, MensajeError, Paginador, SelectorCsv,
    │                        # ImportarClientes, ResumenImportacion
    ├── paginas/             # Login, Campanas, CampanaFormulario, CampanaDetalle, ImportacionDetalle,
    │                        # Exclusiones, Cumplimiento, Usuarios
    ├── utilidades/          # formato.ts (COP, fechas, offset -05:00), campanas.ts, useCarga.ts
    └── test/                # Vitest + Testing Library; fetch simulado
```

## Rutas

| Ruta | Acceso |
|---|---|
| `/login` | público |
| `/campanas`, `/campanas/:id`, `/cumplimiento` | cualquier usuario con sesión |
| `/campanas/nueva`, `/campanas/:id/editar`, `/importaciones/:id`, `/exclusiones` | administrador y supervisor |
| `/usuarios` | administrador |

Cualquier otra ruta redirige a `/campanas`. Un agente solo ve campañas activas y el cumplimiento; las
pantallas de gestión no están disponibles para él.

## Comandos

```bash
npm ci                       # instalación exacta según package-lock.json
npm run dev                  # servidor de desarrollo en http://localhost:5173
npm test -- --run            # Vitest, una sola ejecución
npm run lint                 # ESLint
npm run build                # tsc -b && vite build
npm run preview              # sirve el build de producción
```

## Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `VITE_PROXY_TARGET` | `http://localhost:8000` | Destino del proxy de `/api` en el servidor de desarrollo. |

`vite.config.ts` lee `VITE_PROXY_TARGET` de `process.env`, así que debe exportarse en la shell o
declararse en el entorno del proceso. Un fichero `.env` no basta para este valor. Ejemplo:

```bash
VITE_PROXY_TARGET=http://localhost:8001 npm run dev
```

Con Docker Compose, el servicio `frontend` lo recibe del `.env` de la raíz y apunta a `http://backend:8000`.

## Convenciones

- **Errores de la API.** `cliente.ts` convierte la respuesta de error común (`{ "error": { codigo,
  mensaje, detalles } }`) en `ErrorApi`. Los mensajes de campo se muestran junto al campo con
  `detalleDe(campo)`; el resto, en `MensajeError`. Una respuesta 401 limpia la sesión de `sessionStorage`
  y `AuthContext` es notificado para cerrarla.
- **Montos.** Se muestran como COP con `Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP' })`.
- **Horas del evaluador de cumplimiento.** Se envían siempre con offset `-05:00`, independientemente de la
  zona del navegador (`momentoBogota` en `utilidades/formato.ts`).
- **Accesibilidad.** Cada campo tiene `label` asociado, los errores usan `role="alert"` y las tablas usan
  `<th scope>`.
- **Importación de CSV.** `SelectorCsv` usa `accept=".csv"` y avisa si el archivo supera 10 MiB antes de
  enviarlo. Las reglas completas del archivo están en `docs/importacion-csv.md`.
