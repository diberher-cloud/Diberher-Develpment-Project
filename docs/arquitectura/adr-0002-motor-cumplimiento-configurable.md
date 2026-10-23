# ADR-0002: Motor de cumplimiento puro y políticas configurables

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
La operación en Colombia debe respetar, entre otras:
- **Ley 2300 de 2023, art. 3**: contacto solo lunes a viernes 07:00-19:00 y sábados 08:00-15:00; nunca
  domingos ni festivos. Las llamadas comerciales/publicitarias quedan sujetas a los mismos horarios.
  Una vez establecido contacto directo, no se puede contactar al consumidor por **varios canales en una
  misma semana** ni **más de una vez en el mismo día**. Excepción: el consumidor puede autorizar otros
  horarios en un instrumento distinto y posterior al contrato.
- **Festivos** de la Ley 51 de 1983 (Ley Emiliani): fijos, trasladables al lunes siguiente y móviles
  ligados a la Pascua; ocasionalmente el Gobierno decreta días extra.
- Zona horaria `America/Bogota` (UTC−5, sin horario de verano).

Las interpretaciones jurídicas cambian (conceptos de la SIC/CRC, criterio del área legal del cliente) y
el usuario pidió explícitamente **reglas como configuración, no código fijo**.

## Decisión
1. **Motor puro** en `app/modulos/cumplimiento/motor.py`: funciones sin E/S que reciben
   `(momento: datetime con zona, politica: PoliticaCumplimiento, festivos: frozenset[date], …)` y devuelven
   un `ResultadoEvaluacion(permitido, motivos, momento_local, proxima_ventana_inicio)`. Rechaza datetimes
   ingenuos (`ValueError`). Fase 1: franjas + festivos. Fase 3: frecuencia (recibe el historial de
   intentos como lista de valores) y autorizaciones de horario.
2. **Políticas versionadas** en la tabla `politicas_cumplimiento` (una activa por `tipo_campana`), con la
   configuración como JSON validado por un modelo Pydantic (`PoliticaCumplimiento`). Cambiar una política
   crea una versión nueva (trazabilidad: cada intento de contacto guardará la versión aplicada).
3. **Festivos** calculados por una función pura `festivos_colombia(anio)` (algoritmo de Pascua
   gregoriano anónimo + traslado a lunes) que **siembra** la tabla `festivos`; la tabla es la fuente de
   verdad del motor y admite festivos manuales y desactivación.
4. La verificación es **autoritativa en el servidor** en el momento de marcar (fase 2-3); la UI solo la
   muestra.
5. Valores por defecto sembrados por la migración inicial (ambos tipos):
   L-V 07:00-19:00, sáb 08:00-15:00, dom sin franjas, `permitir_festivos=false`,
   `frecuencia = {max_contactos_dia: 1, max_canales_semana: 1, semana: "calendario", solo_tras_contacto_directo: true}`.

Semántica: una franja `{inicio, fin}` permite `inicio <= hora_local < fin`. La hora de fin es la de
**inicio** de la última llamada posible; si el área legal exige que la llamada termine antes de las 19:00,
se configura `fin: "18:50"`.

## Alternativas consideradas
- **Reglas en código** (constantes): rechazado por requisito.
- **Motor de reglas genérico** (p. ej. reglas en DSL/JSONLogic): sobredimensionado; las reglas son pocas
  y bien tipadas.
- **Librería `holidays`**: válida, pero añade dependencia y no cubre días decretados ad hoc; la regla de
  Ley Emiliani cabe en ~40 líneas testeadas contra calendarios publicados. Si se prefiere, puede sustituir
  a la función pura sin cambiar la tabla.

## Consecuencias
- + Tests deterministas y rápidos sin BD ni reloj real (el momento se inyecta).
- + El área legal ajusta horarios y frecuencia sin despliegue.
- − Hay que mantener la tabla de festivos sembrada para años futuros (CLI `generar-festivos` y endpoint).
- − Una política mal configurada podría permitir contactos ilegales: solo el administrador la cambia, se
  valida estrictamente y queda auditada.
