# ADR-0024: Marcador IA en un hilo del worker con cerrojo arrendado; traspasos y devoluciones de voz

- Estado: aceptado (implementación en subfase 2D)
- Fecha: 2026-11-18
- Modifica: ADR-0021 §3 (dónde corre el tick y cómo se serializa) y §4.5 (errores de creación).
  Concreta: ADR-0016 §8, ADR-0020 §6 y §9. Detalle en [`fase-2d.md`](fase-2d.md) §6-§7.

## Contexto
ADR-0021 preveía el tick del marcador como trabajo periódico de la cola `trabajos` cada 2 s, serializado
con `FOR UPDATE NOWAIT` sobre la fila `configuracion_global('marcador_ia')`. Al bajarlo a contrato:
1. El worker ejecuta los trabajos de un lote **en serie**: un turno de chat (hasta
   `IA_TURNO_MAX_SEGUNDOS` = 240 s) retrasaría el tick; y un trabajo cada 2 s son ~43 000 filas diarias
   en `trabajos`.
2. Mantener el `FOR UPDATE` durante todo el tick obliga a tener una transacción abierta mientras se
   llama a la API REST de Twilio; `NOWAIT` no existe en SQLite (tests).
3. Un error "definitivo" al crear la llamada se resolvía borrando el intento de contacto y liberando la
   reserva **sin** contar intento: un número que Twilio rechaza siempre se reintentaría sin fin.
4. Un error "incierto" (Twilio pudo haber marcado) se cerraba como `fallida`, pero sin decir si el
   intento cuenta para la frecuencia.
5. Faltaba el contrato de la devolución de llamada frente a la frecuencia (S-V6) y el comportamiento
   de las entrantes sin un registro único (S-V9).

## Decisión
1. **Hilo del marcador en el worker** (`marcador/hilo.py`, activado con `MARCADOR_IA_HABILITADO`): cada
   `MARCADOR_IA_INTERVALO_SEGUNDOS` ejecuta `marcador.tick` fuera de la cola `trabajos`. Así no compite
   con los turnos de chat ni llena la cola. Los tests llaman a `tick()` directamente con reloj fijo.
2. **Cerrojo arrendado** en una tabla nueva `cerrojos_sistema(clave, trabajador, adquirido_en,
   expira_en)`, mismo patrón que `bloqueos_turno_ia` (INSERT en SAVEPOINT o UPDATE condicional si
   caducó), clave `marcador_ia`, duración `MARCADOR_IA_CERROJO_SEGUNDOS` (30), renovado antes de cada
   creación de llamada. Si se pierde, el tick se detiene. Portátil a SQLite, sin transacción abierta
   durante la llamada REST y con recuperación por caducidad tras una caída. (La fila
   `configuracion_global('marcador_ia')` de `fase-2.md` §7.3 no se crea.)
3. **Anti-duplicado independiente del cerrojo**: aunque dos ticks coincidieran (cerrojo caducado), cada
   candidato se reserva con `clientes FOR UPDATE SKIP LOCKED` + UPDATE condicional del registro + "sin
   llamada activa del mismo cliente en ninguna campaña", en una transacción corta.
4. **Errores de creación**:
   - *Cierto, no reintentable* (4xx de Twilio salvo 429): la llamada queda `fallida`, se **borra** el
     intento de contacto (no hubo contacto) y se tipifica `no_contesta` (`origen=sistema`, observación
     `error_creacion:<codigo>`), que **suma `intentos`**: el número se reintenta como mucho
     `max_intentos` veces.
   - *Cierto, transitorio* (429, conexión rechazada antes de enviar): la llamada queda `bloqueada`
     (`ERROR_PROVEEDOR_TRANSITORIO`), se borra el intento, se libera la reserva sin sumar intentos y el
     tick deja de marcar durante 10 s.
   - *Incierto* (tiempo de espera o corte después de enviar): la llamada queda `iniciando`; los webhooks
     (que llevan `llamada_id`) la reconcilian. Si a los `MARCADOR_IA_INCIERTA_MINUTOS` (2) sigue con
     `CallSid` provisional, pasa a `fallida` **conservando** el intento de contacto (criterio
     conservador para la frecuencia: pudo haber timbrado) y se tipifica `no_contesta`
     (`creacion_incierta`).
5. **Traspasos de voz** en `traspasos_llamada` con asignación `estados_agente FOR UPDATE SKIP LOCKED` →
   `clientes` → `campana_clientes` → `llamadas` → `llamadas_ia` → `traspasos_llamada`; el agente pasa a
   `en_llamada` mientras timbra; si no contesta (20 s) o rechaza, vuelve a `disponible` y no se le
   vuelve a ofrecer ese traspaso. La conexión real se confirma con el `statusCallback` de `<Client>`.
6. **Devolución de llamada**: el registro queda `requiere_humano=true` con tipificación
   `volver_a_llamar` (`origen=sistema`) en la próxima ventana del horario de humanos, excluido del
   marcador y visible en la consola. La llamada del humano que la atiende se registra con
   `intentos_contacto.es_devolucion=true` y, si la política tiene
   `entrantes.devolucion_cuenta_frecuencia=false` (por defecto), se evalúa **solo por horario** y no
   consume cupo de frecuencia (S-V6).
7. **Entrantes PSTN**: resolución determinista como en 2B (teléfono → registros de campañas activas; si
   hubo una llamada saliente a ese número en 30 días, su registro; si queda uno, ese). Registro único
   de una campaña con voz IA disponible → IA. Registro único sin IA, o varios candidatos (se elige el de
   gestión más reciente) → traspaso directo a humanos (`entrante`/`entrante_ambigua`), nunca IA (S-V9).
   Sin candidatos → mensaje fijo y fin (no se crea fila en `llamadas`, que exige registro).

## Alternativas consideradas
- **Mantener el tick en la cola `trabajos`** con un worker dedicado por tipo: exige filtrar tipos en
  `cola.tomar` y otra réplica del worker; sigue generando filas. Rechazada.
- **`pg_try_advisory_lock`**: ligado a la conexión (el pool la devuelve entre transacciones) y no
  portable a SQLite. Rechazada (misma razón que ADR-0022).
- **No contar intentos en errores definitivos**: bucle infinito con números inválidos. Rechazada.
- **Borrar el intento también en errores inciertos**: podría subestimar la frecuencia real si Twilio sí
  marcó. Rechazada.
- **`<Enqueue>`/TaskRouter para la espera**: posición en cola y prioridades, pero añade otro producto de
  Twilio y su configuración; la espera es corta (≤ 120 s). Pospuesta (ADR-0016).

## Consecuencias
- + El ritmo del marcador no depende de la carga de chat; la cola `trabajos` no crece por el marcador.
- + Ni varias réplicas del worker ni un cerrojo caducado producen llamadas duplicadas.
- + Los números rechazados por el proveedor agotan sus intentos; los inciertos cuentan para la
  frecuencia.
- − Un hilo más en el proceso del worker (se detiene con la misma señal) y una tabla nueva.
- − La política de cumplimiento gana un campo (`entrantes.devolucion_cuenta_frecuencia`) y el motor un
  modo "solo horario" para devoluciones.
