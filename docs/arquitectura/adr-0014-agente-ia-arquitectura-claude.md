# ADR-0014: Arquitectura del agente IA de WhatsApp con la API de Claude

- Estado: aceptado (implementación en subfase 2C)
- Fecha: 2026-10-23

## Contexto
Los chats de WhatsApp los atienden agentes cognitivos con **autonomía total** (negocian acuerdos de
pago y cierran ventas). Modelo: Claude por la API de Anthropic con el SDK oficial de Python
`anthropic`. Requisitos: control total de auditoría y límites, costes acotados, tests sin llamar a la
API real, coherencia con el resto del backend (SQLAlchemy síncrono, worker con cola en PostgreSQL).

Datos de la API usados en este diseño (verificados por el usuario, no sustituir por recuerdos):
- Modelo por defecto `claude-opus-5-5` ($4/$20 por MTok entrada/salida); alternativas
  `claude-sonnet-5-5` ($2/$10) y `claude-haiku-5-5` ($0,10/$0,50). El modelo es **configuración**.
- En Opus 5.5 el *thinking* no se puede desactivar; se controla con `output_config.effort`
  (`low|medium|high|xhigh|max`, por defecto `medium`).
- `tool_choice` forzado (`any`/`tool`) → 400 en Opus 5.5 y Sonnet 5.5: se usa `auto` + `strict: true`
  + instrucciones en el prompt.
- Sin *prefill* del turno del asistente; sin `temperature`/`top_p`/`top_k` (400).
- Mensajes `{"role": "system"}` a mitad de conversación soportados en Opus 5.5/Sonnet 5.5.
- Hay que comprobar siempre `stop_reason` (`end_turn`, `tool_use`, `max_tokens`, `refusal` con
  `stop_details.category`). Fallback de rechazo del lado del servidor:
  `betas=["server-side-fallback-2026-07-01"]` + `fallbacks="default"`.
- Bloques de *thinking*: se devuelve `response.content` completo al historial (append-only).
- Errores del SDK por tipo (`RateLimitError`, `APIStatusError`, `APIConnectionError`…), 2 reintentos
  por defecto.

## Decisión

### 1. Puerto del modelo
`app/modulos/agente_ia/llm.py`:
```python
@dataclass(frozen=True)
class RespuestaLLM:
    id: str
    modelo: str
    stop_reason: str                    # end_turn | tool_use | max_tokens | refusal | pause_turn
    stop_categoria: str | None          # stop_details.category si refusal
    contenido: list[dict[str, Any]]     # bloques tal cual (block.to_dict()), se guardan y reenvían
    uso: dict[str, int]                 # input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
    request_id: str | None

class ClienteLLM(Protocol):
    def crear_mensaje(self, *, modelo: str, max_tokens: int, esfuerzo: str,
                      sistema: list[dict], herramientas: list[dict],
                      mensajes: list[dict], fallback_rechazo: bool) -> RespuestaLLM: ...
```
- `ClienteAnthropic`: `anthropic.Anthropic(max_retries=2, timeout=anthropic.Timeout(60.0, connect=5.0))`.
  Llama `client.messages.create(...)` (o `client.beta.messages.create(..., betas=[
  "server-side-fallback-2026-07-01"], fallbacks="default")` si `fallback_rechazo`), con
  `output_config={"effort": esfuerzo}`, `cache_control={"type": "ephemeral"}` (caché automática de la
  cola) y **sin** `temperature`, `top_p`, `top_k`, `thinking`, `tool_choice` (por defecto `auto`).
  Traduce excepciones del SDK a `ErrorLLM(transitorio: bool, codigo)`: `RateLimitError`,
  `APIConnectionError`, `APITimeoutError`, `InternalServerError` → transitorio (el trabajo se
  reintenta por la cola, ADR-0013); `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`,
  `NotFoundError` → no transitorio (deriva a humano + alerta).
- `ClienteLLMFalso`: guion determinista de respuestas (lista o función de los mensajes recibidos) que
  emite bloques `text`/`tool_use`/`thinking` y `usage` sintético; registra cada petición para
  aserciones (incluida la comprobación de que `system` y `tools` son byte a byte estables).
- Selección por `IA_PROVEEDOR=anthropic|falso` (por defecto `falso` en `desarrollo`/`test`).

### 2. Bucle agéntico manual
Se usa el **bucle manual** (`while stop_reason == "tool_use"`) y no el Tool Runner (beta) porque:
cada ejecución de herramienta debe persistirse en la **misma transacción** que su `tool_result` y su
auditoría; necesitamos comprobar presupuesto, kill switch e instrucciones del supervisor entre
iteraciones; y el turno se ejecuta en el worker con reintentos idempotentes por `tool_use_id`.

`ejecutar_turno(db, conversacion_id)` (trabajo `ia.turno`):
```
bloquear conversación (FOR UPDATE en PG) ; si atendida_por != 'ia' o IA desactivada → salir
nuevos = mensajes entrantes no procesados ; si vacío → salir
guardas deterministas de entrada (opt-out, petición literal de humano, media) → actuar y salir
comprobar presupuesto (campaña y conversación) → si excede: derivar y salir
añadir a historial_ia: user = [<mensaje_cliente> por cada mensaje nuevo]
añadir system messages pendientes (contexto inicial, cambio de fecha local, instrucción de supervisor, identidad verificada)
for i in 1..IA_MAX_ITERACIONES (def. 8):
    r = llm.crear_mensaje(...) ; registrar uso_ia
    añadir a historial_ia: assistant = r.contenido      # completo, con thinking
    switch r.stop_reason:
      tool_use  → ejecutar TODAS las tool_use (en orden), cada una idempotente por tool_use_id;
                  añadir UN user con todos los tool_result (is_error=true en rechazos); continue
      end_turn  → texto = concatenar bloques text ; guardas de salida ; enviar ; break
      max_tokens→ derivar(motivo='ia_max_tokens') ; break
      refusal   → registrar stop_categoria ; derivar(motivo='ia_rechazo') ; break
      otro      → derivar(motivo='ia_stop_inesperado') ; break
si se agotan las iteraciones → derivar(motivo='ia_iteraciones')
```
- `max_tokens` por llamada: `IA_MAX_TOKENS` (por defecto 8 000; incluye *thinking*).
- Si el modelo termina con `end_turn` sin texto, no se envía nada (se registra); si una herramienta
  derivó o cerró la conversación, el texto final (despedida) sí se envía.

### 3. Prompt y caché
- **Orden estable**: `tools` (ordenadas por nombre, serializadas de forma determinista) → `system`
  (texto fijo versionado en `app/modulos/agente_ia/prompts/sistema_v<N>.md`, con
  `cache_control: {"type": "ephemeral"}` en el último bloque) → `messages`.
- El `system` **no contiene** fechas, nombres, ids, datos de campaña ni del cliente. El nombre de la
  empresa (`EMPRESA_NOMBRE`) es constante por despliegue y puede ir en el system.
- Datos variables van **después** del prefijo cacheado:
  - contexto de campaña (tipo, instrucciones del supervisor para la campaña, texto de la plantilla que
    inició la conversación, nombre de pila del cliente, fecha local) como mensaje
    `{"role": "system"}` inmediatamente después del **primer** mensaje `user`;
  - un nuevo `system` cuando cambia la fecha local o el supervisor da una instrucción (ADR-0016);
  - saldos, ofertas y condiciones **solo** mediante herramientas tras verificar identidad.
- Caché automática de la cola (`cache_control` de nivel superior, TTL 5 min; `IA_CACHE_TTL=1h`
  configurable para tráfico con pausas largas). Se registra `cache_read_input_tokens` y un test con el
  cliente falso verifica que dos turnos consecutivos envían un prefijo idéntico.
- El modelo, el esfuerzo y la versión del prompt se **fijan al abrir la conversación**
  (`conversaciones.modelo_ia`, `esfuerzo_ia`, `prompt_version`) y no cambian dentro de ella (la caché es
  por modelo y los bloques de *thinking* dependen del modelo).

### 4. Formato de los mensajes del cliente (datos no confiables)
Cada mensaje entrante va como bloque de texto:
`<mensaje_cliente fecha_local="2026-10-23T10:15">…texto escapado…</mensaje_cliente>`, escapando `<`,
`>` y `&` del texto del cliente para que no pueda cerrar la etiqueta. Media no soportada se representa
como `<mensaje_cliente tipo="audio" soportado="false"/>`.

### 5. Persistencia
- `historial_ia(conversacion_id, secuencia, rol, contenido JSON, creado_en)`, único por
  `(conversacion_id, secuencia)`, **append-only** (nunca se editan turnos previos). Se reconstruye
  `messages` en orden. Contiene datos personales: mismo control de acceso y retención que las
  transcripciones (ADR-0015 §8).
- `acciones_ia(conversacion_id, tool_use_id UNIQUE, herramienta, entrada JSON enmascarada, resultado
  JSON enmascarado, es_error, codigo_error, duracion_ms, creado_en)`: auditoría de cada herramienta e
  idempotencia (si el trabajo se reintenta tras una caída, una herramienta ya ejecutada devuelve el
  resultado guardado).
- `uso_ia(conversacion_id, campana_id, modelo, request_id, stop_reason, input_tokens, output_tokens,
  cache_creation_input_tokens, cache_read_input_tokens, costo_usd NUMERIC(12,6), duracion_ms,
  creado_en)`.

### 6. Costes
- Precios por modelo en configuración (`IA_PRECIOS_JSON`, por defecto los de arriba; lectura de caché
  0,05× y escritura 1,25× para Opus 5.5 según la documentación del SDK) → `costes.py` (puro) calcula
  `costo_usd` por llamada.
- Presupuestos: `configuracion_ia_campana.presupuesto_usd` (mensual) y
  `max_costo_conversacion_usd` / `max_turnos_conversacion`. Se comprueban **antes** de cada llamada;
  al excederse la campaña, la IA de esa campaña se desactiva automáticamente (kill switch, ADR-0016) y
  se alerta; al excederse la conversación, se deriva a humano.

## Alternativas consideradas
- **Tool Runner del SDK (beta)**: menos código, pero el control de transacciones por herramienta, la
  idempotencia por `tool_use_id` y las comprobaciones entre iteraciones quedan fuera de nuestro bucle.
- **SDK asíncrono**: el backend es síncrono (ADR-0006) y el turno corre en el worker; no aporta.
- **Streaming**: el cliente de WhatsApp recibe mensajes completos; no hay beneficio de latencia.
- **Datos del cliente en el system prompt**: rompe la caché y expone datos antes de verificar
  identidad; rechazado.
- **Un modelo por turno (enrutar a Haiku los turnos simples)**: invalida la caché y los *thinking*;
  si se quiere abaratar, se cambia el modelo **por campaña**.

## Consecuencias
- + Todo el comportamiento del agente es testeable sin red con `ClienteLLMFalso`.
- + Coste observable por llamada, conversación y campaña.
- − Latencia por turno de varios segundos (Opus + *thinking* + herramientas); aceptable en chat.
- − Los datos de la conversación salen a un proveedor en el extranjero (transmisión internacional,
  Ley 1581): requisito contractual y de aviso de privacidad (fase-2.md §8).
