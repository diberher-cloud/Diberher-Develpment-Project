# Importación de clientes desde CSV y Excel

Guía de referencia del formato de archivo que acepta `POST /api/v1/campanas/{id}/importaciones`.
Acepta **`.csv`** (Fase 1) y **`.xlsx`** (subfase 2A, ver [Excel (.xlsx)](#excel-xlsx)). Las reglas están
implementadas en `backend/app/modulos/importacion/` (`lector_csv.py`, `lector_xlsx.py`, `normalizacion.py`,
`telefonos.py`, `servicio.py`) y en las constantes de `servicio.py`.

Índice: [Columnas](#columnas) · [Documentos](#documentos) · [Teléfonos](#teléfonos) ·
[Montos y fechas](#montos-y-fechas) · [Codificación y delimitadores](#codificación-y-delimitadores) ·
[Excel (.xlsx)](#excel-xlsx) · [Límites](#límites) · [Deduplicación](#deduplicación) ·
[Exclusiones](#exclusiones-por-tipo-de-campaña) · [Resultado y conteos](#resultado-y-conteos) ·
[Códigos de error](#códigos-de-error) · [Ejemplos](#ejemplos) · [Exclusiones masivas (RNE)](#carga-masiva-de-exclusiones-rne)

---

## Permisos y llamada

- Endpoint: `POST /api/v1/campanas/{id}/importaciones`, `multipart/form-data` con el campo `archivo`.
- Roles: `administrador` y `supervisor`. Un agente recibe `403 PERMISO_DENEGADO`.
- El archivo debe tener extensión `.csv` o `.xlsx` (sin distinguir mayúsculas). Cualquier otra, incluidas
  `.xls` y `.xlsm`, responde `422 FORMATO_ARCHIVO_INVALIDO` con el mensaje «El archivo debe ser .csv o .xlsx.».
- La importación es **síncrona** y ocurre en **una sola transacción**: si hay un error inesperado
  se hace rollback y no queda ninguna importación parcial.

```bash
curl -X POST http://localhost:8000/api/v1/campanas/1/importaciones \
  -H "Authorization: Bearer $TOKEN" \
  -F "archivo=@cobranza_octubre.csv;type=text/csv"

# Excel
curl -X POST http://localhost:8000/api/v1/campanas/1/importaciones \
  -H "Authorization: Bearer $TOKEN" \
  -F "archivo=@cobranza_octubre.xlsx;type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
```

---

## Columnas

Las cabeceras se normalizan antes de compararlas: se pasan a minúsculas, se quitan tildes, los
espacios y guiones se convierten en `_` y se recortan. Por ejemplo, `Teléfono 1` → `telefono_1`,
`Número Documento` → `numero_documento`, `Días Mora` → `dias_mora`.

### Obligatorias (todas las campañas)

| Columna | Regla |
|---|---|
| `tipo_documento` | Uno de `CC`, `CE`, `NIT`, `PA`, `TI`, `PPT`. Se acepta en minúsculas (se normaliza a mayúsculas). Si no, `TIPO_DOCUMENTO_INVALIDO`. |
| `numero_documento` | Ver [Documentos](#documentos). Si no es válido, `DOCUMENTO_INVALIDO`. |
| `nombre` | Tras recortar y colapsar espacios, de 2 a 200 caracteres. Vacío → `CAMPO_REQUERIDO`; fuera de rango → `VALOR_INVALIDO`. |
| `telefono_1` | Teléfono colombiano válido (ver [Teléfonos](#teléfonos)). Obligatorio. |

Si falta alguna de estas cuatro cabeceras, el archivo completo se rechaza con `422 COLUMNAS_FALTANTES`.

### Opcionales generales

| Columna | Regla |
|---|---|
| `telefono_2`, `telefono_3` | Igual que `telefono_1`, pero opcionales: vacíos no generan incidencia. Si son inválidos, son advertencia y se ignoran. |
| `email` | Si no es un email válido, advertencia `EMAIL_INVALIDO` y el cliente se guarda sin email. |
| `ciudad` | Texto de hasta 100 caracteres. |

### Cobranza (campañas de tipo `cobranza`)

| Columna | Regla |
|---|---|
| `numero_obligacion` | Texto de hasta 50 caracteres. |
| `saldo_total`, `saldo_mora` | Monto (ver [Montos y fechas](#montos-y-fechas)). Inválido → `MONTO_INVALIDO` (error). |
| `dias_mora` | Entero mayor o igual a 0 (solo dígitos, hasta 9). Si no, `ENTERO_INVALIDO` (error). |
| `fecha_vencimiento` | `YYYY-MM-DD` o `DD/MM/YYYY`. Si no, `FECHA_INVALIDA` (error). |

### Venta (campañas de tipo `venta`)

| Columna | Regla |
|---|---|
| `producto` | Texto de hasta 120 caracteres. |
| `oferta` | Texto de hasta 2000 caracteres. |

### Autorización de WhatsApp (desde 2B, opcionales)

| Columna | Valores | Regla |
|---|---|---|
| `autoriza_whatsapp` | `si`, `sí`, `no` o vacío (sin distinguir mayúsculas) | Vacío: no hace nada. Cualquier otro valor: advertencia `AUTORIZACION_WHATSAPP_INVALIDA` y se ignora. |
| `fecha_autorizacion_whatsapp` | `YYYY-MM-DD` o `DD/MM/YYYY` (igual que `fecha_vencimiento`) | Obligatoria con `si`. Debe existir y no ser futura (hora de Bogotá). Si falta, es inválida o es futura: advertencia `AUTORIZACION_WHATSAPP_INVALIDA` y se ignora la autorización. |

Efecto, solo para los teléfonos **móviles** de la fila (`telefono_1`, `telefono_2`, `telefono_3`; los fijos se ignoran):

- `si` con fecha válida: se crea una autorización de WhatsApp por cada móvil, con la finalidad de **la campaña**
  (`venta` o `cobranza`), origen `importacion`, la evidencia `importacion:<id> fila <n>` y como fecha de otorgamiento
  el día indicado a las 00:00 de Bogotá. Si ya hay una vigente para esa finalidad, no se duplica.
- `no`: revoca las autorizaciones vigentes de WhatsApp de esos móviles **solo para la finalidad de la campaña**
  (`motivo_revocacion=importacion`). Las autorizaciones de finalidad `todas` no se tocan.
- Si el titular pidió la baja (opt-out) **después** de la fecha de autorización, esa autorización no se crea. La
  fila se importa con la advertencia `AUTORIZACION_REVOCADA_POR_OPT_OUT`, y la autorización cuenta como ignorada.

Las autorizaciones son necesarias para enviar plantillas de WhatsApp (ver [`cumplimiento-frecuencia.md`](cumplimiento-frecuencia.md)).
Los contadores se registran en la auditoría `importacion.autorizaciones` (`creadas`, `revocadas` e `ignoradas`).

```csv
tipo_documento;numero_documento;nombre;telefono_1;telefono_2;autoriza_whatsapp;fecha_autorizacion_whatsapp
CC;1020304050;María Pérez;300 123 4567;601 234 5678;si;2026-10-20
CC;52111222;Juan Ruiz;3109876543;;no;
CC;79000111;Ana Gil;3205550011;;sí;20/10/2026
```

- María: una autorización para su móvil (`telefono_1`); el fijo se ignora.
- Juan: se revocan sus autorizaciones de la finalidad de la campaña.
- Ana: `sí` con fecha en formato `DD/MM/YYYY`.

### Otras columnas

Cualquier otra cabecera se guarda en `datos_adicionales` del registro de campaña, con el nombre
normalizado como clave (por ejemplo, `Segmento` → `"segmento": "A"`). Las columnas de cobranza en una
campaña de venta (y al revés) se aceptan y van a `datos_adicionales`.

Si el mismo nombre aparece dos veces en la cabecera (tras normalizar), gana la primera columna. Las
cabeceras vacías se ignoran.

---

## Documentos

| Tipo | Normalización | Validación |
|---|---|---|
| `CC`, `TI`, `NIT` | Se quitan espacios, puntos y guiones. | Solo dígitos, de 4 a 15. |
| `CE`, `PA`, `PPT` | Se quitan espacios y se pasa a mayúsculas. | Alfanumérico, de 3 a 20. |

- `1.020.304.050` se guarda como `1020304050`.
- En NIT, el guion y el dígito de verificación se unen al número: `900.123.456-7` se guarda como `9001234567`.
- Los mensajes de error nunca muestran el documento completo: solo los últimos 4 caracteres (`***4050`).

---

## Teléfonos

Reglas de `backend/app/modulos/importacion/telefonos.py` (ADR-0007). Se normalizan a E.164 (`+57…`).

**Formatos aceptados**

- `3001234567`
- `300 123 4567`, `300-123-4567`
- `+57 300 123 4567`
- `573001234567` (12 dígitos que empiezan por 57)
- `3001234567.0` (decimal que Excel suele generar)
- Texto con dígitos, p. ej. `tel 3001234567` (ver [pendientes](pendientes.md))

**Tipo de línea**

- Móvil → `movil`.
- Fijo con indicativo de ciudad, p. ej. `601 234 5678` (Bogotá) → `fijo`.

**Rechazados**

| Caso | Código |
|---|---|
| Vacío (solo para `telefono_1`) | `TELEFONO_REQUERIDO` |
| Número no válido o con longitud incorrecta (`2345678`, `abc`) | `TELEFONO_INVALIDO` |
| Número de otro país (`+1 415 555 2671`, `+52 …`) | `TELEFONO_NO_COLOMBIANO` |
| Línea que no es móvil ni fija, p. ej. línea gratuita `018000…` | `TELEFONO_TIPO_NO_PERMITIDO` |

**Reglas de severidad**

- Si `telefono_1` es inválido pero `telefono_2` o `telefono_3` son válidos, la fila es **válida** y el
  problema de `telefono_1` es una advertencia.
- Si ningún teléfono es válido, la fila es **inválida**: error del teléfono y error `SIN_TELEFONO_VALIDO`.
- Un mismo número repetido dentro de la fila se guarda una sola vez.
- La prioridad del teléfono es su posición de columna (`telefono_1` = 1, `telefono_2` = 2, `telefono_3` = 3).

---

## Montos y fechas

**Montos** (`saldo_total`, `saldo_mora`). Se quitan los `$` y los espacios y después se aplica:

1. Formato colombiano: puntos como miles y coma como decimal (`^\d{1,3}(\.\d{3})+(,\d{1,2})?$`).
2. Formato decimal: punto o coma como decimal, con 1 o 2 decimales (`^\d+([.,]\d{1,2})?$`).
3. Cualquier otro valor es inválido (`MONTO_INVALIDO`).

| Valor | Resultado |
|---|---|
| `1.234.567,89` | `1234567.89` |
| `$ 1.500.000` | `1500000.00` |
| `1500000` | `1500000.00` |
| `1500.5` | `1500.50` |
| `1,5` | `1.50` |
| `1.500` | `1500.00` (se interpreta como miles; use `1500` o `1500,00` si quiso decir otra cosa) |
| `1,234.56`, `-5`, `1.5000`, `abc` | Inválido (`MONTO_INVALIDO`, error) |

Máximo: `999999999999.99` (columna `NUMERIC(14,2)`).

**Fechas** (`fecha_vencimiento`). Solo `YYYY-MM-DD` o `DD/MM/YYYY`. Las fechas inexistentes
(`31/02/2026`) son inválidas (`FECHA_INVALIDA`). Una celda vacía deja el campo sin valor.

---

## Codificación y delimitadores

- **Codificación**: se intenta UTF-8 (con o sin BOM). Si no decodifica, se usa `cp1252` (lo habitual
  en Excel para Windows). Si tampoco decodifica, `422 FORMATO_ARCHIVO_INVALIDO`. Un archivo con bytes
  nulos (`\x00`) también se rechaza.
- **Delimitador**: `;` o `,`. Se elige el que más aparece en la **primera línea no vacía** (la
  cabecera); en caso de empate, `,`. Por tanto, una cabecera con comas dentro de los nombres de columna y
  `;` como separador puede detectarse mal.
- **Comillas**: CSV estándar con `"`. Un campo con comas o saltos de línea debe ir entre comillas:
  `"Cupo preaprobado, sin cuota de manejo"`.
- **Líneas vacías**: se ignoran y no cuentan en `total_filas`.
- **Columnas de más o de menos**: una fila con menos columnas tiene vacías las que faltan; las sobrantes
  se ignoran.
- Los valores se recortan (espacios al inicio y al final).
- **Número de fila**: `fila` en los errores es el número de línea física donde empieza el registro
  (la cabecera es la línea 1).

---

## Excel (.xlsx)

Desde la subfase 2A, la importación de clientes y la carga masiva de exclusiones aceptan archivos `.xlsx`.
Después de leerlos, el procesamiento (normalización, deduplicación, exclusiones y conteos) es **el mismo que
para CSV**: las mismas cabeceras, los mismos códigos de fila y los mismos límites de filas.

### Qué se lee

- **Hoja:** la **primera hoja del libro** (según el orden de las hojas, no su nombre). Las demás se ignoran.
- **Cabeceras:** la primera fila que tiene contenido. Las filas vacías que la preceden se ignoran. Las cabeceras
  se normalizan como en CSV, y las vacías se ignoran.
- **Filas de datos:** el resto de filas con contenido. Las filas totalmente vacías, también las intermedias,
  se ignoran.
- **Número de fila** en los errores: el número de fila de la hoja de Excel, contando también las filas vacías.
  Coincide con lo que se ve en Excel si la hoja empieza en A1.

### Cómo se convierte cada celda

Antes de validar, cada celda se convierte a texto. La validación posterior es la de CSV.

| Contenido de la celda | Texto que recibe la validación | Ejemplo |
|---|---|---|
| Vacía | cadena vacía | — |
| Texto | recortado (sin espacios al inicio ni al final) | `" María Pérez "` → `María Pérez` |
| Booleano | `true` o `false` | `TRUE` → `true` |
| Número entero | sus dígitos | `3001234567` → `3001234567` |
| Número decimal que es entero (Excel lo guarda así a veces) | parte entera | `3001234567.0` → `3001234567` |
| Otro número | su representación decimal | `1500.5` → `1500.5`; `1234.56` → `1234.56` |
| Fecha sin hora (medianoche) | `AAAA-MM-DD` | `15/09/2026` (fecha de Excel) → `2026-09-15` |
| Fecha con hora | ISO 8601 | `2026-09-15 10:30` → `2026-09-15T10:30:00` |

Notas:

- **Números y montos.** Se usa el **valor almacenado** de la celda, no su formato de visualización. Un
  `1500000` con formato `$ 1.500.000` llega como `1500000`, que es válido. Un monto escrito como texto
  (`$ 1.500.000`) sigue las reglas de [Montos y fechas](#montos-y-fechas). Los números en notación científica
  (`1.5E+20`) no son válidos.
- **Fechas.** `fecha_vencimiento` acepta una fecha sin hora, como celda de fecha o como texto `DD/MM/YYYY`.
  Una fecha **con hora** no es válida: responde `FECHA_INVALIDA`. Con la celda de fecha de Excel, la hora
  debe estar vacía.
- **Teléfonos.** Un teléfono escrito como número (`3001234567`) es válido. Para los formatos de
  [Teléfonos](#teléfonos), basta con que las cifras sean las correctas.
- **Fórmulas.** Se lee el **último valor calculado guardado** en el archivo. Si la celda no tiene valor guardado
  (el archivo no se recalculó al guardarse), queda vacía. La plataforma no recalcula fórmulas.

### Límites y protecciones

| Protección | Valor | Respuesta si se supera |
|---|---|---|
| Tamaño del archivo | `IMPORTACION_MAX_BYTES` (10 MiB), el mismo que para CSV | `413 ARCHIVO_DEMASIADO_GRANDE`, incluso antes de autenticar |
| Tamaño descomprimido declarado en el ZIP del `.xlsx` | `IMPORTACION_MAX_BYTES_DESCOMPRIMIDO` (100 MiB) | `422 ARCHIVO_INVALIDO` («El archivo Excel descomprimido excede el tamaño permitido.») |
| Archivo que no es un `.xlsx` válido (no es un ZIP, o el libro no se puede abrir) | — | `422 ARCHIVO_INVALIDO` («No se pudo leer el archivo Excel.») |
| Filas de datos | `IMPORTACION_MAX_FILAS` (50 000); exclusiones: `EXCLUSIONES_MAX_FILAS` (200 000) | `422 DEMASIADAS_FILAS` |
| Sin filas de datos | — | `422 ARCHIVO_VACIO` |
| Faltan columnas obligatorias | — | `422 COLUMNAS_FALTANTES` |

Cómo se protege el lector:

- **Sin macros ni código.** El archivo no ejecuta macros ni VBA. Los libros con macros (`.xlsm`) se rechazan
  por su extensión.
- **Antes de abrir.** Se comprueba que el archivo sea un ZIP válido y se suman los tamaños descomprimidos que
  declara su índice, **sin descomprimir**. Si la suma supera el límite, se rechaza (protección contra archivos
  de descompresión masiva).
- **Solo lectura.** El libro se abre en modo de solo lectura, con los valores calculados. El lector no recalcula
  fórmulas.
- **XML seguro.** openpyxl analiza el XML con `defusedxml`, que es una dependencia del proyecto.
- **Errores controlados.** Cualquier excepción durante la lectura se convierte en `ARCHIVO_INVALIDO`. El mensaje
  no incluye datos del archivo.

### Ejemplo

Archivo `cobranza_octubre.xlsx`, primera hoja:

| tipo_documento | numero_documento | nombre | telefono_1 | saldo_total | fecha_vencimiento |
|---|---|---|---|---|---|
| CC | 1020304050 | María Pérez | 3001234567 | 1500000 (con formato `$ 1.500.000`) | 15/09/2026 (fecha de Excel) |
| CC | 52111222 | Juan Ruiz | 3109876543.0 | `$ 2.000.000` (texto) | 2026-09-01 (texto) |

- `1020304050` y `52111222` son documentos sin separadores: válidos.
- `3001234567` llega como número entero y `3109876543.0` como decimal entero: ambos son teléfonos móviles válidos.
- `1500000` se importa como `1500000.00`. `$ 2.000.000` (texto) se importa como `2000000.00`.
- La fecha de Excel `15/09/2026` llega como `2026-09-15` y es válida.

---

## Límites

| Límite | Valor | Variable | Respuesta si se supera |
|---|---|---|---|
| Tamaño del archivo | 10 MiB (10 485 760 bytes) | `IMPORTACION_MAX_BYTES` | `413 ARCHIVO_DEMASIADO_GRANDE` |
| Filas de datos | 50 000 | `IMPORTACION_MAX_FILAS` | `422 DEMASIADAS_FILAS` |
| Columnas adicionales (en `datos_adicionales`) | 20 | constante `MAX_CLAVES_ADICIONALES` | Advertencia `COLUMNAS_ADICIONALES_IGNORADAS` (fila 1); las sobrantes se ignoran |
| Longitud del nombre de una columna adicional | 50 caracteres | constante `MAX_LONGITUD_CLAVE` | Advertencia `COLUMNAS_ADICIONALES_IGNORADAS` (fila 1); esas columnas se ignoran |
| Valor de una columna adicional | 500 caracteres | constante `MAX_VALOR_ADICIONAL` | Se trunca a 500 caracteres, sin aviso |
| `nombre` | 2 a 200 caracteres | — | Error `CAMPO_REQUERIDO` o `VALOR_INVALIDO` |
| `ciudad` / `numero_obligacion` / `producto` / `oferta` | 100 / 50 / 120 / 2000 caracteres | — | Error `VALOR_INVALIDO` (la fila es inválida) |

El límite de tamaño se aplica en dos niveles: un middleware rechaza con `413` cualquier cuerpo cuyo
`Content-Length` supere `IMPORTACION_MAX_BYTES` más 1 MiB de margen, o cuyos bytes leídos lo superen,
**antes de autenticar**. Después, el servicio comprueba el tamaño exacto del archivo.

Para una cabecera con nombres de columna largos, se conservan las primeras 20 columnas adicionales
válidas (en orden de archivo) y las demás se ignoran.

---

## Deduplicación

La clave de un cliente es `(tipo_documento, numero_documento normalizado)`. Se revisa en este orden:

1. **Duplicado en el archivo**: la primera aparición gana. Las siguientes cuentan como
   `filas_duplicadas` con advertencia `DUPLICADO_EN_ARCHIVO` (indica la fila de la primera aparición).
2. **Duplicado en la campaña**: si el cliente ya pertenece a la campaña, cuenta como `filas_duplicadas`
   con advertencia `DUPLICADO_EN_CAMPANA`. No se actualiza ni se añaden teléfonos.

Los clientes son **globales**: un mismo documento importado en otra campaña no se duplica. Se actualiza
su `nombre` (y `email` o `ciudad` si la fila los trae no vacíos) y se añaden los teléfonos nuevos. Los
teléfonos ya conocidos no se repiten.

Una fila con errores se cuenta como inválida antes de comprobar duplicados.

---

## Exclusiones por tipo de campaña

Un número está excluido para una campaña de tipo `T` si existe una exclusión con `aplica_a` igual a `T`
o a `todas` (ver `docs/arquitectura/fase-1.md`, §3).

| Caso | Efecto |
|---|---|
| Todos los teléfonos válidos de la fila están excluidos | La fila **no** se importa (`filas_excluidas`). Advertencia `TODOS_TELEFONOS_EXCLUIDOS`. |
| Solo algunos teléfonos están excluidos | La fila **se importa**. Advertencia `TELEFONO_EXCLUIDO` por cada teléfono excluido (número enmascarado). |

Los teléfonos excluidos se marcan con `excluido: true` en `GET /api/v1/campanas/{id}/clientes`.
En Fase 1 no hay marcador, así que la comprobación al marcar llegará con la telefonía (fases 2 y 3).

---

## Resultado y conteos

Cada fila de datos se cuenta exactamente una vez en uno de cuatro grupos:

```
total_filas = filas_importadas + filas_duplicadas + filas_invalidas + filas_excluidas
```

El servicio comprueba esta igualdad con una aserción antes de confirmar la transacción.

Respuesta `201` (objeto `Importacion`):

| Campo | Significado |
|---|---|
| `total_filas` | Filas de datos del archivo (sin cabecera ni líneas vacías). |
| `filas_importadas` | Filas que crearon o actualizaron un cliente y se añadieron a la campaña. |
| `filas_duplicadas` | Repetidas en el archivo o ya presentes en la campaña. |
| `filas_invalidas` | Con algún error de severidad `error`. |
| `filas_excluidas` | Todos sus teléfonos válidos estaban excluidos. |
| `errores` | Hasta **100** incidencias (errores y advertencias) en orden de fila. |
| `errores_truncados` | `true` si hay más de 100. |

El detalle completo queda guardado: `GET /api/v1/importaciones/{id}/errores?severidad=&page=&page_size=`
(administrador y supervisor, paginado, orden `fila`).

---

## Códigos de error

### Códigos de fila

Severidad `error`: la fila es inválida y no se importa. Severidad `advertencia`: la fila se importa.

| Código | Severidad | Campo | Cuándo |
|---|---|---|---|
| `CAMPO_REQUERIDO` | error | `nombre` | Nombre vacío. |
| `VALOR_INVALIDO` | error | varios | Nombre fuera de 2–200, o texto que supera su longitud máxima. |
| `TIPO_DOCUMENTO_INVALIDO` | error | `tipo_documento` | Tipo fuera de `CC CE NIT PA TI PPT`. |
| `DOCUMENTO_INVALIDO` | error | `numero_documento` | Número no válido para su tipo. |
| `TELEFONO_REQUERIDO` | error o advertencia | `telefono_1` | `telefono_1` vacío. Advertencia si otro teléfono es válido. |
| `TELEFONO_INVALIDO` | error o advertencia | `telefono_N` | Número no válido. Advertencia si otro teléfono es válido. |
| `TELEFONO_NO_COLOMBIANO` | error o advertencia | `telefono_N` | Número de otro país. |
| `TELEFONO_TIPO_NO_PERMITIDO` | error o advertencia | `telefono_N` | Línea que no es móvil ni fija (p. ej. `018000`). |
| `SIN_TELEFONO_VALIDO` | error | — | Ningún teléfono es válido. |
| `EMAIL_INVALIDO` | advertencia | `email` | Email no válido; se guarda vacío. |
| `MONTO_INVALIDO` | error | `saldo_total` / `saldo_mora` | Monto no válido. |
| `ENTERO_INVALIDO` | error | `dias_mora` | No es un entero mayor o igual a 0. |
| `FECHA_INVALIDA` | error | `fecha_vencimiento` | Fecha no válida o en otro formato. |
| `DUPLICADO_EN_ARCHIVO` | advertencia | `numero_documento` | Documento repetido en el archivo. |
| `DUPLICADO_EN_CAMPANA` | advertencia | `numero_documento` | Cliente ya presente en la campaña. |
| `TODOS_TELEFONOS_EXCLUIDOS` | advertencia | `telefono_1` | Fila excluida por completo. |
| `TELEFONO_EXCLUIDO` | advertencia | `telefono_N` | Teléfono excluido; la fila se importa igualmente. |
| `COLUMNAS_ADICIONALES_IGNORADAS` | advertencia | — (fila 1) | Se ignoraron columnas por número o longitud de nombre. |
| `AUTORIZACION_WHATSAPP_INVALIDA` | advertencia | `autoriza_whatsapp` o `fecha_autorizacion_whatsapp` | Valor no reconocido, `si` sin fecha válida o fecha futura. La fila se importa sin esa autorización (desde 2B). |
| `AUTORIZACION_REVOCADA_POR_OPT_OUT` | advertencia | `autoriza_whatsapp` | El titular pidió la baja después de la fecha indicada; la autorización se omite (desde 2B). |

Los mensajes nunca incluyen el documento ni el teléfono completos (se enmascaran como `***4567`).

### Códigos de archivo

Estos errores se devuelven antes de procesar filas y **no crean ningún registro de importación**.

| HTTP | Código | Cuándo |
|---|---|---|
| 404 | `NO_ENCONTRADO` | La campaña no existe. |
| 409 | `CAMPANA_FINALIZADA` | La campaña está finalizada. |
| 413 | `ARCHIVO_DEMASIADO_GRANDE` | Supera 10 MiB. También lo devuelve el middleware antes de autenticar. |
| 422 | `FORMATO_ARCHIVO_INVALIDO` | Extensión distinta de `.csv` y `.xlsx` (incluidas `.xls` y `.xlsm`), codificación no reconocida, bytes nulos o CSV mal formado. |
| 422 | `ARCHIVO_INVALIDO` | `.xlsx` que no se puede leer (no es un ZIP válido, libro dañado) o cuyo tamaño descomprimido supera `IMPORTACION_MAX_BYTES_DESCOMPRIMIDO`. |
| 422 | `COLUMNAS_FALTANTES` | Falta `tipo_documento`, `numero_documento`, `nombre` o `telefono_1`. El campo `detalles` lista las ausentes. |
| 422 | `DEMASIADAS_FILAS` | Más de 50 000 filas de datos. |
| 422 | `ARCHIVO_VACIO` | Sin filas de datos (solo cabecera o líneas vacías). |
| 409 | `IMPORTACION_CONCURRENTE` | Otra operación modificó los mismos datos mientras se importaba (conflicto de integridad al confirmar). Nada se guarda; reintente la importación. |
| 500 | `ERROR_INTERNO` | Error no controlado. Nada se guarda (rollback). La respuesta no incluye trazas. |

---

## Ejemplos

### Cobranza

Archivo `cobranza_octubre.csv` (codificación UTF-8, delimitador `;`):

```csv
Tipo Documento;Número Documento;Nombre;Teléfono 1;Teléfono 2;Email;Ciudad;Número Obligación;Saldo Total;Saldo Mora;Días Mora;Fecha Vencimiento;Segmento
CC;1.020.304.050;María Pérez;300 123 4567;601 234 5678;maria@correo.co;Bogotá;OB-001;1.500.000;250.000,50;45;15/09/2026;A
CC;52111222;Juan Ruiz;3109876543;;;Cali;OB-002;$ 2.000.000;100000;30;2026-09-01;B
CC;52111222;Juan Ruiz duplicado;3001234567;;;;OB-003;1;1;1;2026-09-01;
```

Resultado esperado (`201`):

```json
{
  "id": 7,
  "campana_id": 1,
  "nombre_archivo": "cobranza_octubre.csv",
  "estado": "completada",
  "total_filas": 3,
  "filas_importadas": 2,
  "filas_duplicadas": 1,
  "filas_invalidas": 0,
  "filas_excluidas": 0,
  "creado_por": 2,
  "creado_en": "2026-10-23T15:10:00Z",
  "errores": [
    {
      "fila": 4,
      "campo": "numero_documento",
      "codigo": "DUPLICADO_EN_ARCHIVO",
      "mensaje": "Documento repetido en el archivo (primera aparición en la fila 3).",
      "severidad": "advertencia"
    }
  ],
  "errores_truncados": false
}
```

Lo que ocurre en cada fila:

- **Fila 2**: `1.020.304.050` → `1020304050`. `telefono_1` → `+573001234567` (móvil) y `telefono_2` → `+576012345678` (fijo). Saldo `1.500.000` → `1500000.00`. `Segmento` queda en `datos_adicionales`.
- **Fila 3**: `$ 2.000.000` → `2000000.00`. Sin email ni `telefono_2`.
- **Fila 4**: el documento ya aparece en la fila 3, así que es duplicado en el archivo. El resto de sus datos no se aplica.

### Venta

Archivo `oferta_tarjeta.csv` (codificación UTF-8, delimitador `,`; el campo `oferta` va entre comillas
porque contiene una coma):

```csv
tipo_documento,numero_documento,nombre,telefono_1,telefono_2,email,ciudad,producto,oferta
CC,1020304050,María Pérez,300 123 4567,,maria@correo.co,Bogotá,Tarjeta Plus,"Cupo preaprobado, sin cuota de manejo el primer año"
NIT,900.123.456-7,Comercial Andina SAS,6012345678,,compras@andina.co,Medellín,Plan Empresa,Descuento del 10 % en la renovación
CE,AB123456,Pedro Gómez,3109876543,,correo-invalido,,Tarjeta Plus,Oferta sin correo válido
```

Si se importa en una campaña de tipo `venta`, el resultado es:

- `total_filas`: 3; `filas_importadas`: 3; `filas_duplicadas`: 0; `filas_invalidas`: 0; `filas_excluidas`: 0.
- `errores`: una advertencia `EMAIL_INVALIDO` en la fila 4 (campo `email`, "Email inválido; se ignora."). Pedro
  Gómez se importa sin email.
- El NIT `900.123.456-7` se guarda como `9001234567`.

### Archivo de prueba del repositorio

`backend/tests/fixtures/cobranza_mixta.csv` cubre cada tipo de resultado (importada, duplicada, inválida,
excluida, teléfono excluido parcialmente). Con `+573005550000` excluido para cobranza, el resultado es
`filas_importadas: 3`, `filas_duplicadas: 1`, `filas_invalidas: 2`, `filas_excluidas: 1` (las pruebas
`backend/tests/api/test_importacion.py` verifican este caso).

---

## Carga masiva de exclusiones (RNE)

`POST /api/v1/exclusiones/importar` (administrador y supervisor), `multipart/form-data`:

| Campo | Obligatorio | Regla |
|---|---|---|
| `archivo` | sí | CSV o XLSX con columna obligatoria `telefono`. Mismas reglas de archivo que las importaciones (extensión, codificación, delimitador, 10 MiB; en XLSX, [Excel (.xlsx)](#excel-xlsx)). Máximo 200 000 filas (`EXCLUSIONES_MAX_FILAS`). |
| `motivo` | sí | `rne`, `solicitud_titular`, `numero_errado` o `manual`. |
| `aplica_a` | no si `motivo=rne` | `venta`, `cobranza` o `todas`. Con `rne` y sin valor, se usa `venta`. Con otro motivo es obligatorio: si falta, `422` antes de leer el archivo. |
| `canal` | no | `todos` (por defecto), `voz` o `whatsapp` (desde 2B). Una exclusión `voz` solo bloquea las llamadas; `whatsapp` solo los mensajes; `todos` bloquea ambos. |

Respuesta `200`:

```json
{
  "total_filas": 1000,
  "creadas": 990,
  "duplicadas": 8,
  "invalidas": 2,
  "errores": [
    { "fila": 17, "campo": "telefono", "codigo": "TELEFONO_INVALIDO", "mensaje": "Teléfono inválido (***1234).", "severidad": "error" }
  ],
  "errores_truncados": false
}
```

- Duplicada: ya existe la combinación `(numero_e164, aplica_a, canal)` o el número se repite en el archivo.
- Inválida: el teléfono no supera la normalización (mismos códigos que en importación de clientes).
- Los errores se limitan a 100 (`errores_truncados` indica si hubo más).
- Todo se guarda en una transacción; un conflicto de concurrencia devuelve `409 EXCLUSION_CONCURRENTE`.
