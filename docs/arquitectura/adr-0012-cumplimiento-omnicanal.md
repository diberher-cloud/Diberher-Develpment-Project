# ADR-0012: Cumplimiento omnicanal (franjas, frecuencia, autorización de canal y opt-out)

- Estado: aceptado (2A: frecuencia en voz; 2B-2E: WhatsApp)
- Fecha: 2026-10-23
- Complementa: ADR-0002 (motor puro), ADR-0008 (datos personales)

## Contexto
- **Ley 2300/2023, art. 3**: franjas L-V 07:00-19:00 y sáb 08:00-15:00, sin domingos ni festivos; tras
  contacto directo, no contactar por varios canales en la misma semana ni más de una vez el mismo día. El
  parágrafo extiende las franjas a mensajes publicitarios por SMS, **mensajería por aplicaciones**,
  correo y llamadas comerciales → aplica a WhatsApp.
- **Ley 2300, art. 2**: solo se contacta por los **canales que el consumidor autorice**.
- **Meta**: exige opt-in antes de enviar mensajes iniciados por la empresa y respetar el opt-out.
- **RNE (CRC)**: excluye comunicaciones comerciales/publicitarias a números inscritos.
- La interpretación jurídica de "semana", "contacto" y del alcance a respuestas sigue abierta
  (docs/pendientes.md §1): todo debe ser configuración.

## Decisión
1. **Un solo motor puro** (`cumplimiento/motor.py`) para todos los canales. Se añade
   `evaluar_contacto(momento, canal, politica, festivos, historial, entrante=False)` que combina
   horario (existente) y **frecuencia** (nuevo, `evaluar_frecuencia`). Motivos nuevos:
   `FRECUENCIA_DIA`, `FRECUENCIA_MEDIOS`. Sin E/S; el historial se inyecta como lista de
   `IntentoPrevio`.
2. **Semántica de frecuencia** (configurable en `politica.frecuencia`):
   - Ventana "semana": `calendario` (lunes 00:00 a domingo 23:59:59 local) o `movil_7_dias`
     (`(momento − 7 d, momento]`).
   - Historial considerado: intentos **del mismo cliente global** en campañas **del mismo tipo** que la
     política evaluada (la finalidad: cobranza o venta), de **todos los canales**.
   - Si `solo_tras_contacto_directo` y no hay ningún intento con `contacto_directo=true` en la ventana
     semanal → no se aplica límite de frecuencia.
   - Contables = intentos con `iniciado_por=empresa` y (`contacto_directo` o
     `contar_intentos_sin_contacto`). **Nuevo campo** `contar_intentos_sin_contacto` (por defecto
     `true`, el criterio más restrictivo).
   - `FRECUENCIA_DIA` si los contables del mismo día local ≥ `max_contactos_dia`.
   - `FRECUENCIA_MEDIOS` si el número de **medios** distintos (`telefono`, `whatsapp`) entre los
     contables de la semana más el medio propuesto > `max_canales_semana`.
   - Los intentos `iniciado_por=cliente` **no consumen** cupo, pero **sí establecen** contacto directo
     si `entrantes.establecen_contacto_directo` (por defecto `true`).
3. **Contactos iniciados por el cliente** (mensaje o llamada entrante de WhatsApp; supuesto **S-E1**,
   a validar por el área legal): responder a una solicitud del consumidor **no** es una práctica de
   cobranza/comercial iniciada por la empresa. Por defecto:
   - se puede **responder** fuera de franja mientras la conversación siga abierta por iniciativa del
     cliente (`entrantes.responder_fuera_de_franja = true`);
   - las respuestas no cuentan para `max_contactos_dia` ni para medios;
   - si el área legal decide lo contrario, `responder_fuera_de_franja=false` hace que la respuesta de la
     IA o del humano se **retenga** hasta la próxima ventana (se informa al cliente con un mensaje
     automático fijo configurable), sin cambiar código.
4. **Autorización de canal (opt-in)**: tabla `autorizaciones_canal` (2B) por número E.164, `canal`
   (`whatsapp`) y finalidad (`venta`|`cobranza`|`todas`), con `origen` (`importacion`, `cliente`,
   `agente`, `agente_ia`) y `evidencia`. **Ningún contacto iniciado por la empresa por WhatsApp
   (plantilla o llamada) sin autorización vigente.** Un mensaje entrante del cliente autoriza
   *responder en esa conversación*, no enviar plantillas futuras (supuesto **S-E2**). La IA puede
   registrar la autorización explícita con una herramienta si el cliente la da en el chat.
   Las llamadas de WhatsApp requieren además el **permiso de llamada de Meta** (2E).
5. **Exclusiones por canal** (migración 0003, 2B): `exclusiones.canal` ∈ {`todos`, `voz`, `whatsapp`}
   (por defecto `todos`, así el RNE y las exclusiones existentes cubren WhatsApp); unicidad
   `(numero_e164, aplica_a, canal)`; `creado_por` pasa a nulo para altas del sistema/IA y se añade
   `origen` (`usuario`, `sistema`, `agente_ia`).
6. **Opt-out**, doble vía:
   - **Determinista** (antes de llamar a la IA): mensaje normalizado (minúsculas, sin tildes ni
     signos) igual a una frase de la lista configurable (`STOP`, `BAJA`, `NO ME ESCRIBAN`,
     `NO QUIERO MAS MENSAJES`, …) o pulsación del botón de baja de una plantilla de marketing →
     exclusión `motivo=solicitud_titular`, `canal=whatsapp`, `aplica_a=todas`, confirmación fija,
     conversación cerrada. La IA no interviene.
   - **IA**: herramienta `registrar_opt_out(alcance)` para peticiones parafraseadas ("ya no me
     contacten por aquí", "no me llamen más") con alcance `whatsapp` o `todos_los_canales`.
   - Supuesto **S-E3**: un opt-out por WhatsApp aplica a todas las finalidades (`aplica_a=todas`) en ese
     canal; "no me contacten más" → `canal=todos`.
7. **Punto de aplicación**: el cumplimiento se evalúa **en el servidor y en el momento del contacto**:
   TwiML saliente (voz y llamada WhatsApp), worker de envío de plantillas (2D) y envío de cualquier
   mensaje saliente libre (comprueba ventana de 24 h, exclusión del canal y S-E1). La UI solo muestra.
8. Cada intento guarda `politica_version` aplicada (trazabilidad ante la SIC).

## Esquema de política (extensión compatible)
```json
{
  "zona_horaria": "America/Bogota",
  "franjas": { "...": "igual que fase 1" },
  "permitir_festivos": false,
  "frecuencia": {
    "max_contactos_dia": 1, "max_canales_semana": 1, "semana": "calendario",
    "solo_tras_contacto_directo": true,
    "contar_intentos_sin_contacto": true
  },
  "entrantes": {
    "responder_fuera_de_franja": true,
    "establecen_contacto_directo": true
  }
}
```
`contar_intentos_sin_contacto` y `entrantes` tienen valores por defecto, así las versiones guardadas
en Fase 1 siguen validando sin migrar datos.

## Alternativas consideradas
- **Frecuencia por campaña**: incumple el espíritu de la ley (el límite es por consumidor).
- **Contar todas las finalidades juntas**: más restrictivo; se descartó como defecto porque la regla del
  art. 3 se refiere a gestores de cobranza, pero puede lograrse con una política de venta tan
  restrictiva como la de cobranza. Queda como pregunta legal.
- **Clasificar el opt-out solo con la IA**: no determinista e inaceptable para un derecho del titular.

## Consecuencias
- + Una sola implementación auditada para todos los canales; tests deterministas.
- + El área legal puede endurecer o relajar S-E1/S-E2 sin despliegue.
- − La evaluación de frecuencia requiere leer el historial del cliente en cada contacto (índice
  `(cliente_id, momento)`); asumible a esta escala.
