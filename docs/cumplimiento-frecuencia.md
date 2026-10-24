# Horario y frecuencia de contacto: qué modela la plataforma

> **Documento para el área jurídica.** Describe cómo la plataforma aplica el horario, los festivos y la
> frecuencia de contacto (Ley 2300 de 2023) en las llamadas de la consola. No es asesoría legal ni
> interpretación oficial. **Las normas se contrastaron solo con búsquedas web. Ningún abogado las ha revisado.**
> Todas las reglas están en la configuración de la política, así que el área puede cambiarlas sin desplegar código.
> Las preguntas abiertas están en la sección 10.

Referencias técnicas: [ADR-0002](arquitectura/adr-0002-motor-cumplimiento-configurable.md) (motor configurable),
[ADR-0012](arquitectura/adr-0012-cumplimiento-omnicanal.md) (frecuencia y canales),
[`fase-2.md`](arquitectura/fase-2.md) §4.8 y §8. Uso operativo: [`consola-agente.md`](consola-agente.md).

Índice: [1. Resumen](#1-resumen) · [2. Normas modeladas](#2-normas-modeladas) ·
[3. Configuración de la política](#3-configuración-de-la-política) · [4. Horario y festivos](#4-horario-y-festivos) ·
[5. Cómo se cuentan los contactos](#5-cómo-se-cuentan-los-contactos) · [6. Cuándo se comprueba](#6-cuándo-se-comprueba) ·
[7. Trazabilidad](#7-trazabilidad) · [8. Exclusiones](#8-exclusiones-rne-y-números-erróneos) ·
[9. Límites de 2A](#9-qué-no-hace-la-plataforma-en-2a) · [10. Supuestos y preguntas abiertas](#10-supuestos-y-preguntas-abiertas)

---

## 1. Resumen

- En cada llamada, el **servidor** comprueba el horario, los festivos y la frecuencia **en el momento de marcar**.
  La interfaz solo muestra el resultado.
- Una llamada que incumple una regla **no se marca**. Queda registrada como bloqueada, con el motivo.
- La frecuencia se cuenta **por cliente** (documento) y **por tipo de campaña** (venta o cobranza).
- Los valores por defecto aplican el criterio más restrictivo de la lectura adoptada (ver sección 10).
- Cada intento guarda la versión de la política aplicada, para poder demostrar qué regla estaba vigente.

---

## 2. Normas modeladas

| Norma | Qué modela la plataforma | Estado |
|---|---|---|
| **Ley 2300 de 2023, art. 3** (lectura adoptada en ADR-0012) | Franjas de contacto de lunes a viernes de 07:00 a 19:00 y sábados de 08:00 a 15:00. No hay contacto en domingos ni festivos. Tras un contacto directo, no más de un contacto el mismo día ni por varios medios en la misma semana. | Modelada como configuración. La lectura **no está validada**. |
| **Ley 2300 de 2023, art. 2** | Solo se contacta por los canales que el consumidor autorice. | En 2A solo hay llamadas de voz. La autorización de canal (opt-in) llega con WhatsApp (2B). |
| **Parágrafo del art. 3** (lectura adoptada en ADR-0012) | Extiende las franjas a otros medios (mensajería por aplicaciones, correo, SMS y llamadas comerciales). | Se aplica a WhatsApp desde 2B. **Lectura pendiente.** |
| **Ley 51 de 1983** (festivos colombianos) | Calcula los festivos (fijos, trasladables al lunes y basados en Pascua) y los guarda en una tabla editable. | Implementado. Ver sección 3.3. |
| **Registro de Números Excluidos (RNE, CRC)** | Excluye los números inscritos. Las exclusiones se cargan desde un archivo. | Carga manual en 2A. No consulta el webservice. |
| **Ley 1581 de 2012** (Habeas Data) | Aviso de grabación al cliente antes de unir al agente. | El aviso existe. **Su texto debe aprobarlo el área jurídica.** |

**Cómo se contrastaron las normas.** Solo con búsquedas web. No se ha consultado el texto oficial publicado ni
existe revisión jurídica. Hasta que el área jurídica del cliente las confirme, deben tratarse como configurables.

---

## 3. Configuración de la política

Hay **una política activa por tipo de campaña** (`venta` o `cobranza`). Cada cambio crea una **versión nueva**
y desactiva la anterior. Solo el administrador la modifica (`PUT /api/v1/cumplimiento/politicas/{tipo}`). Las
políticas guardadas antes de la subfase 2A siguen siendo válidas: los campos nuevos toman sus valores por defecto.

### 3.1 Campos de la política

| Campo | Tipo y restricciones | Por defecto | Significado |
|---|---|---|---|
| `zona_horaria` | Zona IANA válida | `America/Bogota` | Zona en la que se interpretan las franjas y los días. |
| `franjas.<día>` | Lista de `{inicio, fin}` en `HH:MM` (24 h) | L–V `07:00–19:00`; S `08:00–15:00`; D sin franjas | Horas permitidas. `inicio` es inclusivo y `fin` exclusivo. En cada día, las franjas van ordenadas y no se solapan. |
| `permitir_festivos` | Booleano | `false` | Si es `true`, los festivos no bloquean el contacto. Los días sin franja siguen bloqueando. |
| `frecuencia.max_contactos_dia` | Entero 1–10 | `1` | Máximo de contactos contables en el mismo día local. |
| `frecuencia.max_canales_semana` | Entero 1–10 | `1` | Máximo de medios distintos contables en la semana. |
| `frecuencia.semana` | `calendario` o `movil_7_dias` | `calendario` | Ventana semanal (sección 5.4). |
| `frecuencia.solo_tras_contacto_directo` | Booleano | `true` | Si es `true`, la frecuencia solo se limita tras un contacto directo en la ventana. |
| `frecuencia.contar_intentos_sin_contacto` | Booleano | `true` | Si es `true`, los intentos sin contacto directo también cuentan. |
| `entrantes.responder_fuera_de_franja` | Booleano | `true` | Permite responder a un contacto iniciado por el cliente fuera de franja. Sin uso en 2A. |
| `entrantes.establecen_contacto_directo` | Booleano | `true` | Un contacto iniciado por el cliente cuenta como contacto directo. Sin uso en 2A. |

Ningún campo admite claves adicionales (`extra="forbid"`). El valor por defecto completo es el de la
función `politica_por_defecto()` (`backend/app/modulos/cumplimiento/politica.py`).

### 3.2 Consultar y cambiar

- `GET /api/v1/cumplimiento/politicas`: la política activa de cada tipo.
- `GET /api/v1/cumplimiento/politicas/{tipo}/versiones`: historial de versiones (administrador y supervisor).
- `PUT /api/v1/cumplimiento/politicas/{tipo}`: crea una nueva versión (administrador). Responde `201`. Se audita como `politica.actualizar`.
- `POST /api/v1/cumplimiento/evaluar`: evalúa un momento sin llamar. Con `cliente_id` (administrador y supervisor)
  incluye la frecuencia; sin él, solo el horario.

### 3.3 Festivos

- Tabla `festivos` con fecha, nombre, `origen` (`calculado` o `manual`) y `activo`.
- **Generación:** `python -m app.cli generar-festivos --desde AAAA --hasta AAAA` (o `POST /api/v1/festivos/generar`,
  administrador). Es idempotente: no cambia fechas que ya existen. Con Docker Compose se generan los años 2025 a 2028
  al arrancar.
- **Manuales:** `POST /api/v1/festivos` y `PATCH /api/v1/festivos/{id}` (administrador). Un festivo desactivado
  (`activo = false`) no bloquea.
- **Respaldo:** si un año no tiene **ningún** festivo calculado en la tabla, el evaluador usa el cálculo de la
  Ley 51 de 1983 para ese año. Los festivos manuales y los desactivados se respetan.
- Rango de años: 1984 a 2100.

---

## 4. Horario y festivos

Para un instante dado, en la zona de la política:

1. Se obtiene la **fecha y hora local** y el día de la semana.
2. **Festivo:** si la fecha es festivo activo y `permitir_festivos` es `false` → motivo `FESTIVO`.
3. **Día sin franja:** si el día no tiene franjas (domingo por defecto) → motivo `DIA_SIN_FRANJA`.
4. **Fuera de franja:** si la hora no cae en ninguna franja del día → motivo `FUERA_DE_FRANJA`.

Si no hay motivos, el horario permite el contacto. La **próxima ventana** es el primer instante futuro en
que sí se permitiría (en un horizonte de 14 días). Se usa en los mensajes de error y para fijar reintentos.

---

## 5. Cómo se cuentan los contactos

### 5.1 Qué es un intento

Cada llamada **permitida** crea un registro de intento de contacto con: cliente, tipo de campaña, canal
(`voz`), iniciado por la empresa, momento (UTC), campaña, teléfono y versión de la política. Una llamada
bloqueada **no** crea intento.

Al tipificar la llamada, el intento recibe la marca de **contacto directo**:

| Resultado de la tipificación | Contacto directo |
|---|---|
| `contactado`, `promesa_pago`, `venta`, `rechazo` | Sí |
| `no_contesta`, `numero_errado` | No |
| `volver_a_llamar` | Lo indica el agente |
| Sin tipificar (llamada en curso o pendiente) | No, de momento |

### 5.2 Quién cuenta: el cliente y el tipo de campaña

- El historial es **global por cliente** (documento), no por campaña.
- Solo cuentan los intentos de campañas **del mismo tipo** que la política evaluada. Un contacto en una campaña
  de venta **no** limita una campaña de cobranza del mismo cliente, y viceversa.
- Cuentan todas las campañas del mismo tipo, sin importar cuál.

### 5.3 Qué intentos cuentan para el límite

- **Contable:** un intento iniciado por la empresa que sea contacto directo o, si `contar_intentos_sin_contacto`
  es `true`, cualquier intento de la empresa.
- Los intentos iniciados por el cliente **no consumen cupo**. Sí establecen contacto directo si
  `entrantes.establecen_contacto_directo` es `true`. En 2A no existen contactos iniciados por el cliente.

### 5.4 Ventana semanal

- `calendario` (por defecto): de **lunes 00:00 a lunes siguiente 00:00**, hora local.
- `movil_7_dias`: los 7 días anteriores al momento evaluado.
- En ambos casos cuentan solo los intentos **anteriores o iguales** al momento evaluado.

### 5.5 Reglas

1. **Umbral de contacto directo.** Si `solo_tras_contacto_directo` es `true` y en la ventana **no hay ningún**
   contacto directo, no hay límite de frecuencia. Los intentos sin contacto solos no bloquean.
2. **Límite diario (`FRECUENCIA_DIA`).** Si los contables del **mismo día local** son `≥ max_contactos_dia`,
   se bloquea.
3. **Límite de medios (`FRECUENCIA_MEDIOS`).** Los medios son `telefono` (voz) y `whatsapp` (mensajes y llamadas
   de WhatsApp). Si el número de medios distintos entre los contables de la ventana y el medio propuesto es
   mayor que `max_canales_semana`, se bloquea.

Con la política por defecto (`max_contactos_dia = 1`, `max_canales_semana = 1`), tras un contacto directo
por voz no se puede contactar por voz otra vez ese día, ni por WhatsApp esa semana.

### 5.6 Ejemplos

Los dos primeros casos están especificados como casos de prueba (F3 y F5 en
[`fase-2.md`](arquitectura/fase-2.md) §6). El tercero corresponde al F7, pero la próxima ventana de esa fila
la he derivado de la regla, porque la especificación no la indica. **Esta documentación no ejecutó ningún caso
de prueba.** Todos suponen la política por defecto y una campaña de cobranza.

| Historial del cliente (hora de Bogotá) | Llamada propuesta | Resultado | Próxima ventana permitida |
|---|---|---|---|
| Vie 23/10/2026 08:00, voz, **contacto directo** | Vie 23/10/2026 10:00, voz | Bloqueada: `FRECUENCIA_DIA` | Sáb 24/10/2026 08:00 |
| Igual | Sáb 24/10/2026 10:00, WhatsApp | Bloqueada: `FRECUENCIA_MEDIOS` | Lun 26/10/2026 07:00 |
| Lun 19/10 10:00, voz, contacto directo; vie 23/10 08:00, voz, **sin** contacto directo | Vie 23/10 10:00, voz | Bloqueada: `FRECUENCIA_DIA` (el intento sin contacto cuenta) | Sáb 24/10 08:00 |

Un cuarto caso (F2): con un intento sin contacto directo y sin ningún contacto directo en la semana, la misma
llamada del viernes a las 10:00 **sí** se permite, porque `solo_tras_contacto_directo` lo impide.

---

## 6. Cuándo se comprueba

| Momento | Dónde | Efecto |
|---|---|---|
| **Al autorizar cada llamada** (TwiML saliente) | Servidor, con la hora del servidor (UTC) convertida a la zona de la política | Si no se permite, la llamada queda **bloqueada** y no se marca. Antes de decidir, el servidor bloquea el cliente, de modo que dos llamadas simultáneas no pasan ambas. |
| **Ficha del cliente** (`GET /consola/registros/{id}`) | Servidor, en cada consulta | Informativo. Muestra los motivos por teléfono. No impide nada por sí mismo. |
| **Fecha de rellamada** (`volver_a_llamar_en`) | Servidor, al tipificar | Valida solo el **horario**, no la frecuencia. Si la fecha queda fuera de franja, se rechaza con la próxima ventana. |
| **Tras `no_contesta`** | Servidor, al tipificar | Propone el próximo intento en la **próxima ventana de horario**, no de frecuencia. La comprobación real ocurre al llamar. |
| **Interfaz** | Navegador | No decide nada. Solo muestra. |

En 2A no hay marcador automático ni envío masivo. Cada llamada la inicia una persona desde la consola.

---

## 7. Trazabilidad

- Cada intento guarda momento (UTC), canal, quién lo inició, contacto directo, resultado y la **versión de la
  política** aplicada (ADR-0012, punto 8).
- Cada llamada bloqueada se guarda con sus motivos (`motivos_bloqueo`) y se audita (`llamada.bloqueada`)
  con los códigos, sin números de teléfono.
- Los cambios de política (`politica.actualizar`) y de festivos (`festivo.crear`, `festivo.actualizar`,
  `festivos.generar`) quedan en la auditoría, junto con las exclusiones por número errado (`exclusion.crear`).
  Los detalles no contienen datos personales.

---

## 8. Exclusiones: RNE y números erróneos

- **Carga:** `POST /api/v1/exclusiones/importar` (administrador y supervisor), con un archivo CSV o XLSX con la
  columna `telefono`, y el motivo (`rne`, `solicitud_titular`, `numero_errado` o `manual`). El alcance `aplica_a`
  puede ser `venta`, `cobranza` o `todas`. Para `rne` sin valor, se usa `venta`.
- **Número errado:** al tipificar `numero_errado`, el número queda excluido para **todas** las campañas
  (`aplica_a = todas`), y aparece en `/exclusiones`.
- **Comprobación:** el número excluido para el tipo de campaña bloquea la llamada (`EXCLUIDO`). Se comprueba
  antes de la frecuencia.
- En 2A **no** se consulta el webservice del RNE. La lista se mantiene a mano desde archivos.
- Pregunta abierta: si las ofertas a clientes con relación contractual vigente son comerciales y están sujetas al
  RNE. Por defecto, sí (ver `docs/pendientes.md`, sección 1).

---

## 9. Qué no hace la plataforma en 2A

- No verifica la **autorización del consumidor** para cada canal (opt-in). Llega con WhatsApp (2B).
- No modela **excepciones de horario** por autorización del consumidor.
- No tiene marcador automático, reintentos automáticos ni marcación predictiva (Fase 3).
- No aplica **plazos de conservación** de grabaciones ni de datos (Fase 2F y 5).
- No cuenta la frecuencia **por campaña**: la regla es por cliente y tipo de campaña (sección 5.2).
- Los festivos calculados siguen solo la Ley 51 de 1983. Son editables, pero no provienen de una tabla oficial.
- **Aviso de grabación.** Solo se reproduce si `TELEFONIA_GRABAR` es `true`. Si se desactiva la grabación,
  también se desactiva el aviso. Si la norma exige el aviso con independencia de la grabación, debe corregirse.

---

## 10. Supuestos y preguntas abiertas

### 10.1 Supuestos de la subfase 2A

Se adoptan para desarrollar la plataforma. Cambian con coste bajo.

| Id | Supuesto | Relevancia legal |
|---|---|---|
| **S-A1** | La frecuencia se cuenta **por cliente global y por tipo de campaña**. Medios `telefono` y `whatsapp`. `contar_intentos_sin_contacto = true`. Los entrantes no consumen cupo, pero sí establecen contacto directo. | **Alta.** Es la lectura de frecuencia que el área debe confirmar. |
| **S-A2** | El agente ve el teléfono **enmascarado** y el documento **completo** (lo necesita para verificar la identidad en la llamada). | Media. Afecta al principio de minimización (Ley 1581). |
| **S-A3** | Promesa del agente: monto ≤ `saldo_total` si existe, fecha ≤ 60 días, una cuota. | Baja. Política de negocio. |
| **S-A4** | Reserva de 15 minutos; un registro reservado por agente a la vez. | Ninguna. Operativo. |
| **S-A5** | Tipificación obligatoria tras cada llamada realizada, coherente con el estado técnico. | Baja. |
| **S-A6** | Solo usuarios con rol `agente` se asignan a campañas y usan la consola. | Ninguna. |
| **S-A7** | `contactado` (habló con el titular, sin resultado concreto) deja el registro `gestionado`. Para volver a contactar se usa `volver_a_llamar`. | Media. Afecta a cuántas veces se puede llamar. |

### 10.2 Preguntas legales abiertas

**De la subfase 2A y de la frecuencia**

- **S-E1.** ¿Responder fuera de franja a un mensaje o una llamada **iniciados por el cliente** está permitido? Por
  defecto, sí (configurable). ¿Cuenta como «contacto» para la frecuencia?
- **S-E2.** ¿Basta un mensaje entrante como autorización del canal para responder? ¿Qué evidencia de opt-in vale para
  las plantillas (columna de la base, cláusula contractual, aceptación en el chat)?
- **S-E3.** ¿Qué alcance tiene el opt-out por WhatsApp: solo el canal o todos? ¿Afecta a todas las finalidades?
- ¿Es **«semana»** la semana calendario o una ventana móvil de 7 días? (S-A1.)
- ¿Cuentan los intentos **sin contacto directo** o solo los contactos? (S-A1.)
- ¿Se aplica igual a **ventas** que a **cobranza**? ¿O se cuentan juntas? (S-A1.)
- ¿Se gestiona la **excepción de horario** por autorización del consumidor? ¿Cómo se acredita el documento?
- ¿Las ofertas a clientes con relación contractual vigente son comerciales y están sujetas al RNE?
- ¿El RNE aplica a los mensajes comerciales de WhatsApp? Por defecto, sí (exclusiones con `canal = todos`).
- ¿Hay que reproducir el **aviso de grabación** aunque no se grabe la llamada? Hoy no se reproduce.
- ¿Cuál es el **texto aprobado** del aviso de grabación? Hoy es `TELEFONIA_AVISO_GRABACION` (texto de ejemplo).
- ¿Un **agente IA** puede celebrar acuerdos de pago y ventas vinculantes? ¿Qué constancia se exige? ¿Derecho de
  retracto en ventas a distancia (Ley 1480) y cómo se informa? (Subfase 2C.)
- Texto del **aviso de asistente virtual** y del aviso de privacidad. Tratamiento con IA y **transmisión
  internacional** a Anthropic y a Twilio (Ley 1581, art. 26). (Subfase 2C.)
- **Plazo de retención** de transcripciones y grabaciones. (Subfases 2C y 2F.)
- Contenido permitido en **plantillas de cobranza** (sin montos por defecto) y si el primer contacto puede
  mencionar que existe una deuda. (Subfase 2D.)
- ¿Varias obligaciones por cliente en la misma campaña? Afecta a la consulta de obligaciones (S2 de Fase 1).

Las preguntas de negocio y los requisitos externos (Twilio, Meta, Anthropic) están en
[`pendientes.md`](pendientes.md), secciones 5 y 6.
