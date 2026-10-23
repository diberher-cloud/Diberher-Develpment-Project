# ADR-0009: Marcador preview y progresivo con cola en PostgreSQL

- Estado: aceptado (implementación en fase 3)
- Fecha: 2026-10-23

## Contexto
Se pide marcador automático con modos preview y progresivo, reintentos configurables y respeto de
franjas y frecuencia. El modo predictivo marca más llamadas que agentes libres; genera llamadas
abandonadas (cliente contesta y no hay agente), lo que en Colombia aumenta el riesgo de quejas ante la SIC
y cuenta como contacto frente a la Ley 2300.

## Decisión
- **Preview**: el sistema reserva el siguiente registro elegible para el agente y muestra la ficha; el
  agente pulsa *Llamar* (flujo de ADR-0003).
- **Progresivo 1:1**: un worker toma, por cada agente `disponible` en una campaña progresiva, un registro
  elegible y crea la llamada (Twilio AMD). Nunca hay más llamadas en curso que agentes reservados → sin
  abandono por diseño.
- **Cola**: tabla `cola_marcacion` (campana_cliente_id, telefono_id, disponible_desde, prioridad,
  reservado_por, reservado_hasta). Toma con `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1`; reserva con
  caducidad para liberar registros si el worker cae.
- **Elegibilidad** (todas en servidor, en el momento de marcar): campaña activa, registro pendiente,
  `intentos < max_intentos`, `proximo_intento_en <= ahora`, franja y festivo (ADR-0002), exclusiones,
  frecuencia del cliente entre campañas.
- **Reintentos**: por resultado (`no_contesta`, `ocupado`, `buzon`, `fallida`) con intervalo de la campaña;
  si el próximo intento cae fuera de franja se mueve a `proxima_ventana_inicio`.
- **Predictivo**: pospuesto a fase 5, con tope de abandono configurable y conferencias.

## Alternativas consideradas
- **Predictivo desde el MVP**: mayor productividad, pero riesgo regulatorio y algoritmo complejo.
- **Cola en Redis**: innecesaria a esta escala (ADR-0001).

## Consecuencias
- + Cumplimiento verificable y sin abandono.
- − Menor productividad que el predictivo (más tiempo de espera del agente).
