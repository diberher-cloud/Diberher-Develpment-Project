# ADR-0023: Núcleo IA independiente del canal y turno de voz en streaming

- Estado: aceptado (implementación en subfase 2D)
- Fecha: 2026-11-18
- Concreta/modifica: ADR-0014 §1 (streaming), ADR-0020 §3, §4, §5 y §8, ADR-0022 (núcleo de 2C).
  Detalle de contrato en [`fase-2d.md`](fase-2d.md) §4-§5.

## Contexto
2C entregó un núcleo "preparado para voz", pero el backend declaró que **no es del todo independiente
del canal**: `bucle.py`, `herramientas/ejecutores.py`, `derivacion.py` y `presupuesto.py` leen y escriben
la fila `conversaciones` (`turnos_ia`, `identidad_verificada`, `identidad_intentos`,
`aviso_ia_enviado_en`, `costo_usd_acumulado`, `intento_contacto_id`, `iniciada_por`), filtran
`acciones_ia`/`instrucciones_supervisor`/`tipificaciones` por `conversacion_id`, llaman a
`configuracion.ia_disponible` (que exige WhatsApp habilitado) y registran auditoría con entidad
`conversacion`. Además, el turno de chat envía el texto **al final**; en voz se habla mientras se
genera. Al detallar el turno de voz aparecieron también:
1. Con `eager_input_streaming: true` (ADR-0020 §3) la API **deja de validar** la entrada de las
   herramientas (documentación del SDK, `streaming.md`): se pierde la garantía de `strict: true`.
2. Si la guarda de montos bloquea una frase a mitad de respuesta, cancelar el stream deja al historial
   sin el turno `assistant` aunque el cliente ya oyó frases anteriores.
3. El documento marcado por DTMF debía llegar al modelo para que llamara a `verificar_identidad`:
   dígitos completos en `historial_ia` y en la petición a Anthropic sin necesidad.
4. S-V3 (el cliente acepta "tras una repetición explícita de las condiciones") no era verificable por
   el servidor.

## Decisión
1. **Estado de interacción común.** `llamadas_ia` usa **los mismos nombres de columna** que
   `conversaciones` para el estado de IA (`identidad_verificada`, `identidad_intentos`, `turnos_ia`,
   `costo_usd_acumulado`, `aviso_ia_enviado_en`, `modelo_ia`, `esfuerzo_ia`, `prompt_version`,
   `iniciada_por`) y expone `intento_contacto_id` como propiedad de la llamada. Un módulo nuevo
   `agente_ia/interaccion.py` concentra lo que dependía de la conversación: `fila_estado(db, ref)`,
   `filtro(Modelo, ref)`, `gestion(db, ref)`, `ref_columnas(ref)` y `entidad_auditoria(ref)`. El
   núcleo deja de importar `Conversacion` (test de importaciones).
2. **Disponibilidad por canal**: `configuracion.disponible(db, ctx)` → `ia_disponible` (chat, sin
   cambios) o `voz_disponible` (`IA_HABILITADA` ∧ global ∧ campaña activa ∧ `voz_modo='ia'` ∧
   `voz_activa`). El protocolo `CanalIA` gana `avisar_derivacion` (el mensaje de traspaso/espera de
   WhatsApp sale de `derivacion.py` y pasa a `CanalChat`).
3. **Pasos de turno compartidos**: las transacciones de `bucle.py` se extraen a `nucleo_turno.py`
   (preparar, comprobar antes de cada llamada, registrar respuesta, ejecutar herramientas, cerrar) sin
   cambio funcional en chat; `voz_ia/bucle_voz.py` (asíncrono) los invoca en hilos.
4. **Sin `eager_input_streaming`** en voz: las herramientas de voz mantienen `strict: true` (validación
   en la API) además de la validación Pydantic del servidor. La latencia de herramientas se cubre con
   la frase de relleno. Se reconsidera solo si V6 muestra que la entrada de herramientas domina la
   latencia.
5. **Guarda por frase y lectura completa del stream**: cada frase se guarda antes de hablarse; si una
   falla, **se deja de hablar** pero se sigue leyendo el stream hasta el final (≤ `IA_VOZ_MAX_TOKENS`),
   se añade el `assistant` completo al historial y después un `user` de control con lo efectivamente
   dicho (`<control_servidor tipo="respuesta_bloqueada" dicho="…"/>`) y el `system` de corrección
   (mismo esquema que ADR-0022). Solo una **interrupción del cliente** descarta el turno en generación.
6. **DTMF de identidad resuelto por el servidor**: una secuencia de 5-15 dígitos terminada en `#` (o
   pausa) con la identidad sin verificar ejecuta `verificar_identidad` en el servidor (acción
   registrada con `tool_use_id` sintético `srv_dtmf_<llamada>_<n>`); el modelo recibe solo
   `<dtmf tipo="documento" resultado="…"/>`. Los dígitos no llegan al modelo ni a `historial_ia`; en
   `transcripciones_llamada` quedan enmascarados. DTMF `0` aislado = petición de asesor.
7. **Repetición de condiciones verificable** (S-V3): en voz, `registrar_acuerdo_pago`/`registrar_venta`
   exigen además un segmento hablado por la IA, posterior a la simulación/cotización y anterior a la
   cita, que contenga el monto total (o valor total) respaldado → si no, `CONDICIONES_NO_REPETIDAS`.
8. **Catálogo de voz** por tipo de campaña (voz-cobranza, voz-venta) con los mismos nombres y
   ejecutores que chat y descripciones orales; `registrar_opt_out.alcance` ∈ {`llamadas`,
   `todos_los_canales`}. No se crea el alias `transferir_a_humano` (ADR-0020 §3): `derivar_a_humano`
   basta y evita una rama en los ejecutores.

## Alternativas consideradas
- **Tabla genérica `interacciones_ia`** con el estado de IA de chat y voz: migraría datos de 2C y
  añadiría un JOIN en cada turno. Rechazada; nombres de columna comunes + `interaccion.py` bastan.
- **Duplicar el bucle para voz**: dos implementaciones de las mismas reglas transaccionales. Rechazada.
- **Cancelar el stream al fallar una guarda**: historial sin el turno `assistant` y el modelo ignora lo
  que ya dijo. Rechazada.
- **Enviar los dígitos DTMF al modelo**: más datos personales a un tercero sin beneficio. Rechazada.
- **Mantener `eager_input_streaming`**: menor latencia de entrada de herramientas, pero entradas sin
  validar por la API. Rechazada por defecto.

## Consecuencias
- + Un solo núcleo para chat y voz, comprobado por tests (chat de 2C intacto, `CanalFalso` y
  `CanalVoz`).
- + Menos datos personales hacia Anthropic (DTMF) y verificación de S-V3 en servidor.
- − Refactor acotado de 2C (extracción a `nucleo_turno.py`, `interaccion.py`) con regresión completa.
- − Tokens adicionales cuando una guarda bloquea a mitad de respuesta (se lee el resto del stream).
- − La primera audición espera a la primera frase completa (no token a token).
