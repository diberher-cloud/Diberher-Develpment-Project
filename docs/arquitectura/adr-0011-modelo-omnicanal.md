# ADR-0011: Modelo de datos omnicanal (intentos de contacto, gestiones y conversaciones)

- Estado: aceptado (2A: intentos y gestiones; 2B: conversaciones y mensajes)
- Fecha: 2026-10-23

## Contexto
La plataforma pasa de un canal (voz PSTN) a cuatro formas de contacto: llamada PSTN, mensaje de
WhatsApp, llamada de WhatsApp y chat atendido por IA. Necesitamos:
- un **historial común** que alimente las reglas de frecuencia de la Ley 2300 *entre canales y entre
  campañas* (por consumidor);
- un **resultado de gestión** común (tipificación, promesa de pago, venta) sin importar si lo registró un
  agente humano por voz o el agente IA por chat;
- un modelo de **conversación** para canales asíncronos (WhatsApp), con su ventana de 24 h, que pueda
  pasar de IA a humano y viceversa.

## Decisión
1. **Canal** como catálogo cerrado en todo el modelo: `voz` (PSTN), `whatsapp_mensaje`,
   `whatsapp_llamada`. Para las reglas de frecuencia se agrupan en **medios**: `telefono` = {`voz`},
   `whatsapp` = {`whatsapp_mensaje`, `whatsapp_llamada`} (ADR-0012).
2. **`intentos_contacto`** (2A) es la fuente de verdad de la frecuencia: una fila por cada contacto
   **iniciado por la empresa** (llamada marcada, plantilla enviada) y por cada conversación/llamada
   **iniciada por el cliente**, con `canal`, `iniciado_por` (`empresa`|`cliente`), `momento`,
   `contacto_directo` (se actualiza al tipificar o cuando el cliente responde), `cliente_id` (global),
   `campana_id` y `tipo_campana` (desnormalizado para consultar por finalidad sin joins).
3. **`tipificaciones`** (2A) es el resultado de una gestión, canal-agnóstico: `resultado` (catálogo
   único para humanos e IA), `canal`, `origen` (`agente`|`agente_ia`|`sistema`), `usuario_id` (nulo para
   IA/sistema), referencia opcional a `llamadas` o (desde 2B) a `conversaciones`. Las tablas
   **`promesas_pago`** y **`ventas`** cuelgan de una tipificación (1:1). La IA usa exactamente las
   mismas tablas y las mismas validaciones de servicio que el agente humano (más los límites de
   negocio por campaña de ADR-0015, que también aplican al humano desde 2C).
4. **`llamadas`** (2A) representa una llamada de voz (PSTN o, desde 2E, WhatsApp) con su `canal` y
   `direccion`; los eventos del proveedor van a `eventos_llamada` (idempotentes).
5. **`conversaciones`** + **`mensajes`** (2B) para WhatsApp:
   - Una conversación agrupa los mensajes entre un número de cliente y el número de la empresa mientras
     esté **abierta**. Se cierra por inactividad (configurable, por defecto al vencer la ventana de
     24 h sin actividad), por opt-out o manualmente. Un nuevo mensaje tras el cierre abre otra.
   - Como mucho una abierta por par de números: columna `clave_abierta` = `"<cliente>|<empresa>"`
     mientras está abierta y `NULL` al cerrar, con `UNIQUE(clave_abierta)` (portable SQLite/PostgreSQL,
     sin índices parciales).
   - El **backend fija** `cliente_id`, `campana_cliente_id` y `campana_id` de la conversación al
     abrirla (resolución determinista, `fase-2.md` §7.1); nunca los decide el modelo de IA.
   - `atendida_por` ∈ {`ia`, `humano`, `sin_asignar`} y `usuario_asignado_id` modelan el traspaso
     (ADR-0016). `ventana_expira_en` = último mensaje entrante + 24 h.
   - `mensajes` guarda cada mensaje (entrante/saliente, autor `cliente`|`ia`|`agente`|`sistema`,
     tipo, estado de entrega, id del proveedor único para idempotencia).
6. El historial **técnico** del agente IA (bloques exactos enviados/recibidos de la API de Claude) se
   guarda aparte en `historial_ia` (ADR-0014): `mensajes` es lo que vio el cliente; `historial_ia` es lo
   que vio el modelo.

## Alternativas consideradas
- **Tablas por canal** (`llamadas_voz`, `mensajes_whatsapp`, sin historial común): la frecuencia
  exigiría uniones entre tablas heterogéneas en cada evaluación; rechazado.
- **Un único "evento de contacto" genérico con JSON**: flexible pero sin integridad referencial ni
  consultas tipadas; rechazado.
- **Conversación eterna por cliente** (un hilo por número para siempre): simplifica la UI pero hace
  crecer sin límite el contexto del modelo y el coste; se prefiere cerrar y abrir conversaciones,
  dando a la IA el historial previo por herramienta (`consultar_historial_gestiones`).

## Consecuencias
- + Las reglas de frecuencia, los reportes y la supervisión ven un único historial.
- + Humano e IA comparten resultados y validaciones: lo que la IA no puede hacer tampoco lo puede hacer
  un humano fuera de los límites, y viceversa.
- − `intentos_contacto` se escribe en varios puntos (TwiML saliente, envío de plantilla, mensaje
  entrante, llamada entrante); se centraliza en `cumplimiento.servicio.registrar_intento()`.
