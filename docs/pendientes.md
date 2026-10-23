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
  - Hoy la frecuencia se **guarda** en la política (`configuracion.frecuencia`) pero **no se evalúa**.
    Debe resolverse antes de la fase 3.
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
