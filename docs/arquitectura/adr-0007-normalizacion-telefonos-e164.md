# ADR-0007: Normalización de teléfonos colombianos a E.164

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
Las bases llegan con formatos heterogéneos ("300 123 4567", "+57 300-123-4567", "573001234567",
"(601) 234 5678", "3001234567.0" por exportaciones de Excel). Desde 2021-2022 la marcación fija en
Colombia es de 10 dígitos (`60X` + 7 dígitos); los móviles son `3XX` + 7 dígitos. Twilio exige E.164. La
deduplicación y las exclusiones (RNE) deben comparar el mismo formato.

## Decisión
- Función pura `normalizar_telefono(crudo: str) -> TelefonoNormalizado | ErrorTelefono` en
  `app/modulos/importacion/telefonos.py`, usando **`phonenumbers`** (port de libphonenumber de Google)
  con región por defecto `CO`.
- Preprocesado determinista antes de `phonenumbers`:
  1. `strip()`; si coincide `^\d+\.0$` quitar `.0`.
  2. Quitar todo lo que no sea dígito salvo un `+` inicial.
  3. Si quedan 12 dígitos que empiezan por `57` y no hay `+`, anteponer `+`.
- Aceptar solo números **válidos** (`is_valid_number`) de **Colombia** (`region_code_for_number == "CO"`)
  y de tipo `MOBILE` (→ `movil`) o `FIXED_LINE` / `FIXED_LINE_OR_MOBILE` (→ `fijo`).
- Errores: `TELEFONO_REQUERIDO` (vacío), `TELEFONO_INVALIDO`, `TELEFONO_NO_COLOMBIANO`,
  `TELEFONO_TIPO_NO_PERMITIDO` (01-8000, premium, etc.).
- Se persiste siempre `numero_e164` (`+573001234567`) y `tipo_linea`.

## Alternativas consideradas
- **Expresiones regulares propias**: frágiles ante cambios del plan de numeración; `phonenumbers` se
  actualiza con el plan oficial.

## Consecuencias
- + Dedupe y exclusiones fiables; formato listo para Twilio.
- − Dependencia con metadatos que cambian: fijar versión menor y actualizar periódicamente.
- − Números fijos antiguos de 7 dígitos se rechazan (no se puede inferir el indicativo): se informa en el
  resumen de importación.
