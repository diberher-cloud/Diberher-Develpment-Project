# Frontend — interfaz de la plataforma outbound

SPA en React 18 + TypeScript + Vite, sin librerías de componentes ni de estado. Consume la API de `backend/`
bajo `/api/v1`. Desde la subfase 2A incluye la consola del agente, el softphone (`@twilio/voice-sdk`, versión
`^2.18.5` en `package.json`) y el tiempo real por WebSocket. Desde la subfase 2B incluye la bandeja de WhatsApp, la
página de plantillas, las autorizaciones, el simulador de WhatsApp (solo fuera de producción) y el estado del worker
en la supervisión. La visión general está en el [README raíz](../README.md).

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
    ├── tiempo_real/         # 2A: conexion.ts (WebSocket, ticket, reconexión, ping) y TiempoRealContext.tsx
    ├── telefonia/           # 2A: softphone.ts (interfaz), softphoneTwilio.ts, softphoneFalso.ts, crearSoftphone.ts
    ├── componentes/         # Layout, Campo, Cargando, MensajeError, Paginador, SelectorCsv,
    │                        # ImportarClientes, ResumenImportacion
    │   ├── consola/         # 2A: SelectorEstado, ListaTrabajo, FichaCliente, Guion, BarraLlamada,
    │   │                    #     FormularioTipificacion, HistorialGestiones
    │   ├── CampanaAgentes.tsx        # 2A: pestaña Agentes del detalle de campaña
    │   ├── TipificacionesCampana.tsx # 2A: pestaña Tipificaciones del detalle de campaña
    │   ├── bandeja/         # 2B: ColaAtencion, ListaConversaciones, VistaConversacion, BurbujaMensaje, CompositorMensaje,
    │   │                    #     SelectorPlantilla, AdjuntoMedia, AccionesConversacion, AsignarA, VincularRegistro,
    │   │                    #     CerrarConversacion
    │   ├── ContextoWhatsApp.tsx      # 2B: configuración de WhatsApp y contador de no leídos (menú "Bandeja (n)")
    │   └── TarjetaWorker.tsx         # 2B: estado del worker y de la cola en Supervisión
    ├── paginas/             # Login, Campanas, CampanaFormulario, CampanaDetalle, ImportacionDetalle,
    │                        # Exclusiones, Cumplimiento, Usuarios
    │                        # 2A: Consola (agente), SupervisionAgentes (administrador y supervisor)
    │                        # 2B: Bandeja (todos), PlantillasWhatsApp y Autorizaciones (administrador y supervisor),
    │                        #     SimuladorWhatsApp (solo con simulación habilitada)
    ├── utilidades/          # formato.ts (COP, fechas, offset -05:00), campanas.ts, useCarga.ts,
    │                        # consola.ts (etiquetas de estados y llamadas), tipificacion.ts (resultados)
    └── test/                # Vitest + Testing Library; fetch simulado; WebSocket y Device simulados
```

## Rutas

| Ruta | Acceso |
|---|---|
| `/login` | público |
| `/campanas`, `/campanas/:id`, `/cumplimiento` | cualquier usuario con sesión |
| `/campanas/nueva`, `/campanas/:id/editar`, `/importaciones/:id`, `/exclusiones` | administrador y supervisor |
| `/supervision/agentes` (2A) | administrador y supervisor |
| `/bandeja` (2B) | todos los roles (el agente ve sus conversaciones; A y S, todas) |
| `/whatsapp/plantillas`, `/autorizaciones` (2B) | administrador y supervisor |
| `/whatsapp/simulador` (2B) | cualquier usuario con sesión; el menú solo lo muestra si `GET /whatsapp/configuracion` devuelve `simulacion: true` |
| `/consola` (2A) | agente |
| `/usuarios` | administrador |

Cualquier otra ruta redirige a `/campanas`. Un agente solo ve campañas activas, el cumplimiento y la consola; las
pantallas de gestión no están disponibles para él. En el menú, **Consola** aparece solo para agentes y
**Supervisión** solo para administradores y supervisores. El detalle de campaña (`/campanas/:id`) tiene las
pestañas **Clientes**, **Agentes** y **Tipificaciones**. Las dos últimas son para administrador y supervisor.

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

El proxy de `/api` reenvía también el WebSocket (`ws: true` en `vite.config.ts`), que el cliente abre en
`/api/v1/ws?ticket=…`. Las variables de telefonía del backend no pasan por el frontend. Ver
[`docs/telefonia-twilio.md`](../docs/telefonia-twilio.md).

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
- **Importación de CSV y Excel.** `SelectorCsv` usa `accept=".csv,.xlsx"` y avisa si el archivo supera 10 MiB antes de
  enviarlo. Las reglas completas del archivo están en `docs/importacion-csv.md`.
- **Tiempo real (2A).** `conexion.ts` pide un ticket con `POST /ws/ticket` antes de **cada** intento de conexión y
  abre `/api/v1/ws?ticket=…`. Reconecta con espera exponencial de 1 s a 30 s y envía `ping` cada 30 s. Ante un
  cierre 4401 pide un ticket nuevo **una vez**; si vuelve a fallar, cierra la sesión. Al reconectar, la interfaz
  recarga el estado por REST, porque la base de datos es la fuente de verdad. `useEventoTiempoReal(tipo, handler)`
  reparte los eventos por tipo.
- **Softphone (2A).** `crearSoftphone` elige la implementación según `proveedor` del token: `falso` →
  `SoftphoneFalso` (sin audio; usa los endpoints de simulación), `twilio` → `SoftphoneTwilio` (carga
  `@twilio/voice-sdk` de forma diferida). El softphone de Twilio no llama a `device.register()` y renueva el token
  en `tokenWillExpire`. Con el proveedor falso, la barra de llamada muestra los botones **Contesta**,
  **No contesta** y **Ocupado** (solo en desarrollo).
- **Números en la consola (2A).** La interfaz solo muestra `numero_mascara` (`+57300****567`). El navegador envía
  ids (`campana_cliente_id`, `telefono_id`) y el servidor resuelve el número.
- **Accesibilidad de la consola (2A).** El estado de la llamada se anuncia con `role="status"` y
  `aria-live="polite"`. Los errores usan `role="alert"`.
- **Bandeja (2B).** Los mensajes nuevos se anuncian con `aria-live="polite"`. El compositor cuenta los caracteres
  (máximo 4096). Enter envía y Mayús+Enter salta de línea. Cada envío genera una `idempotencia_clave` (UUID v4; `crypto.randomUUID()`, con alternativa por `getRandomValues`)
  que se reutiliza si se reintenta el mismo texto. Un 4xx la libera, para que el siguiente intento sea nuevo.
- **Datos de la conversación (2B).** La interfaz nunca muestra un E.164 completo a un agente: solo `numero_mascara`. El
  número completo solo lo ven administrador y supervisor (campo `numero_e164`).
- **Auditoría de la apertura.** La conversación se pide con `GET /conversaciones/{id}?apertura=true` solo al abrirla. Las
  recargas, los refrescos por evento y la reconexión la piden sin ese parámetro, así que solo la apertura queda auditada.
- **Adjuntos (2B).** `AdjuntoMedia` descarga el archivo con `fetch` y Bearer, y lo muestra desde un `blob:` (una imagen con
  `<img src>` no puede enviar el JWT). La URL `blob:` se revoca al desmontar el componente.
- **Eventos de WhatsApp (2B).** `conversacion.mensaje`, `conversacion.estado` y `atencion.cola` se reparten con
  `useEventoTiempoReal`. Una conversación que no es la abierta no altera la vista. El contador de no leídos se refresca
  con los mismos eventos.
