# Subfase 2B — WhatsApp base y bandeja de chat para agentes humanos

> Fuente de verdad para backend, frontend, QA y documentación durante la subfase 2B. Se separa de
> [`fase-2.md`](fase-2.md) por tamaño; las convenciones de la Fase 1 (`fase-1.md` §4) y de 2A
> (`fase-2.md` §4.1) siguen vigentes salvo lo que se indica aquí. Decisiones: ADR-0010 a ADR-0013,
> ADR-0016 y [ADR-0019](adr-0019-whatsapp-bandeja-humana.md) (decisiones propias de 2B). Migración:
> `0003`.

## 0. Índice

1. Alcance · 2. Estructura y dependencias · 3. Esquema y migración `0003` · 4. Contratos de API ·
5. Configuración y docker-compose · 6. Tareas · 7. Riesgos y preguntas abiertas.

---

## 1. Alcance

**Incluye**
1. `ProveedorWhatsApp` (Twilio + falso) con tipos neutros, firma Twilio compartida con voz y endpoints
   de **simulación** (solo `ENTORNO != produccion` y `WHATSAPP_PROVEEDOR=falso`).
2. Cola `trabajos` en BD + worker `python -m app.worker` + servicio `worker` en docker-compose
   (ADR-0013), con latido y healthcheck.
3. Webhooks de Twilio Messaging: entrante (persistir y encolar) y estado de entrega (idempotente,
   monótono), con firma.
4. Conversaciones y mensajes (ADR-0011) con **resolución determinista del contexto**, ventana de 24 h,
   estados de atención preparados para el dueño IA de 2C (§3.3).
5. Bandeja humana: cola de atención, tomar / tomar siguiente / asignar / liberar, historial, responder
   texto en ventana, plantilla fuera de ella, vincular registro, cerrar con tipificación
   (`canal=whatsapp_mensaje`).
6. Plantillas: sincronización desde Twilio Content API, mapeo de variables a lista blanca, finalidad,
   activación.
7. Opt-in (`autorizaciones_canal`, importación, alta manual con evidencia) y opt-out determinista y
   manual; exclusiones por canal.
8. Cumplimiento de WhatsApp: plantilla = contacto iniciado por la empresa (franja, festivo,
   frecuencia, exclusión, opt-in); respuesta = según `entrantes.responder_fuera_de_franja`.
9. Envío individual de plantilla desde la ficha de la consola de voz.
10. Medios entrantes por proxy autenticado (sin almacenar el binario).
11. Eventos de tiempo real nuevos por el WebSocket con tickets existente.
12. Deudas de 2A: variables de entorno en docker-compose (§5.2) y ADR-0003/ADR-0017 actualizados
    (hecho por arquitectura).

**No incluye**: agente IA (2C), envíos masivos y recordatorios (2D), llamadas de WhatsApp (2E),
retención/anonimización y reportes (2F), **medios salientes** (el agente no adjunta archivos en 2B),
transcripción de audios, varios números de empresa (un sender: `WHATSAPP_NUMERO_EMPRESA`).

**Sin credenciales reales**: `WHATSAPP_PROVEEDOR=falso` + simulador (`/whatsapp/simulacion/*` y página
`/whatsapp/simulador`). Con Twilio real solo cambian variables de entorno (§5).

---

## 2. Estructura y dependencias

### 2.1 Estructura de carpetas (nuevo o modificado en 2B)

```
backend/
├── pyproject.toml                         # + httpx (dependencia de producción, §2.2)
├── alembic/versions/0003_whatsapp_bandeja.py
├── app/
│   ├── config.py                          # + variables §5.1 y validación WHATSAPP_PROVEEDOR=twilio
│   ├── main.py                            # + routers 2B; simulación WhatsApp condicionada
│   ├── worker.py                          # python -m app.worker [--healthcheck] (bucle, señales, latido)
│   ├── catalogos.py                       # + catálogos de §3 (estados, autores, motivos de cola…)
│   ├── integraciones/
│   │   ├── twilio_webhook.py              # validar_peticion_twilio() común voz/WhatsApp (sale de telefonia/router.py)
│   │   └── whatsapp/
│   │       ├── proveedor.py               # Protocol ProveedorWhatsApp + tipos neutros (§4.3)
│   │       ├── twilio.py                  # ProveedorWhatsAppTwilio (SDK twilio + httpx para medios)
│   │       ├── falso.py                   # ProveedorWhatsAppFalso (memoria, reglas de error por número)
│   │       └── fabrica.py                 # obtener_proveedor_whatsapp() según WHATSAPP_PROVEEDOR
│   ├── trabajos/
│   │   ├── modelos.py                     # Trabajo, LatidoWorker
│   │   ├── cola.py                        # encolar, tomar, completar, fallar, ejecutar_pendientes
│   │   ├── registro.py                    # MANEJADORES {tipo: función}; ErrorTrabajo
│   │   └── periodicos.py                  # programación de trabajos periódicos
│   └── modulos/
│       ├── whatsapp/
│       │   ├── opt_out.py                 # PURO: normalizar(texto), clasificar(texto, payload)
│       │   ├── ventana.py                 # PURO: ventana_abierta, decidir_respuesta
│       │   ├── plantillas_render.py       # PURO: variables_de(cuerpo), renderizar(cuerpo, valores), CAMPOS
│       │   ├── medios.py                  # PURO: categoria(tipo_contenido), cabeceras de respuesta
│       │   ├── modelos.py                 # PlantillaWhatsApp, AutorizacionCanal
│       │   ├── esquemas.py
│       │   ├── servicio_entrante.py       # webhook entrante + trabajo whatsapp.procesar_entrante
│       │   ├── servicio_envio.py          # texto, plantilla, automáticos, trabajo whatsapp.enviar_mensaje
│       │   ├── servicio_estado.py         # webhook de estado (monótono)
│       │   ├── servicio_plantillas.py     # sincronizar, actualizar, enviables
│       │   ├── servicio_autorizaciones.py # alta, revocación, opt-out (aplicar_opt_out)
│       │   ├── router.py                  # webhooks, configuración, plantillas, autorizaciones
│       │   └── router_simulacion.py
│       ├── conversaciones/
│       │   ├── dueno.py                   # PURO: transiciones de dueño (§3.3)
│       │   ├── resolucion.py              # resolución determinista del contexto (consultas acotadas)
│       │   ├── modelos.py                 # Conversacion, Mensaje, EventoMensaje, ColaAtencion
│       │   ├── esquemas.py
│       │   ├── servicio.py                # cambiar_dueno (único punto), cerrar, vincular, leer
│       │   ├── atencion.py                # cola: tomar_siguiente, capacidad, PRIORIDAD
│       │   ├── cierre_inactivas.py        # trabajo periódico conversaciones.cerrar_inactivas
│       │   └── router.py                  # /conversaciones/*, /atencion/*
│       ├── exclusiones/                   # + canal, origen, creado_por nulo; consultas por canal
│       ├── campanas/                      # + whatsapp_habilitado, plantilla_inicial_id
│       ├── importacion/servicio.py        # + autoriza_whatsapp, fecha_autorizacion_whatsapp
│       ├── consola/
│       │   ├── servicio.py                # exclusiones por canal; TelefonoFicha.whatsapp; plantilla desde la ficha
│       │   ├── tipificacion.py            # factorizar validación/efectos para reutilizar con conversacion_id
│       │   └── estado.py                  # al pasar a desconectado: conversaciones del agente → cola
│       ├── telefonia/servicio.py          # exclusiones: canal IN ('todos','voz')
│       └── supervision/                   # + GET /supervision/trabajos
└── tests/
    ├── conftest.py                        # + proveedor WhatsApp falso, firmar_twilio() reutilizado, ejecutar_pendientes
    ├── unit/
    │   ├── test_opt_out.py, test_ventana.py, test_plantillas_render.py, test_medios.py,
    │   ├── test_dueno_conversacion.py, test_cola_trabajos.py
    ├── api/
    │   ├── test_webhook_entrante.py, test_webhook_estado_mensaje.py, test_resolucion_contexto.py,
    │   ├── test_conversaciones.py, test_atencion_cola.py, test_envio_texto.py, test_envio_plantilla.py,
    │   ├── test_plantillas.py, test_autorizaciones.py, test_exclusiones_canal.py, test_opt_out_api.py,
    │   ├── test_cierre_conversacion.py, test_medios_proxy.py, test_simulacion_whatsapp.py,
    │   ├── test_worker.py, test_importacion_autorizaciones.py, test_websocket_2b.py,
    │   ├── test_permisos_fase2b.py, test_migracion_0003.py
    │   └── test_postgres_2b.py            # marcador postgres (§6 [qa] P1-P10)
frontend/src/
├── api/tipos.ts, endpoints.ts             # + §4.15
├── paginas/
│   ├── Bandeja.tsx                        # /bandeja (agente, supervisor, administrador)
│   ├── PlantillasWhatsApp.tsx             # /whatsapp/plantillas (A, S)
│   ├── Autorizaciones.tsx                 # /autorizaciones (A, S)
│   └── SimuladorWhatsApp.tsx              # /whatsapp/simulador (solo si configuracion.simulacion)
├── componentes/bandeja/
│   ├── ColaAtencion.tsx, ListaConversaciones.tsx, VistaConversacion.tsx, BurbujaMensaje.tsx,
│   ├── CompositorMensaje.tsx, SelectorPlantilla.tsx, CerrarConversacion.tsx,
│   ├── VincularRegistro.tsx, AdjuntoMedia.tsx, AccionesConversacion.tsx
├── componentes/consola/
│   ├── FichaCliente.tsx                   # + insignia WhatsApp por teléfono y "Enviar plantilla"
│   └── FormularioTipificacion.tsx         # reutilizable con contexto 'llamada' | 'conversacion'
├── paginas/CampanaFormulario.tsx          # + whatsapp_habilitado, plantilla_inicial_id
├── paginas/Exclusiones.tsx                # + canal (columna, filtro, alta e importación)
├── paginas/SupervisionAgentes.tsx         # + tarjeta de estado del worker (GET /supervision/trabajos)
└── test/                                  # + bandeja, compositor, plantillas, autorizaciones, simulador, tiempoReal2b
```

### 2.2 Dependencias nuevas

| Paquete | Versión | Uso y justificación |
|---|---|---|
| httpx | `>=0.27,<1` | Descarga de medios de Twilio con Basic Auth, límite de bytes y timeouts; elimina `Authorization` en redirecciones a otro origen (Twilio redirige a su CDN). En tests se usa `httpx.MockTransport` (sin red). Ya está en el lock como dependencia de desarrollo; pasa a producción. |

Sin dependencias nuevas en el frontend. `twilio>=9.3` ya incluye Messaging y Content API v1.

---

## 3. Esquema de base de datos — migración `0003_whatsapp_bandeja`

Convenciones de Fase 1/2A (PK `id INTEGER`, `FechaHoraUTC`, enumeraciones `VARCHAR + CHECK` con
`catalogos.en_lista`, `render_as_batch`). `revision = "0003"`, `down_revision = "0002"`. Las "claves
mientras está vivo" (`clave_abierta`, `clave_vigente`, `clave_activa`, `trabajos.clave_unica`) siguen el
patrón portable de ADR-0011: valor mientras la fila está activa, `NULL` después, `UNIQUE` simple.

### 3.1 Tablas nuevas

#### `plantillas_whatsapp`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| content_sid | varchar(64) | NOT NULL, UNIQUE (`HX…`; en falso `HXfalso…`) |
| nombre | varchar(200) | NOT NULL (`friendly_name` / nombre en Meta) |
| idioma | varchar(10) | NOT NULL (`es`, `es_CO`…) |
| categoria | varchar(15) | NOT NULL, CHECK in (`marketing`,`utility`,`authentication`,`desconocida`) |
| estado_aprobacion | varchar(15) | NOT NULL, CHECK in (`aprobada`,`pendiente`,`rechazada`,`pausada`,`deshabilitada`,`eliminada`,`desconocido`) |
| motivo_rechazo | varchar(300) | NULL |
| cuerpo | text | NOT NULL (texto con `{{1}}`, `{{2}}`…) |
| variables | JSON | NOT NULL default `[]` (lista ordenada de claves: `["1","2"]`) |
| botones | JSON | NOT NULL default `[]` (`[{ "tipo": "respuesta_rapida", "texto": "Darme de baja", "payload": "BAJA" }]`) |
| tiene_boton_baja | boolean | NOT NULL default false (algún botón con `payload == WHATSAPP_PAYLOAD_BAJA`) |
| mapeo_variables | JSON | NOT NULL default `{}` (`{"1":"primer_nombre","2":"empresa"}`) |
| finalidad | varchar(10) | NULL hasta configurarse, CHECK NULL o in (`venta`,`cobranza`,`todas`) |
| activa | boolean | NOT NULL default false |
| sincronizada_en | FechaHoraUTC | NOT NULL |
| actualizado_por | integer | FK usuarios.id, NULL |
| actualizado_en | FechaHoraUTC | NOT NULL |
| | | CHECK `activa = false OR (estado_aprobacion = 'aprobada' AND finalidad IS NOT NULL)` |

#### `conversaciones`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| clave_abierta | varchar(40) | NULL, UNIQUE (`"<cliente_e164>|<empresa_e164>"` mientras `estado='abierta'`) |
| numero_cliente_e164 | varchar(16) | NOT NULL, INDEX |
| numero_empresa_e164 | varchar(16) | NOT NULL |
| nombre_perfil | varchar(100) | NULL (`ProfileName` de WhatsApp; dato personal) |
| cliente_id | integer | FK clientes.id, NULL, INDEX |
| campana_id | integer | FK campanas.id, NULL |
| campana_cliente_id | integer | FK campana_clientes.id, NULL, INDEX |
| telefono_id | integer | FK telefonos.id, NULL |
| estado | varchar(10) | NOT NULL, CHECK in (`abierta`,`cerrada`) |
| atendida_por | varchar(12) | NOT NULL, CHECK in (`sin_asignar`,`humano`,`ia`) |
| usuario_asignado_id | integer | FK usuarios.id, NULL |
| asignada_en | FechaHoraUTC | NULL |
| iniciada_por | varchar(10) | NOT NULL, CHECK in (`empresa`,`cliente`) |
| intento_contacto_id | integer | FK intentos_contacto.id, NULL (intento que abrió el contacto) |
| ventana_expira_en | FechaHoraUTC | NULL (último entrante + 24 h; nulo si el cliente no ha escrito) |
| ultimo_mensaje_en | FechaHoraUTC | NOT NULL |
| ultimo_entrante_en | FechaHoraUTC | NULL |
| mensajes_sin_leer | integer | NOT NULL default 0, CHECK >= 0 |
| aviso_espera_enviado_en | FechaHoraUTC | NULL |
| aviso_fuera_franja_enviado_en | FechaHoraUTC | NULL |
| abierta_en | FechaHoraUTC | NOT NULL |
| cerrada_en | FechaHoraUTC | NULL |
| motivo_cierre | varchar(15) | NULL, CHECK NULL o in (`agente`,`supervisor`,`inactividad`,`opt_out`,`sistema`) |
| cerrada_por | integer | FK usuarios.id, NULL |
| *Previstas para 2C (sin lógica en 2B)* | | |
| identidad_verificada | boolean | NOT NULL default false |
| identidad_intentos | integer | NOT NULL default 0 |
| turnos_ia | integer | NOT NULL default 0 |
| costo_usd_acumulado | numeric(12,6) | NOT NULL default 0 |
| modelo_ia | varchar(40) | NULL |
| esfuerzo_ia | varchar(10) | NULL |
| prompt_version | integer | NULL |
| aviso_ia_enviado_en | FechaHoraUTC | NULL |
| | | CHECK `(estado='abierta' AND clave_abierta IS NOT NULL AND cerrada_en IS NULL) OR (estado='cerrada' AND clave_abierta IS NULL AND cerrada_en IS NOT NULL)` |
| | | CHECK `(atendida_por='humano' AND usuario_asignado_id IS NOT NULL) OR (atendida_por<>'humano' AND usuario_asignado_id IS NULL)` |
| | | CHECK `campana_cliente_id IS NULL OR (campana_id IS NOT NULL AND cliente_id IS NOT NULL)` |
| | | INDEX (`estado`, `atendida_por`), (`usuario_asignado_id`, `estado`), (`campana_id`, `estado`) |

Al cerrar se conservan `atendida_por` y `usuario_asignado_id` (quién la tuvo al final).

#### `mensajes`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| conversacion_id | integer | FK conversaciones.id, NULL (solo entrantes aún sin procesar) |
| numero_cliente_e164 | varchar(16) | NOT NULL |
| direccion | varchar(10) | NOT NULL, CHECK in (`entrante`,`saliente`) |
| autor | varchar(10) | NOT NULL, CHECK in (`cliente`,`agente`,`ia`,`sistema`) |
| usuario_id | integer | FK usuarios.id, NULL; CHECK `autor <> 'agente' OR usuario_id IS NOT NULL` |
| tipo | varchar(15) | NOT NULL, CHECK in (`texto`,`plantilla`,`media`,`boton`,`no_soportado`) |
| cuerpo | text | NULL (≤ 4096; entrante: `Body`; plantilla: texto renderizado) |
| plantilla_id | integer | FK plantillas_whatsapp.id, NULL |
| variables | JSON | NULL (valores enviados a la plantilla) |
| media | JSON | NOT NULL default `[]` (`[{ "indice":0, "tipo_contenido":"image/jpeg", "categoria":"imagen", "url_proveedor":"https://api.twilio.com/…" }]`) |
| boton_payload | varchar(256) | NULL |
| boton_texto | varchar(256) | NULL |
| respuesta_a_proveedor_id | varchar(64) | NULL (`OriginalRepliedMessageSid`) |
| proveedor_id | varchar(64) | NULL, UNIQUE (`MessageSid`; saliente: al aceptarlo el proveedor) |
| idempotencia_clave | varchar(64) | NULL, UNIQUE (UUID del cliente web) |
| estado | varchar(10) | NOT NULL, CHECK in (`recibido`,`pendiente`,`retenido`,`enviando`,`enviado`,`entregado`,`leido`,`fallido`,`cancelado`) |
| error_codigo | varchar(30) | NULL (código Twilio/Meta o propio: `VENTANA_CERRADA`, `ENVIO_INCIERTO`…) |
| programado_para | FechaHoraUTC | NULL (retenidos) |
| creado_en | FechaHoraUTC | NOT NULL (entrante: recepción del webhook) |
| enviado_en | FechaHoraUTC | NULL |
| entregado_en | FechaHoraUTC | NULL |
| leido_en | FechaHoraUTC | NULL |
| procesado_en | FechaHoraUTC | NULL (entrante: procesado por el worker) |
| procesado_ia_en | FechaHoraUTC | NULL (*previsto 2C*: consumido por un turno de IA) |
| | | CHECK `direccion = 'entrante' OR conversacion_id IS NOT NULL` |
| | | CHECK `(direccion='entrante' AND autor='cliente' AND estado='recibido') OR (direccion='saliente' AND autor<>'cliente' AND estado<>'recibido')` |
| | | INDEX (`conversacion_id`, `id`) |

#### `eventos_mensaje`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| proveedor_id | varchar(64) | NOT NULL |
| mensaje_id | integer | FK mensajes.id ON DELETE CASCADE, NULL (el estado puede llegar antes de guardar el SID) |
| estado_proveedor | varchar(20) | NOT NULL (`queued`,`sent`,`delivered`,`read`,`failed`,`undelivered`…) |
| error_codigo | varchar(30) | NULL |
| recibido_en | FechaHoraUTC | NOT NULL |
| | | UNIQUE (`proveedor_id`, `estado_proveedor`); INDEX (`mensaje_id`) |

#### `autorizaciones_canal`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| numero_e164 | varchar(16) | NOT NULL, INDEX |
| canal | varchar(10) | NOT NULL, CHECK in (`whatsapp`) |
| finalidad | varchar(10) | NOT NULL, CHECK in (`venta`,`cobranza`,`todas`) |
| origen | varchar(12) | NOT NULL, CHECK in (`importacion`,`cliente`,`agente`,`agente_ia`) |
| evidencia | varchar(500) | NOT NULL |
| otorgada_en | FechaHoraUTC | NOT NULL |
| registrada_por | integer | FK usuarios.id, NULL |
| importacion_id | integer | FK importaciones.id, NULL |
| conversacion_id | integer | FK conversaciones.id, NULL |
| clave_vigente | varchar(40) | NULL, UNIQUE (`"<numero>|<canal>|<finalidad>"` mientras no está revocada) |
| revocada_en | FechaHoraUTC | NULL |
| revocada_por | integer | FK usuarios.id, NULL |
| motivo_revocacion | varchar(12) | NULL, CHECK NULL o in (`opt_out`,`manual`,`importacion`) |
| creado_en | FechaHoraUTC | NOT NULL |
| | | CHECK `(revocada_en IS NULL AND clave_vigente IS NOT NULL) OR (revocada_en IS NOT NULL AND clave_vigente IS NULL)` |
| | | CHECK `origen NOT IN ('agente','cliente') OR registrada_por IS NOT NULL` |

Una autorización **vigente** para la finalidad `F` es una fila con `clave_vigente` no nula y
`finalidad IN (F, 'todas')`. `origen=cliente`: el cliente la dio en el chat y la registró el dueño de
la conversación; `origen=agente`: alta manual con evidencia externa.

#### `cola_atencion`
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| conversacion_id | integer | FK conversaciones.id ON DELETE CASCADE, NOT NULL, INDEX |
| campana_id | integer | FK campanas.id, NULL (desnormalizado para filtrar; nulo = sin campaña) |
| motivo | varchar(25) | NOT NULL, CHECK in catálogo `MOTIVOS_COLA` (abajo) |
| resumen | varchar(500) | NULL (lo rellena la IA en 2C) |
| prioridad | integer | NOT NULL, CHECK 1..3 |
| estado | varchar(10) | NOT NULL, CHECK in (`pendiente`,`asignada`,`cerrada`) |
| clave_activa | varchar(20) | NULL, UNIQUE (`str(conversacion_id)` mientras `pendiente`/`asignada`) |
| asignada_a | integer | FK usuarios.id, NULL |
| creado_en | FechaHoraUTC | NOT NULL |
| asignada_en | FechaHoraUTC | NULL |
| cerrada_en | FechaHoraUTC | NULL |
| | | INDEX (`estado`, `prioridad`, `creado_en`) |

`MOTIVOS_COLA` (incluye ya los de 2C para no alterar el CHECK en `0004`): `entrante`, `sin_campana`,
`liberada`, `agente_desconectado`, `supervisor`, `solicitud_cliente`, `queja`, `ia_no_resuelve`,
`identidad_bloqueada`, `ia_rechazo`, `ia_max_tokens`, `ia_iteraciones`, `ia_stop_inesperado`,
`ia_monto_no_respaldado`, `ia_error`, `presupuesto_excedido`, `ia_desactivada`.
Prioridad por defecto (`atencion.PRIORIDAD`): 1 = `solicitud_cliente`, `queja`, `identidad_bloqueada`,
todos los `ia_*` y `presupuesto_excedido`; 2 = el resto.

#### `trabajos` (ADR-0013 §4)
| columna | tipo | restricciones |
|---|---|---|
| id | integer | PK |
| tipo | varchar(60) | NOT NULL (sin CHECK: lo valida `trabajos/registro.py`; 2C/2D añaden tipos sin migrar) |
| clave_unica | varchar(120) | NULL, UNIQUE (deduplica **mientras está `pendiente`**; se pone a NULL al tomarlo) |
| payload | JSON | NOT NULL default `{}` (**solo ids y catálogos**, nunca texto de mensajes ni números) |
| estado | varchar(12) | NOT NULL, CHECK in (`pendiente`,`en_proceso`,`completado`,`fallido`,`cancelado`) |
| intentos | integer | NOT NULL default 0 |
| max_intentos | integer | NOT NULL default 5, CHECK 1..20 |
| disponible_desde | FechaHoraUTC | NOT NULL |
| bloqueado_hasta | FechaHoraUTC | NULL |
| bloqueado_por | varchar(80) | NULL (id del trabajador) |
| ultimo_error | varchar(300) | NULL (`TipoExcepcion:codigo`, sin datos personales) |
| creado_en | FechaHoraUTC | NOT NULL |
| actualizado_en | FechaHoraUTC | NOT NULL |
| completado_en | FechaHoraUTC | NULL |
| | | INDEX (`estado`, `disponible_desde`) |

#### `latidos_worker`
| columna | tipo | restricciones |
|---|---|---|
| trabajador | varchar(80) | PK (`<hostname>-<pid>`) |
| iniciado_en | FechaHoraUTC | NOT NULL |
| ultimo_latido | FechaHoraUTC | NOT NULL |
| version | varchar(20) | NOT NULL |

### 3.2 Alteraciones

| Tabla | Cambio |
|---|---|
| `exclusiones` | + `canal` varchar(10) NOT NULL server_default `'todos'`, CHECK in (`todos`,`voz`,`whatsapp`); + `origen` varchar(10) NOT NULL server_default `'usuario'`, CHECK in (`usuario`,`sistema`,`agente_ia`); `creado_por` pasa a NULL con CHECK `origen <> 'usuario' OR creado_por IS NOT NULL`; + `conversacion_id` FK conversaciones.id NULL (opt-out desde una conversación); se **reemplaza** la UNIQUE (`numero_e164`,`aplica_a`) por UNIQUE (`numero_e164`,`aplica_a`,`canal`). Las filas existentes quedan `canal='todos'`, `origen='usuario'`. |
| `campanas` | + `whatsapp_habilitado` boolean NOT NULL server_default false; + `plantilla_inicial_id` FK plantillas_whatsapp.id NULL (sugerida en la ficha; la usará 2D). |
| `tipificaciones` | + `conversacion_id` FK conversaciones.id NULL, UNIQUE; CHECK `llamada_id IS NULL OR conversacion_id IS NULL`. |

Orden de `upgrade()`: `plantillas_whatsapp` → `campanas` (batch) → `conversaciones` → `mensajes` →
`eventos_mensaje` → `autorizaciones_canal` → `cola_atencion` → `exclusiones` (batch; el nombre de la
UNIQUE antigua sale de la convención de nombres de `0001`) → `tipificaciones` (batch) → `trabajos` →
`latidos_worker`. `downgrade()` en orden inverso; al bajar, las exclusiones con `canal<>'todos'` o
`creado_por IS NULL` se **borran** antes de restaurar la UNIQUE y el NOT NULL (documentado en el
docstring: el downgrade pierde opt-outs de WhatsApp).

### 3.3 Estados de la conversación y dueño (pensado para 2C)

Dos ejes independientes: **ciclo de vida** (`estado`: `abierta` → `cerrada`, irreversible; un mensaje
nuevo tras el cierre abre otra conversación) y **dueño** (`atendida_por` + `usuario_asignado_id`).

Toda transición de dueño pasa por **un único servicio**
`conversaciones.servicio.cambiar_dueno(db, conv, nuevo: Dueno, motivo_cola: str | None, actor_id: int | None, ahora)`
con `Dueno = SinAsignar | Humano(usuario_id) | IA` y reglas puras en `conversaciones/dueno.py`:

| desde \ hacia | `sin_asignar` | `humano` | `ia` |
|---|---|---|---|
| (apertura) | entrante sin IA (2B: siempre) | plantilla enviada por un agente | (2C) campaña con IA activa |
| `sin_asignar` | — | tomar, tomar siguiente, asignar | (2C) devolver a IA |
| `humano` | liberar, agente desconectado | asignar (reasignación) | (2C) devolver a IA |
| `ia` | (2C) `derivar_a_humano`, kill switch, presupuesto | (2C) tomar por A/S | — |

Efectos del servicio (en la misma transacción): actualiza la conversación; mantiene `cola_atencion`
(pasar a `sin_asignar` crea una fila `pendiente` con `motivo_cola`; pasar a `humano` marca la fila
activa `asignada` con `asignada_a`; pasar a `ia` o cerrar la conversación cierra la fila activa);
auditoría `conversacion.dueno` `{conversacion_id, de, a, motivo}`; eventos `conversacion.estado` y
`atencion.cola`. En 2B, `decidir_dueno_inicial(conv, campana)` devuelve siempre `SinAsignar` (o
`Humano` en el envío de plantilla por un agente); 2C solo cambia esa función y añade los disparadores
IA. El traspaso IA → humano de 2C es exactamente `cambiar_dueno(conv, SinAsignar, "solicitud_cliente", …)`.

### 3.4 Orden global de bloqueos (PostgreSQL)

Se amplía la regla B4 de 2A: **`estados_agente` → `clientes` → `conversaciones` → `cola_atencion` →
`mensajes`**. Ningún camino toma un bloqueo anterior en la lista después de uno posterior:
- Plantilla (consola o conversación): `clientes` (FOR UPDATE, serializa la frecuencia con la voz) →
  `conversaciones` (la abierta del número, si existe) → `mensajes`.
- Cerrar con tipificación: leer `cliente_id` sin bloqueo → `clientes` FOR UPDATE → `conversaciones`
  FOR UPDATE (revalidar que el cliente no cambió) → tipificación.
- Entrante (worker), estado (webhook), envío (worker), tomar, asignar, liberar, vincular:
  `conversaciones` → `cola_atencion` → `mensajes` (no bloquean `clientes`).
- Paso del agente a `desconectado`: `estados_agente` → `conversaciones` del agente.
- `tomar-siguiente`: `estados_agente` (FOR SHARE, comprueba `disponible`) → `cola_atencion` FOR UPDATE
  SKIP LOCKED → `conversaciones`. *Excepción documentada*: aquí la cola se bloquea antes que la
  conversación; es seguro porque la fila de cola se toma con SKIP LOCKED (nunca espera) y la
  conversación se actualiza con un UPDATE condicional `WHERE atendida_por='sin_asignar'`; si falla, se
  libera y se prueba la siguiente.

---

## 4. Contratos de API (2B)

Todo lo no mencionado mantiene `fase-1.md` §4 y `fase-2.md` §4. Prefijo `/api/v1`.

### 4.1 Convenciones nuevas

- **Números**: el agente ve `numero_mascara` (regla de 2A). Administrador/supervisor reciben además
  `numero_e164`; para el agente ese campo es `null`.
- **Texto de mensajes**: nunca en logs, eventos de tiempo real, payload de `trabajos` ni auditoría.
- **Webhooks de WhatsApp**: `application/x-www-form-urlencoded`, firma `X-Twilio-Signature` con la URL
  `PUBLIC_BASE_URL + ruta + query` (el fragmento `#rc=…` no se firma). Firma inválida → `403
  FIRMA_INVALIDA`. La validación pasa a `app/integraciones/twilio_webhook.py` y la usan voz y WhatsApp.
- **Idempotencia del cliente web**: los POST que envían mensajes aceptan `idempotencia_clave` (UUID v4,
  `crypto.randomUUID()`); repetirla devuelve el resultado existente con `200` si es del mismo usuario y
  conversación, o `409 IDEMPOTENCIA_CONFLICTO` si no.
- **Códigos de error nuevos**:

| HTTP | codigo | Cuándo |
|---|---|---|
| 403 | `CONVERSACION_NO_ASIGNADA` | el agente no es el dueño (o no puede verla/tomarla) |
| 409 | `CONVERSACION_ASIGNADA` | tomar/enviar plantilla a una conversación con otro dueño humano |
| 409 | `CONVERSACION_CERRADA` | operación sobre una conversación cerrada |
| 409 | `CONVERSACION_YA_VINCULADA` | vincular registro a una conversación que ya tiene uno |
| 409 | `CONVERSACION_ABIERTA_OTRO_REGISTRO` | plantilla a un número con conversación abierta de otro registro |
| 409 | `VENTANA_CERRADA` | texto libre con la ventana de 24 h cerrada (o a < margen de cerrarse) |
| 409 | `VENTANA_ABIERTA` | plantilla desde la consola con la ventana abierta (responder en la conversación) |
| 409 | `RESPUESTA_FUERA_DE_FRANJA` | respuesta retenible pero la próxima franja empieza después de que cierre la ventana |
| 409 | `CLIENTE_OPT_OUT` | texto libre tras un opt-out posterior al último mensaje del cliente |
| 409 | `WHATSAPP_NO_HABILITADO` | campaña sin `whatsapp_habilitado` o no `activa` (plantilla, vincular) |
| 409 | `CAPACIDAD_MAXIMA` | el agente ya tiene `ATENCION_MAX_CONVERSACIONES_AGENTE` abiertas |
| 409 | `AGENTE_NO_DISPONIBLE` | `tomar-siguiente`/`tomar` sin estar `disponible` |
| 409 | `IDEMPOTENCIA_CONFLICTO` | `idempotencia_clave` usada por otro usuario o conversación |
| 409 | `AUTORIZACION_DUPLICADA` | ya hay una autorización vigente igual |
| 422 | `PLANTILLA_NO_DISPONIBLE` | plantilla inexistente, no aprobada, inactiva o de otra finalidad |
| 422 | `PLANTILLA_VARIABLE_VACIA` | una variable mapeada no tiene valor para este registro |
| 422 | `PLANTILLA_MAPEO_INVALIDO` | mapeo incompleto o con campos fuera de la lista blanca |
| 422 | `PLANTILLA_SIN_BAJA` | activar una plantilla `marketing` sin botón de baja |
| 422 | `TELEFONO_NO_VALIDO` | teléfono de otro cliente o fijo para WhatsApp |
| 422 | `REGISTRO_NO_COINCIDE` | el registro a vincular no tiene el número de la conversación |
| 422 | `RESULTADO_INCOHERENTE` | (reutilizado) resultado imposible para la conversación |
| 413 | `MEDIA_DEMASIADO_GRANDE` | el medio supera `WHATSAPP_MEDIA_MAX_BYTES` |
| 404 | `MEDIA_NO_DISPONIBLE` | índice inexistente, categoría `no_soportado` o el proveedor no lo entrega |
| 502 | `PROVEEDOR_NO_DISPONIBLE` | fallo transitorio al descargar un medio o sincronizar plantillas |

- **Matriz de permisos** (A = administrador, S = supervisor, G = agente):

| Recurso | A | S | G |
|---|---|---|---|
| `/whatsapp/webhooks/*` | firma Twilio (sin JWT) | | |
| `GET /whatsapp/configuracion` | ✓ | ✓ | ✓ |
| `GET /whatsapp/plantillas` | ✓ | ✓ | ✓ (exige `campana_id` asignada; solo enviables) |
| `POST /whatsapp/plantillas/sincronizar` | ✓ | – | – |
| `PUT /whatsapp/plantillas/{id}` | ✓ | ✓ | – |
| `GET/POST /autorizaciones`, `DELETE /autorizaciones/{id}` | ✓ | ✓ | – |
| `GET /conversaciones` | ✓ todas | ✓ todas | ✓ solo con `usuario_asignado_id` = él |
| `GET /conversaciones/{id}` y `/mensajes`, `/ficha`, `/media` | ✓ | ✓ | ✓ solo dueño |
| `POST /conversaciones/{id}/mensajes`, `/plantillas`, `/leida`, `/opt-out`, `/autorizacion` | ✓ dueño | ✓ dueño | ✓ dueño |
| `POST /conversaciones/{id}/tomar` | ✓ | ✓ | ✓ (campaña asignada, `sin_asignar`) |
| `POST /conversaciones/{id}/asignar` | ✓ | ✓ | – |
| `POST /conversaciones/{id}/liberar`, `/cerrar` | ✓ | ✓ | ✓ dueño |
| `GET /conversaciones/{id}/registros-candidatos`, `PUT …/registro` | ✓ | ✓ | ✓ dueño (solo campañas asignadas) |
| `GET /atencion/cola` | ✓ todo | ✓ todo | ✓ campañas asignadas con WhatsApp (sin `sin_campana`) |
| `POST /atencion/tomar-siguiente` | – | – | ✓ |
| `POST /consola/registros/{id}/whatsapp/plantilla` | – | – | ✓ |
| `/whatsapp/simulacion/*` | ✓ | ✓ | ✓ (solo si está habilitada) |
| `GET /supervision/trabajos` | ✓ | ✓ | – |
| `GET /ws` | ✓ | ✓ | ✓ (eventos filtrados, §4.14) |

"Dueño" = `atendida_por='humano' AND usuario_asignado_id = yo`. A/S deben tomar o asignarse la
conversación para escribir en ella (no hay escritura "en nombre de").

### 4.2 Configuración visible (`GET /api/v1/whatsapp/configuracion`)
```json
{ "proveedor": "falso", "simulacion": true, "numero_empresa_mascara": "+57300****001",
  "margen_ventana_segundos": 60, "max_caracteres_texto": 4096,
  "max_conversaciones_agente": 5, "media_max_bytes": 16777216 }
```

### 4.3 Proveedor (`app/integraciones/whatsapp/proveedor.py`)

```python
CategoriaMedia = Literal["imagen", "audio", "documento", "no_soportado"]

@dataclass(frozen=True)
class MediaEntrante:
    indice: int
    url: str                      # URL del proveedor; NUNCA se envía al navegador
    tipo_contenido: str           # en minúsculas, sin parámetros (";codecs=opus" se descarta)

@dataclass(frozen=True)
class MensajeEntrante:
    proveedor_id: str             # MessageSid
    numero_cliente: str           # E.164 sin prefijo "whatsapp:"
    numero_empresa: str           # E.164
    cuenta: str | None            # AccountSid
    texto: str | None             # Body (recortado a 4096)
    nombre_perfil: str | None     # ProfileName (≤ 100)
    media: tuple[MediaEntrante, ...]
    boton_payload: str | None     # ButtonPayload
    boton_texto: str | None       # ButtonText
    respuesta_a: str | None       # OriginalRepliedMessageSid

@dataclass(frozen=True)
class EstadoMensaje:
    proveedor_id: str
    estado_proveedor: str         # valor crudo (MessageStatus)
    estado: Literal["enviado", "entregado", "leido", "fallido"] | None   # None = ignorar (p. ej. "receiving")
    error_codigo: str | None      # ErrorCode

@dataclass(frozen=True)
class EnvioResultado:
    proveedor_id: str
    estado_proveedor: str

@dataclass(frozen=True)
class BotonPlantilla:
    tipo: Literal["respuesta_rapida", "url", "telefono", "otro"]
    texto: str
    payload: str | None

@dataclass(frozen=True)
class PlantillaRemota:
    ref: str                      # ContentSid
    nombre: str
    idioma: str
    categoria: str                # ya mapeada al catálogo de §3.1
    estado_aprobacion: str        # ya mapeado al catálogo de §3.1
    motivo_rechazo: str | None
    cuerpo: str
    variables: tuple[str, ...]
    botones: tuple[BotonPlantilla, ...]

class ErrorProveedorWhatsApp(Exception):
    def __init__(self, codigo: str, transitorio: bool) -> None: ...

class ProveedorWhatsApp(Protocol):
    nombre: Literal["twilio", "falso"]
    def enviar_texto(self, *, origen: str, destino: str, texto: str, url_estado: str) -> EnvioResultado: ...
    def enviar_plantilla(self, *, origen: str, destino: str, plantilla_ref: str,
                         variables: dict[str, str], url_estado: str) -> EnvioResultado: ...
    def listar_plantillas(self) -> list[PlantillaRemota]: ...
    def validar_firma(self, url: str, params: Mapping[str, str | Sequence[str]], firma: str | None) -> bool: ...
    def parsear_entrante(self, params: Mapping[str, str]) -> MensajeEntrante | None: ...   # None = inválido
    def parsear_estado(self, params: Mapping[str, str]) -> EstadoMensaje | None: ...
    def url_media_valida(self, url: str) -> bool: ...
    def descargar_media(self, url: str, max_bytes: int) -> tuple[str, bytes]: ...         # (tipo_contenido, bytes)
```

**Twilio** (`ProveedorWhatsAppTwilio`):
- Cliente `twilio.rest.Client(TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_ACCOUNT_SID)`.
- `enviar_texto` → `client.messages.create(from_="whatsapp:"+origen, to="whatsapp:"+destino,
  body=texto, status_callback=url_estado)`. `enviar_plantilla` → igual con `content_sid=plantilla_ref,
  content_variables=json.dumps(variables, ensure_ascii=False)` y sin `body`.
- Errores: `TwilioRestException` con `status` 429 o 503 → `transitorio=True`, `codigo=str(e.code or
  e.status)`; otro `TwilioRestException` → `transitorio=False`; `requests.ConnectTimeout` → transitorio
  (`CONEXION`); cualquier otro error de red (pudo enviarse) → `ErrorProveedorWhatsApp("ENVIO_INCIERTO",
  False)`.
- `listar_plantillas` → `client.content.v1.content_and_approvals.list()`: `cuerpo` = `body` del primer
  tipo con cuerpo (`twilio/text`, `twilio/quick-reply`, `twilio/call-to-action`, `twilio/card`);
  `variables` = claves de `variables` ordenadas numéricamente; botones de `actions` (`quick-reply`: `id`
  → `payload`); aprobación de `approval_requests` (WhatsApp): `approved→aprobada`,
  `pending|received|in_review→pendiente`, `rejected→rechazada`, `paused→pausada`,
  `disabled→deshabilitada`, otro → `desconocido`; categoría `MARKETING|UTILITY|AUTHENTICATION` en
  minúsculas, otra → `desconocida`. *(Verificar nombres exactos de campos contra la versión instalada
  del SDK al implementar; queda aislado en el adaptador.)*
- `parsear_entrante`: exige `MessageSid` no vacío y `From`/`To` con prefijo `whatsapp:` y E.164
  (`\+[1-9]\d{7,14}`); `NumMedia` 0..10, `MediaUrl{i}`/`MediaContentType{i}`.
- `parsear_estado` (mapa): `accepted|scheduled|queued|sending|sent → enviado`; `delivered →
  entregado`; `read → leido`; `failed|undelivered|canceled → fallido`; otro → `None`.
- `url_media_valida`: prefijo exacto
  `https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages/` (anti-SSRF).
- `descargar_media`: `httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=True,
  auth=(TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET))`, lectura en streaming abortando al superar
  `max_bytes` (`MEDIA_DEMASIADO_GRANDE`); 404/410 → `MEDIA_NO_DISPONIBLE`; timeout/5xx → transitorio
  (`PROVEEDOR_NO_DISPONIBLE`). httpx retira `Authorization` al redirigir a otro origen.

**Falso** (`ProveedorWhatsAppFalso`, estado en memoria del proceso, `reiniciar()` para tests):
- `enviar_*` devuelve `EnvioResultado("SMfalso" + hex32, "queued")` y añade a `enviados` un registro
  `{tipo, destino, texto|plantilla_ref, variables}`. Reglas deterministas por destino: termina en
  `0000` → `ErrorProveedorWhatsApp("63003", transitorio=False)`; termina en `9999` →
  `ErrorProveedorWhatsApp("429", transitorio=True)`.
- `listar_plantillas` devuelve 4 plantillas fijas: `HXfalso0001` "recordatorio_cobranza" (utility,
  aprobada, `Hola {{1}}, le escribimos de {{2}}. ¿Podemos conversar sobre su cuenta?`),
  `HXfalso0002` "oferta_venta" (marketing, aprobada, `Hola {{1}}, {{2}} tiene una oferta de
  {{3}} para usted.`, botón respuesta rápida `Darme de baja`/`BAJA`), `HXfalso0003` "seguimiento"
  (utility, pendiente, `Hola {{1}}, ¿pudo revisar nuestro mensaje?`), `HXfalso0004`
  "marketing_sin_baja" (marketing, aprobada, `Hola {{1}}, conozca nuestras novedades.`, sin botón).
- `validar_firma` = `twilio_firma.validar_firma(..., TWILIO_AUTH_TOKEN)` (igual que voz).
- `url_media_valida`: prefijo `https://media.falso.invalid/`; `descargar_media` devuelve bytes fijos
  según el tipo de la URL (`/image/png` → PNG 1×1, `/audio/ogg` → cabecera OGG, `/application/pdf` →
  PDF mínimo) y `MEDIA_DEMASIADO_GRANDE` si la URL contiene `/grande/`.

### 4.4 Webhooks de Twilio Messaging

**`POST /api/v1/whatsapp/webhooks/entrante`** (firma). Form usado: `MessageSid`, `AccountSid`, `From`,
`To`, `Body`, `ProfileName`, `WaId`, `NumMedia`, `MediaUrl{i}`, `MediaContentType{i}`, `ButtonPayload`,
`ButtonText`, `OriginalRepliedMessageSid`.

| # | Paso | Resultado |
|---|---|---|
| 1 | Firma | inválida → `403 FIRMA_INVALIDA` |
| 2 | `parsear_entrante` | `None` → `200` vacío, log `whatsapp.entrante_invalido` (sin parámetros) |
| 3 | `AccountSid == TWILIO_ACCOUNT_SID` (solo twilio) y `numero_empresa == WHATSAPP_NUMERO_EMPRESA` | si no → `200` vacío, log de advertencia |
| 4 | INSERT `mensajes` (`direccion=entrante`, `autor=cliente`, `estado=recibido`, `conversacion_id=NULL`, `tipo` según §4.5, `media` con `categoria`) + `encolar("whatsapp.procesar_entrante", {"mensaje_id": id}, clave_unica="entrante:<id>")`; commit | `MessageSid` duplicado (IntegrityError) → rollback y `200` (sin efectos) |
| 5 | Respuesta | `200` `application/xml`: `<?xml version="1.0" encoding="UTF-8"?><Response/>` |

Objetivo < 300 ms; sin llamadas externas. Configurar en Twilio el webhook entrante como
`{PUBLIC_BASE_URL}/api/v1/whatsapp/webhooks/entrante#rc=3&rp=ct,rt,5xx` (reintentos de Twilio; el
fragmento no se firma) — el paso 4 hace seguros los reintentos.

**`POST /api/v1/whatsapp/webhooks/estado`** (firma) → siempre `204` tras la firma. Form: `MessageSid`,
`MessageStatus`, `ErrorCode`.
1. `parsear_estado`; `None` → 204 sin efectos.
2. INSERT `eventos_mensaje` (`proveedor_id`, `estado_proveedor`, `error_codigo`); duplicado → 204 sin
   efectos.
3. Si existe `mensajes.proveedor_id = MessageSid`: bloquear conversación y mensaje (§3.4), fijar
   `eventos_mensaje.mensaje_id` y aplicar **orden monótono**: rango `enviando 0 < enviado 1 <
   entregado 2 < leido 3`; `fallido` solo se aplica si el estado actual es `< entregado`. Un estado de
   rango menor o igual no cambia nada (se guarda el evento). Marca de tiempo correspondiente
   (`enviado_en`, `entregado_en`, `leido_en`); `fallido` guarda `error_codigo`. Evento
   `conversacion.mensaje` (`accion:"estado"`) si cambió.
4. Si no existe aún (el estado llegó antes de que el worker guardara el SID): queda con
   `mensaje_id=NULL`; el worker, al guardar el SID (§4.6), aplica en orden todos los eventos
   pendientes de ese `proveedor_id`.

### 4.5 Procesamiento del entrante (trabajo `whatsapp.procesar_entrante`)

`tipo` del mensaje (al guardar): `boton` si hay `ButtonPayload`; si no, `media` si `NumMedia > 0` (el
`Body` es el pie de foto); si no, `texto` si hay `Body` no vacío; si no, `no_soportado` (ubicación,
contacto, reacción…, `cuerpo=NULL`).

Categorías de medio (`medios.categoria`, puro):

| categoria | tipos de contenido aceptados |
|---|---|
| `imagen` | `image/jpeg`, `image/png`, `image/webp` |
| `audio` | `audio/ogg`, `audio/mpeg`, `audio/mp4`, `audio/aac`, `audio/amr` |
| `documento` | `application/pdf` |
| `no_soportado` | todo lo demás (vídeo, vCard, office, `image/svg+xml`…): se guarda el tipo, no hay descarga |

Pasos (una transacción, idempotente: si `mensaje.procesado_en` no es nulo, termina):
1. Buscar la conversación abierta por `clave_abierta = "<numero_cliente>|<numero_empresa>"` con
   `FOR UPDATE`. Si no existe, **crearla** en un SAVEPOINT (`estado=abierta`,
   `atendida_por=sin_asignar`, `iniciada_por=cliente`, `abierta_en=ultimo_mensaje_en=creado_en del
   mensaje`) y **resolver el contexto** (paso 2); si la UNIQUE falla, releer la abierta con
   `FOR UPDATE`.
2. **Resolución determinista** (`resolucion.py`), solo para conversaciones nuevas:
   1. Teléfonos con `numero_e164 = numero_cliente` **sin** exclusión `numero_errado` aplicable →
      clientes candidatos → registros (`campana_clientes`) de esos clientes en campañas `activa` con
      `whatsapp_habilitado`.
   2. Si en los últimos `WHATSAPP_DIAS_RESOLUCION_PLANTILLA` (30) hay un mensaje `tipo=plantilla`
      saliente no fallido a ese número cuyo registro está entre los candidatos → ese registro (el más
      reciente).
   3. Si no, si queda **exactamente un** candidato → ese.
   4. Si no (0 o varios) → sin registro: `cliente_id`, `campana_id`, `campana_cliente_id` nulos.
   Con registro: fija `cliente_id`, `campana_id`, `campana_cliente_id`, `telefono_id` (el teléfono del
   cliente con ese número) y registra `intentos_contacto` (`canal=whatsapp_mensaje`,
   `iniciado_por=cliente`, `contacto_directo = entrantes.establecen_contacto_directo` de la política
   del tipo, `momento = abierta_en`, `politica_version`) → `conversaciones.intento_contacto_id`.
3. Asociar el mensaje: `conversacion_id`, `procesado_en=ahora`. Actualizar la conversación:
   `ultimo_mensaje_en`, `ultimo_entrante_en = creado_en`, `ventana_expira_en = creado_en + 24 h`,
   `mensajes_sin_leer += 1`, `nombre_perfil` si viene.
4. Si la conversación es `iniciada_por=empresa`, es su **primer** entrante y tiene
   `intento_contacto_id` → ese intento pasa a `contacto_directo=true` (ADR-0011 §2).
5. **Opt-out determinista** (`opt_out.clasificar(texto, boton_payload, …)`, §4.10). Si clasifica →
   aplicar opt-out (§4.10) y terminar (no se encola a nadie).
6. **Enrutado**: si `atendida_por = humano` → nada (el dueño recibe el evento). Si `ia` (2C) → encolar
   `ia.turno` (no en 2B). Si `sin_asignar` y no hay fila activa en `cola_atencion` →
   `cambiar_dueno(SinAsignar, motivo = "sin_campana" si no hay registro, si no "entrante")`.
7. **Aviso de espera**: si la conversación acaba de entrar en cola, `aviso_espera_enviado_en` es nulo,
   `WHATSAPP_MENSAJE_ESPERA` no está vacío y **no hay ningún agente `disponible`** asignado a la
   campaña con WhatsApp (sin campaña: a ninguna campaña con WhatsApp) → mensaje automático (§4.6)
   y fijar `aviso_espera_enviado_en`.
8. Eventos: `conversacion.estado` si se creó; `conversacion.mensaje` (`accion:"nuevo"`); `atencion.cola`
   si entró en cola.

Un mensaje entrante **nunca** se rechaza por cumplimiento: el cliente siempre puede escribir.

### 4.6 Envío: texto, plantilla, automáticos y trabajo `whatsapp.enviar_mensaje`

**Ventana** (`ventana.py`, puro): `ventana_abierta(conv, ahora, margen) = conv.ventana_expira_en is not
None and ahora < conv.ventana_expira_en - margen` con `margen = WHATSAPP_MARGEN_VENTANA_SEGUNDOS`.

**`decidir_respuesta(ahora, politicas, festivos, ventana_expira_en, margen) ->
Enviar | Retener(programado_para) | Rechazar("RESPUESTA_FUERA_DE_FRANJA")`** (puro), para mensajes de
humano/IA dentro de la ventana:
- Si todas las `politicas` aplicables tienen `entrantes.responder_fuera_de_franja = true` → `Enviar`.
- Si no, `evaluar_contacto(ahora, "whatsapp_mensaje", politica, festivos, [], entrante=True)` (solo
  horario) para cada política; si todas permiten → `Enviar`.
- Si no, `t = max(proxima_ventana_inicio de cada política)`; si `t` es nulo o
  `t >= ventana_expira_en - margen` → `Rechazar`; si no → `Retener(t)`.
- Políticas aplicables: la del tipo de la campaña; **sin campaña, las dos activas** (más restrictivo).

**`POST /api/v1/conversaciones/{id}/mensajes`** (dueño)
```json
{ "texto": "Buenos días, le ayudo con gusto.", "idempotencia_clave": "8f0f1c6e-2b0a-4a7e-9a55-3f2a1d0c9b11" }
```
Validación en este orden: existe (404); dueño (403 `CONVERSACION_NO_ASIGNADA`); `idempotencia_clave`
repetida (→ 200 existente o 409 `IDEMPOTENCIA_CONFLICTO`); `texto` recortado 1..4096 (422 `VALIDACION`
campo `texto`); abierta (409 `CONVERSACION_CERRADA`); ventana (409 `VENTANA_CERRADA`); exclusión
`solicitud_titular` aplicable a WhatsApp (canal `whatsapp`|`todos`) con `creado_en >
ultimo_entrante_en` (409 `CLIENTE_OPT_OUT`); `decidir_respuesta` (`Rechazar` → 409
`RESPUESTA_FUERA_DE_FRANJA` con `detalles:[{"campo":"texto","mensaje":"La próxima franja (2026-10-26T07:00:00-05:00) empieza después de que cierre la ventana de 24 h. Use una plantilla."}]`).
Efectos: `mensajes` (`saliente`, `autor=agente`, `usuario_id`, `tipo=texto`, `estado=pendiente` o
`retenido` con `programado_para`), `encolar("whatsapp.enviar_mensaje", {"mensaje_id"},
clave_unica="enviar:<id>", disponible_desde = ahora o programado_para)`, conversación
`ultimo_mensaje_en`; si queda `retenido` y `aviso_fuera_franja_enviado_en` es nulo y
`WHATSAPP_MENSAJE_FUERA_DE_FRANJA` no está vacío → mensaje automático y se fija la marca. **No** crea
`intentos_contacto` ni consume frecuencia (ADR-0012 §3). Evento `conversacion.mensaje`. Respuesta
`202 Mensaje`.

**Plantilla** — servicio único `enviar_plantilla(db, *, usuario, campana_cliente, telefono, plantilla,
conversacion | None, idempotencia_clave, ahora)` usado por los dos endpoints:

- **`POST /api/v1/consola/registros/{id}/whatsapp/plantilla`** (G)
  ```json
  { "telefono_id": 21, "plantilla_id": 3, "idempotencia_clave": "0b6e5d1a-7c41-4f0e-8d0c-2f9b7e6a1c33" }
  ```
- **`POST /api/v1/conversaciones/{id}/plantillas`** (dueño; usa el registro y teléfono de la
  conversación; sin registro → 409 `WHATSAPP_NO_HABILITADO`)
  ```json
  { "plantilla_id": 3, "idempotencia_clave": "0b6e5d1a-7c41-4f0e-8d0c-2f9b7e6a1c33" }
  ```

Validación en este orden (errores 4xx; la primera decide):

| # | Comprobación | Error |
|---|---|---|
| 1 | Consola: registro existe (404), campaña asignada (403 `CAMPANA_NO_ASIGNADA`), reserva propia vigente (409 `REGISTRO_NO_RESERVADO`). Conversación: existe (404), dueño (403), abierta (409 `CONVERSACION_CERRADA`) | |
| 2 | `idempotencia_clave` repetida | 200 resultado existente / 409 `IDEMPOTENCIA_CONFLICTO` |
| 3 | Campaña `activa` y `whatsapp_habilitado` | 409 `WHATSAPP_NO_HABILITADO` |
| 4 | Teléfono del cliente del registro y `tipo_linea=movil` | 422 `TELEFONO_NO_VALIDO` |
| 5 | Plantilla `activa`, `aprobada`, finalidad `todas` o = tipo de campaña | 422 `PLANTILLA_NO_DISPONIBLE` |
| 6 | Valores de todas las variables no vacíos (§4.9) | 422 `PLANTILLA_VARIABLE_VACIA` (detalle `plantilla_id`: "Falta el valor de {{3}} (producto).") |
| 7 | Capacidad del agente (si la plantilla crea conversación nueva y el rol es agente) | 409 `CAPACIDAD_MAXIMA` |
| 8 | Bloquear `clientes` del cliente y la conversación abierta del número (§3.4). Consola: si hay abierta → con ventana abierta 409 `VENTANA_ABIERTA`; de otro dueño humano 409 `CONVERSACION_ASIGNADA`; de otro registro 409 `CONVERSACION_ABIERTA_OTRO_REGISTRO` | |

Después, **cumplimiento** (todos los motivos, en este orden) → si hay alguno, **no** es error:
`EXCLUIDO` (exclusión con `canal IN ('todos','whatsapp')` y `aplica_a IN (tipo,'todas')`),
`SIN_AUTORIZACION` (sin autorización vigente para la finalidad), y los de
`evaluar_para_cliente(db, cliente_id, tipo, "whatsapp_mensaje", ahora)` (`FESTIVO`, `DIA_SIN_FRANJA`,
`FUERA_DE_FRANJA`, `FRECUENCIA_DIA`, `FRECUENCIA_MEDIOS`).

Respuesta **`200 ResultadoEnvioPlantilla`**:
```json
{ "permitido": true, "motivos": [], "proxima_ventana_inicio": null, "politica_version": 1,
  "conversacion_id": 12, "mensaje": { "...": "Mensaje (estado pendiente)" } }
```
```json
{ "permitido": false,
  "motivos": [ { "codigo": "SIN_AUTORIZACION", "mensaje": "El número no tiene autorización vigente para WhatsApp (cobranza)." },
               { "codigo": "FUERA_DE_FRANJA", "mensaje": "…" } ],
  "proxima_ventana_inicio": "2026-10-26T07:00:00-05:00", "politica_version": 1,
  "conversacion_id": null, "mensaje": null }
```
- **Permitido** (misma transacción): conversación nueva si no había (`iniciada_por=empresa`,
  `atendida_por=humano`, `usuario_asignado_id=yo`, `ventana_expira_en=NULL`) o reutiliza la abierta
  (sin dueño humano → `cambiar_dueno(Humano(yo))`); `registrar_intento(canal=whatsapp_mensaje,
  iniciado_por=empresa, contacto_directo=false, politica_version)` → `conversaciones.intento_contacto_id`
  si era nueva; mensaje `tipo=plantilla`, `cuerpo` renderizado, `variables`, `estado=pendiente`;
  trabajo `whatsapp.enviar_mensaje`; consola: renueva la reserva y fija `ultima_gestion_en` (no toca
  `intentos`: cuenta al tipificar); auditoría `whatsapp.plantilla_enviada`
  `{mensaje_id, conversacion_id, plantilla_id, campana_cliente_id}`; eventos.
- **Bloqueado**: sin filas nuevas; auditoría `whatsapp.plantilla_bloqueada`
  `{campana_cliente_id, plantilla_id, codigos}`.

**Mensajes automáticos** (`autor=sistema`, `tipo=texto`): confirmación de opt-out, aviso de espera y
aviso de fuera de franja. Exentos de `decidir_respuesta` (son acuse inmediato de un mensaje del
cliente, ADR-0012 §3 / ADR-0019) pero exigen ventana abierta; no crean intentos; un texto de
configuración vacío los desactiva.

**Trabajo `whatsapp.enviar_mensaje` `{mensaje_id}`** (max_intentos 5):
1. Tx 1: bloquear conversación y mensaje. Si `estado` ∉ {`pendiente`,`retenido`} → terminar (si es
   `enviando`: un intento anterior murió a mitad → `fallido` con `ENVIO_INCIERTO`, sin reenviar).
   Conversación cerrada → `cancelado`, **salvo** `autor=sistema` con `motivo_cierre=opt_out` (la
   confirmación de baja sí se envía). Revalidar: texto → ventana abierta (si no, `fallido`
   `VENTANA_CERRADA`); texto de agente → opt-out posterior (`fallido` `CLIENTE_OPT_OUT`) y
   `decidir_respuesta` (si ahora toca retener → reprogramar el trabajo y terminar); plantilla →
   exclusión y autorización (si no, `fallido` `CONTACTO_NO_PERMITIDO`). Pasar a `enviando`; commit.
2. Llamada al proveedor (`url_estado = PUBLIC_BASE_URL + "/api/v1/whatsapp/webhooks/estado"`).
3. Tx 2: éxito → `proveedor_id`, `estado=enviado`, `enviado_en`, aplicar eventos pendientes de
   `eventos_mensaje` con ese SID (§4.4 paso 4); `ErrorProveedorWhatsApp(transitorio=True)` → volver a
   `pendiente` y relanzar `ErrorTrabajo(transitorio)`; no transitorio → `fallido` + `error_codigo`.
   Evento `conversacion.mensaje` (`accion:"estado"`).

### 4.7 Cola de trabajos y worker

```python
# app/trabajos/cola.py
def encolar(db: Session, tipo: str, payload: dict[str, Any], *, clave_unica: str | None = None,
            disponible_desde: datetime | None = None, max_intentos: int = 5) -> Trabajo: ...   # sin commit
def tomar(db: Session, trabajador: str, ahora: datetime, limite: int) -> list[Trabajo]: ...
def ejecutar(db_factory: Callable[[], Session], trabajo_id: int, reloj: Reloj) -> None: ...
def ejecutar_pendientes(db: Session, ahora: datetime | None = None, max_trabajos: int = 100) -> int: ...  # tests, síncrono
# app/trabajos/registro.py
class ErrorTrabajo(Exception):
    def __init__(self, codigo: str, transitorio: bool) -> None: ...
Manejador = Callable[[Session, dict[str, Any], datetime], None]
MANEJADORES: dict[str, Manejador]   # "whatsapp.procesar_entrante", "whatsapp.enviar_mensaje",
                                    # "conversaciones.cerrar_inactivas", "trabajos.purgar"
```
- `encolar` con `clave_unica` ya presente (pendiente) devuelve el existente (INSERT en SAVEPOINT +
  relectura).
- `tomar`: `SELECT … WHERE (estado='pendiente' AND disponible_desde <= :ahora) OR (estado='en_proceso'
  AND bloqueado_hasta < :ahora) ORDER BY disponible_desde, id LIMIT :n FOR UPDATE SKIP LOCKED`
  (PostgreSQL; en SQLite sin la cláusula) → `estado=en_proceso`, `intentos+1`,
  `bloqueado_hasta = ahora + WORKER_BLOQUEO_SEGUNDOS`, `bloqueado_por`, **`clave_unica=NULL`**; commit.
- Ejecución en una sesión nueva: el manejador trabaja sin commit (salvo los que confirman por fases,
  como el envío) y el worker marca `completado` + `completado_en` y confirma. Excepción → rollback;
  `ErrorTrabajo(transitorio=False)` o `intentos >= max_intentos` → `fallido` (auditoría
  `trabajo.fallido` `{trabajo_id, tipo, codigo}` y evento `trabajo.fallido`); si no → `pendiente`,
  `disponible_desde = ahora + min(5 s · 2^(intentos-1), 600 s)`. Excepciones no previstas cuentan como
  transitorias. `ultimo_error = f"{type(exc).__name__}:{codigo}"[:300]`.
- Periódicos (`periodicos.py`): en cada vuelta, si no hay trabajo pendiente con
  `clave_unica = "periodico:<tipo>"`, se encola con `disponible_desde` = siguiente ejecución:
  `conversaciones.cerrar_inactivas` cada 300 s; `trabajos.purgar` cada 24 h (borra `completado` con
  más de 7 días; `fallido` se conserva 30 días).
- **`python -m app.worker`**: id `"<hostname>-<pid>"`; bucle: latido (`latidos_worker` upsert) →
  programar periódicos → `tomar(WORKER_LOTE)` → ejecutar en serie → si no hubo trabajo, dormir
  `WORKER_INTERVALO_SEGUNDOS`. `SIGTERM`/`SIGINT`: termina el trabajo en curso y sale con 0. Usa el
  mismo `Settings`, `logging_seguro.instalar()` y `bus.crear_bus()` (con PostgreSQL publica con
  `pg_notify` y la API lo reenvía; con SQLite el bus en memoria del worker no llega a la API: en
  desarrollo con SQLite no hay tiempo real desde el worker — documentado).
- **`python -m app.worker --healthcheck`**: sale 0 si existe un latido con `ultimo_latido >= ahora −
  60 s`, 1 si no.
- **`conversaciones.cerrar_inactivas`**: cierra (`motivo_cierre=inactividad`, cola cerrada, mensajes
  `pendiente`/`retenido` → `cancelado`) las abiertas con
  `ahora >= max(COALESCE(ventana_expira_en, abierta_en), ultimo_mensaje_en + CONVERSACION_INACTIVIDAD_HORAS)`.
  No crea tipificación (el registro queda como esté). Lotes de 200.

**`GET /api/v1/supervision/trabajos`** (A, S) → `200`:
```json
{ "trabajadores": [ { "trabajador": "worker-7f3a-12", "ultimo_latido": "2026-10-24T15:00:05Z", "activo": true } ],
  "por_estado": [ { "tipo": "whatsapp.enviar_mensaje", "estado": "pendiente", "total": 3 } ],
  "fallidos_recientes": [ { "id": 88, "tipo": "whatsapp.enviar_mensaje", "ultimo_error": "ErrorTrabajo:63003",
                            "intentos": 1, "actualizado_en": "2026-10-24T14:58:00Z" } ] }
```
`activo` = latido de hace ≤ 60 s; `fallidos_recientes`: últimos 20 de 24 h.

### 4.8 Conversaciones y bandeja

Objeto **`ConversacionResumen`**:
```json
{ "id": 12, "estado": "abierta", "atendida_por": "humano",
  "usuario_asignado": { "id": 5, "nombre": "Pedro Agente" },
  "numero_mascara": "+57300****567", "numero_e164": null, "nombre_perfil": "María",
  "campana": { "id": 1, "nombre": "Cobranza cartera octubre", "tipo": "cobranza" },
  "cliente_nombre": "María Pérez", "iniciada_por": "cliente",
  "ventana_abierta": true, "ventana_expira_en": "2026-10-25T15:00:00Z",
  "ultimo_mensaje_en": "2026-10-24T15:00:00Z", "mensajes_sin_leer": 2, "motivo_cola": null,
  "abierta_en": "2026-10-24T14:50:00Z", "cerrada_en": null, "motivo_cierre": null }
```
Objeto **`Conversacion`** = `ConversacionResumen` +
```json
{ "campana_cliente_id": 15, "cliente_id": 9, "telefono_id": 21, "tipificada": false,
  "puede_responder": true,
  "motivos_no_responder": [],
  "alertas": [ { "codigo": "EXCLUIDO_WHATSAPP", "mensaje": "El número tiene una exclusión para WhatsApp (rne)." } ] }
```
- `puede_responder` = dueño, abierta, ventana abierta y sin opt-out posterior; si no, `motivos_no_responder`
  con códigos `NO_ES_DUENO`, `CONVERSACION_CERRADA`, `VENTANA_CERRADA`, `CLIENTE_OPT_OUT`.
- `alertas`: `EXCLUIDO_WHATSAPP` (cualquier exclusión aplicable al canal), `SIN_AUTORIZACION`,
  `SIN_CAMPANA`, `VARIOS_REGISTROS` (había varios candidatos).
- `numero_e164` solo para A/S; `cliente_nombre` nulo sin cliente; `motivo_cola` = motivo de la fila
  activa de la cola.

Objeto **`Mensaje`**:
```json
{ "id": 101, "conversacion_id": 12, "direccion": "entrante", "autor": "cliente", "usuario": null,
  "tipo": "media", "cuerpo": "Le envío el comprobante",
  "plantilla": null,
  "media": [ { "indice": 0, "categoria": "imagen", "tipo_contenido": "image/jpeg", "disponible": true } ],
  "boton": null, "estado": "recibido", "error": null, "programado_para": null,
  "creado_en": "2026-10-24T15:00:00Z", "enviado_en": null, "entregado_en": null, "leido_en": null }
```
`usuario` = `{id, nombre}` si `autor=agente`; `plantilla` = `{id, nombre}`; `boton` =
`{payload, texto}`; `error` = `{codigo, mensaje}` con mensaje de catálogo (`63016` "Fuera de la ventana
de 24 h.", `63003` "El número no está disponible en WhatsApp.", `VENTANA_CERRADA`, `CLIENTE_OPT_OUT`,
`CONTACTO_NO_PERMITIDO`, `ENVIO_INCIERTO` "No se pudo confirmar el envío; revise antes de reenviar.",
otro → "Error del proveedor ({codigo})."). `disponible = categoria != "no_soportado"`.

**`GET /api/v1/conversaciones?estado=abierta&atendida_por=&campana_id=&sin_campana=&usuario_id=&page=&page_size=`**
→ paginado de `ConversacionResumen`; orden `ultimo_mensaje_en` desc, `id` desc. `estado` por defecto
`abierta`. G: filtro implícito `usuario_asignado_id = yo` (los parámetros `usuario_id`/`sin_campana`
se ignoran).

**`GET /api/v1/conversaciones/{id}`** → `200 Conversacion`; auditoría `conversacion.ver`.

**`GET /api/v1/conversaciones/{id}/mensajes?antes_de=<mensaje_id>&limite=50`** → `200`:
```json
{ "items": [ { "...": "Mensaje" } ], "hay_mas": true }
```
`limite` 1..100 (def. 50); `items` en orden ascendente por `id` (los `limite` anteriores a `antes_de`,
o los últimos si se omite).

**`POST /api/v1/conversaciones/{id}/leida`** (dueño) → `204`; `mensajes_sin_leer = 0`.

**`POST /api/v1/conversaciones/{id}/tomar`** → `200 Conversacion`. G: campaña asignada (403
`CAMPANA_NO_ASIGNADA`; sin campaña → 403 `CONVERSACION_NO_ASIGNADA`), estado `disponible` (409
`AGENTE_NO_DISPONIBLE`), capacidad (409 `CAPACIDAD_MAXIMA`). Abierta (409). Ya mía → 200 sin cambios.
`UPDATE conversaciones SET atendida_por='humano', usuario_asignado_id=:yo … WHERE id=:id AND
estado='abierta' AND atendida_por='sin_asignar'` (A/S en 2C también desde `ia`); 0 filas → 409
`CONVERSACION_ASIGNADA`. Vía `cambiar_dueno`; auditoría `conversacion.tomar`.

**`POST /api/v1/atencion/tomar-siguiente`** (G) → `200 Conversacion` o `204` si no hay. Mismas
comprobaciones de estado y capacidad. Elige la fila `pendiente` de `cola_atencion` de campañas
asignadas al agente, `activa` y con WhatsApp (nunca `sin_campana`), por `prioridad`, `creado_en`, `id`,
con `FOR UPDATE SKIP LOCKED`; aplica el UPDATE condicional de `tomar`; si falla, prueba la siguiente
(máx. 5).

**`POST /api/v1/conversaciones/{id}/asignar`** (A, S)
```json
{ "usuario_id": 6 }
```
Destino activo; si es agente: asignado a la campaña de la conversación (422 `VALIDACION` campo
`usuario_id` "El agente no está asignado a la campaña."; sin campaña → mismo 422 "Solo un supervisor o
administrador puede atender conversaciones sin campaña."). Desde `sin_asignar` o `humano` (y `ia` en
2C). No aplica el límite de capacidad. `200 Conversacion`; auditoría `conversacion.asignar`
`{conversacion_id, usuario_id}`; evento `conversacion.estado` con `usuario_anterior_id`.

**`POST /api/v1/conversaciones/{id}/liberar`** (dueño, A, S) → `200 Conversacion`;
`cambiar_dueno(SinAsignar, "liberada")`.

**Agente a `desconectado`** (manual o por inactividad de 2A): sus conversaciones abiertas →
`cambiar_dueno(SinAsignar, "agente_desconectado")` en la misma transacción. `pausa` no las libera.

**`GET /api/v1/atencion/cola?campana_id=&motivo=`** → `200 [ItemCola]` (orden `prioridad`, `creado_en`):
```json
[ { "id": 40, "conversacion_id": 12, "campana": { "id": 1, "nombre": "Cobranza cartera octubre" },
    "motivo": "entrante", "prioridad": 2, "resumen": null, "numero_mascara": "+57300****567",
    "creado_en": "2026-10-24T15:00:00Z", "espera_segundos": 95 } ]
```
Solo filas `pendiente`. `campana` nulo para `sin_campana` (solo A/S las ven).

**`GET /api/v1/conversaciones/{id}/registros-candidatos`** → `200`:
```json
[ { "campana_cliente_id": 15, "campana": { "id": 1, "nombre": "Cobranza cartera octubre", "tipo": "cobranza" },
    "cliente_nombre": "María Pérez", "estado": "pendiente" } ]
```
Registros de campañas `activa` con WhatsApp cuyo cliente tiene un teléfono con el número de la
conversación (sin exclusión `numero_errado`); G: solo campañas asignadas.

**`PUT /api/v1/conversaciones/{id}/registro`** `{ "campana_cliente_id": 15 }` → `200 Conversacion`.
Abierta (409); sin registro previo (409 `CONVERSACION_YA_VINCULADA`); el registro está entre los
candidatos (422 `REGISTRO_NO_COINCIDE`); G: campaña asignada (403). Fija `cliente_id`, `campana_id`,
`campana_cliente_id`, `telefono_id`; si `iniciada_por=cliente` registra el intento (como §4.5 paso 2
con `momento = abierta_en`); si estaba en cola con `sin_campana`, la fila se cierra y se abre otra
`entrante` (vía `cambiar_dueno`). Auditoría `conversacion.vincular`.

**`GET /api/v1/conversaciones/{id}/ficha`** (dueño, A, S) → `200 FichaCliente` (objeto de 2A,
`fase-2.md` §4.4, con `whatsapp` en cada teléfono, §4.13) del registro vinculado; sin registro → 404.
No exige reserva. Auditoría `consola.ficha_ver` con `{campana_cliente_id, conversacion_id}`.

**`POST /api/v1/conversaciones/{id}/cerrar`** (dueño, A, S)
```json
{ "tipificacion": { "resultado": "promesa_pago", "observacion": "Paga el viernes",
                    "contacto_directo": null, "promesa": { "monto": "250000.50", "fecha_pago": "2026-10-30" },
                    "venta": null, "volver_a_llamar_en": null } }
```
- Abierta (409 `CONVERSACION_CERRADA`). `tipificacion` **obligatoria** si hay `campana_cliente_id` y
  **prohibida** si no (422 `VALIDACION` campo `tipificacion`).
- Validación de la tipificación: la de `fase-2.md` §4.6 (campos condicionados, montos, fechas,
  `RESULTADO_NO_PERMITIDO`, `VOLVER_A_LLAMAR_FUERA_DE_FRANJA`), con esta **coherencia**: si la
  conversación tiene algún entrante → `resultado ≠ no_contesta`; si no tiene ninguno → `resultado =
  no_contesta` (si no, 422 `RESULTADO_INCOHERENTE`).
- Efectos: tabla de efectos de 2A (`efectos.py`) con `canal=whatsapp_mensaje`, `conversacion_id`,
  `llamada_id=NULL`, `origen=agente`, `usuario_id` = quien cierra; misma regla B2 de reservas (solo
  libera/cierra el registro si la reserva es suya o está libre); `numero_errado` crea la exclusión del
  número de la conversación (`aplica_a=todas`, `canal=todos`) si no existe; el intento de la
  conversación recibe `contacto_directo` y `resultado`; mensajes `pendiente`/`retenido` → `cancelado`;
  conversación `cerrada`, `motivo_cierre = agente` (G) o `supervisor` (A/S), `cerrada_por`; cola
  cerrada. Auditoría `conversacion.cerrar` y `tipificacion.crear`; eventos `conversacion.estado`,
  `consola.registro`.
- Respuesta `200`:
  ```json
  { "conversacion": { "...": "Conversacion" }, "tipificacion": { "...": "Tipificacion de 2A con conversacion_id" } }
  ```

`Tipificacion` (2A) añade `"conversacion_id": number | null`; el historial de la ficha muestra
`canal=whatsapp_mensaje`.

### 4.9 Plantillas

Lista blanca de variables (`plantillas_render.CAMPOS`), con valor calculado en servidor:

| campo | valor |
|---|---|
| `primer_nombre` | primera palabra de `clientes.nombre`, capitalizada |
| `empresa` | `EMPRESA_NOMBRE` |
| `agente` | primera palabra del nombre del usuario que envía |
| `producto` | `campana_clientes.producto` (vacío → `PLANTILLA_VARIABLE_VACIA`) |

Nunca montos, saldos, fechas de deuda ni documentos (el número puede no ser del titular).
`renderizar(cuerpo, valores)` sustituye `{{n}}` (tolera espacios), deja literal lo desconocido.

**`GET /api/v1/whatsapp/plantillas?campana_id=&enviables=`** → `200 [Plantilla]`. A/S: todas (o
filtradas). G: `campana_id` obligatorio y asignado (403 si no); solo enviables para el tipo de la
campaña.
```json
{ "id": 3, "content_sid": "HXfalso0001", "nombre": "recordatorio_cobranza", "idioma": "es",
  "categoria": "utility", "estado_aprobacion": "aprobada", "motivo_rechazo": null,
  "cuerpo": "Hola {{1}}, le escribimos de {{2}}. ¿Podemos conversar sobre su cuenta?",
  "variables": ["1", "2"], "botones": [], "tiene_boton_baja": false,
  "mapeo_variables": { "1": "primer_nombre", "2": "empresa" }, "finalidad": "cobranza",
  "activa": true, "enviable": true, "sincronizada_en": "2026-10-24T14:00:00Z" }
```
`enviable` = activa ∧ aprobada ∧ finalidad ∧ mapeo completo.

**`POST /api/v1/whatsapp/plantillas/sincronizar`** (A) → `200 { "creadas": 2, "actualizadas": 1,
"desactivadas": 0 }`. Upsert por `content_sid`. Si cambian `cuerpo` o `variables` de una existente →
se vacía `mapeo_variables` y `activa=false`. Las que ya no existen en remoto → `estado_aprobacion =
eliminada`, `activa=false`. Las que dejan de estar aprobadas → `activa=false`. Error transitorio del
proveedor → 502 `PROVEEDOR_NO_DISPONIBLE`. Auditoría `whatsapp.plantillas_sincronizar` con contadores.

**`PUT /api/v1/whatsapp/plantillas/{id}`** (A, S)
```json
{ "finalidad": "cobranza", "mapeo_variables": { "1": "primer_nombre", "2": "empresa" }, "activa": true }
```
Campos opcionales (`extra="forbid"`). Mapeo: claves = exactamente `variables`, valores en la lista
blanca (422 `PLANTILLA_MAPEO_INVALIDO` con detalle `mapeo_variables.<clave>`). `activa=true` exige
aprobada, finalidad y mapeo completo (422 `PLANTILLA_NO_DISPONIBLE`) y, si `categoria=marketing`,
`tiene_boton_baja` (422 `PLANTILLA_SIN_BAJA`). Auditoría `whatsapp.plantilla_actualizar`
`{plantilla_id, campos}`. `200 Plantilla`.

Campañas: `CampanaCrear`/`CampanaActualizar` aceptan `whatsapp_habilitado` (bool) y
`plantilla_inicial_id` (nulo o plantilla enviable compatible con el tipo, si no 422 `VALIDACION`);
`Campana` los devuelve.

### 4.10 Opt-in, opt-out y exclusiones por canal

**Exclusiones** (amplía Fase 1): `ExclusionCrear` + `"canal": "todos" | "voz" | "whatsapp"` (opcional,
def. `todos`); `Exclusion` + `canal`, `origen`, `creado_por` (nulo si sistema), `conversacion_id`;
`GET /exclusiones?canal=`; importación con campo de formulario `canal` (def. `todos`); duplicado =
mismo (`numero`, `aplica_a`, `canal`). **Aplicabilidad**: voz → `canal IN ('todos','voz')`; WhatsApp →
`canal IN ('todos','whatsapp')`; siempre `aplica_a IN (tipo, 'todas')`. Hay que actualizar todas las
consultas de 2A (`consola/servicio.exclusiones_de`, TwiML saliente, número errado).

**Opt-out determinista** (`opt_out.py`, puro):
```python
AlcanceOptOut = Literal["whatsapp", "todos"]
def normalizar(texto: str) -> str: ...
def clasificar(texto: str | None, boton_payload: str | None,
               frases_whatsapp: frozenset[str], frases_todos: frozenset[str],
               payload_baja: str) -> AlcanceOptOut | None: ...
```
- `normalizar`: NFKD y quitar marcas diacríticas; minúsculas; todo carácter que no sea `[a-z0-9]` →
  espacio (quita signos y emojis); colapsar espacios; recortar. Luego, repetidamente, quitar prefijos
  de cortesía `por favor`, `porfa`, `porfavor`, `hola`, `buenas`, `buenos dias`, `buenas tardes`,
  `buenas noches` y sufijos `por favor`, `porfa`, `gracias`, `muchas gracias`.
- `clasificar`: `boton_payload == payload_baja` → `"whatsapp"`. Si no, texto nulo o de más de 80
  caracteres → `None`; normalizado ∈ `frases_todos` → `"todos"`; ∈ `frases_whatsapp` → `"whatsapp"`;
  si no → `None`. Coincidencia **exacta** tras normalizar (nunca subcadena).
- Frases por defecto (se normalizan al cargar; configurables, separadas por `|`):
  - WhatsApp: `stop`, `parar`, `detener`, `baja`, `dar de baja`, `darme de baja`, `de baja`,
    `unsubscribe`, `no me escriban`, `no me escriban mas`, `no me escriba mas`, `no escriban mas`,
    `no mas mensajes`, `no quiero mas mensajes`, `no quiero recibir mas mensajes`,
    `no me envien mas mensajes`, `no envien mas mensajes`, `dejen de escribirme`,
    `no me vuelvan a escribir`.
  - Todos los canales: `no me contacten`, `no me contacten mas`, `no me vuelvan a contactar`,
    `no vuelvan a contactarme`, `no quiero que me contacten`, `no me llamen ni me escriban`,
    `no me llamen ni me escriban mas`.
  - Excluidas a propósito: `cancelar` (en Colombia "cancelar" es pagar), `no`, `salir`.

**Aplicar opt-out** (servicio único `aplicar_opt_out`, usado por el entrante y por el endpoint
manual): exclusión `motivo=solicitud_titular`, `aplica_a=todas`, `canal` = `whatsapp` o `todos`,
`origen=sistema` (determinista) o `usuario` (manual, `creado_por`), `conversacion_id` — si ya existe
una equivalente o más amplia (`todos`) no se duplica; revoca las autorizaciones vigentes de WhatsApp
del número (`motivo_revocacion=opt_out`); mensaje automático de confirmación
(`WHATSAPP_MENSAJE_OPT_OUT` o `WHATSAPP_MENSAJE_OPT_OUT_TODOS`); cancela salientes
`pendiente`/`retenido`; cierra la conversación (`motivo_cierre=opt_out`) y su cola **después** de
encolar la confirmación (el trabajo de envío la envía aunque la conversación esté cerrada, §4.6).
Auditoría `whatsapp.opt_out` `{conversacion_id, alcance, origen: "determinista" | "agente"}`; eventos.
Sin tipificación automática.

**`POST /api/v1/conversaciones/{id}/opt-out`** (dueño, A, S) `{ "alcance": "whatsapp" | "todos" }` →
`200 Conversacion` (cerrada). Para peticiones parafraseadas que no detecta la lista.

**Autorizaciones (opt-in)**. Objeto `Autorizacion`:
```json
{ "id": 7, "numero_mascara": "+57300****567", "numero_e164": "+573001234567", "canal": "whatsapp",
  "finalidad": "cobranza", "origen": "agente", "evidencia": "Formulario firmado F-123",
  "otorgada_en": "2026-10-24T15:00:00Z", "vigente": true, "revocada_en": null, "motivo_revocacion": null,
  "registrada_por": { "id": 2, "nombre": "Sara Supervisora" } }
```
- `GET /api/v1/autorizaciones?numero=&finalidad=&vigentes=true&page=&page_size=` (A, S) → paginado,
  orden `id` desc.
- `POST /api/v1/autorizaciones` (A, S)
  `{ "telefono": "3001234567", "finalidad": "cobranza", "evidencia": "Formulario firmado F-123", "otorgada_en": "2026-10-20T10:00:00-05:00" }`
  → `201 Autorizacion` (`origen=agente`). `otorgada_en` opcional (def. ahora), no futura;
  `evidencia` 5..500 (se recorta); duplicada vigente → 409 `AUTORIZACION_DUPLICADA`. Auditoría
  `autorizacion.crear` `{autorizacion_id, finalidad, origen}`.
- `POST /api/v1/conversaciones/{id}/autorizacion` (dueño)
  `{ "finalidad": "cobranza", "evidencia": "Cliente escribe en el chat que acepta mensajes por este medio" }`
  → `201 Autorizacion` para el número de la conversación, `origen=cliente`, `conversacion_id`,
  `registrada_por` = yo.
- `DELETE /api/v1/autorizaciones/{id}` (A, S) → `204`; `revocada_en`, `revocada_por`,
  `motivo_revocacion=manual`, `clave_vigente=NULL`; ya revocada → 204. Auditoría
  `autorizacion.revocar`.
- **Importación**: columnas opcionales `autoriza_whatsapp` (`si`/`sí`/`no`/vacío, sin distinguir
  mayúsculas) y `fecha_autorizacion_whatsapp` (`YYYY-MM-DD`, ≤ hoy). `si` + fecha válida → autorización
  `finalidad` = tipo de la campaña, `origen=importacion`, `importacion_id`,
  `evidencia="importacion:<id> fila <n>"`, `otorgada_en` = fecha a las 00:00 locales, para **cada
  teléfono móvil** de la fila (sin duplicar vigentes). `no` → revoca las vigentes de esa finalidad de
  esos móviles (`motivo_revocacion=importacion`). Valor inválido o `si` sin fecha válida → advertencia
  de fila `AUTORIZACION_WHATSAPP_INVALIDA` y se ignora. Los contadores van en la auditoría
  `importacion.autorizaciones` `{importacion_id, creadas, revocadas, ignoradas}`.

### 4.11 Medios (proxy)

**`GET /api/v1/conversaciones/{id}/mensajes/{mensaje_id}/media/{indice}`** (dueño, A, S):
1. Mensaje de la conversación (404), índice existente y categoría ≠ `no_soportado` (404
   `MEDIA_NO_DISPONIBLE`), `url_media_valida` (si no, 404 `MEDIA_NO_DISPONIBLE` + log de advertencia).
2. `descargar_media(url, WHATSAPP_MEDIA_MAX_BYTES)`; el tipo devuelto debe tener la misma categoría
   que el guardado (si no, 404 `MEDIA_NO_DISPONIBLE`). Errores: 413 `MEDIA_DEMASIADO_GRANDE`, 404, 502.
3. `200` con el binario y cabeceras: `Content-Type` = tipo guardado; `Content-Disposition: inline`
   (imagen, audio) o `attachment; filename="documento-<mensaje_id>-<indice>.pdf"`;
   `X-Content-Type-Options: nosniff`; `Cache-Control: private, no-store`;
   `Content-Security-Policy: sandbox; default-src 'none'`.
4. Auditoría `whatsapp.media_ver` `{conversacion_id, mensaje_id, indice}`.

No se almacena el binario (Twilio lo conserva con autenticación obligatoria; su borrado por retención
va en 2F). El navegador lo obtiene con `fetch` + Bearer y crea un `blob:` URL (no puede usar
`<img src>` con JWT).

### 4.12 Simulación (solo `WHATSAPP_PROVEEDOR=falso` y `ENTORNO != produccion`; si no, 404)

- **`POST /api/v1/whatsapp/simulacion/entrante`**
  ```json
  { "numero": "3001234567", "texto": "Hola", "nombre_perfil": "María",
    "media": [ { "tipo_contenido": "image/png" } ], "boton_payload": null, "boton_texto": null }
  ```
  `numero` normalizado a E.164 (422 si inválido); construye los parámetros de Twilio
  (`MessageSid="SMsim"+hex32`, `From="whatsapp:+57…"`, `To="whatsapp:"+WHATSAPP_NUMERO_EMPRESA`,
  `MediaUrl0="https://media.falso.invalid/<hex>/image/png"`…) y ejecuta **el mismo servicio** que el
  webhook (pasos 2-4) → `200 { "mensaje_id": 101, "proveedor_id": "SMsim…" }`. El procesamiento lo hace
  el worker (en tests, `ejecutar_pendientes`).
- **`POST /api/v1/whatsapp/simulacion/mensajes/{mensaje_id}/estado`**
  `{ "estado": "delivered" | "read" | "failed" | "undelivered", "error_codigo": "63016" }` → `204`;
  ejecuta el servicio del webhook de estado con el `proveedor_id` del mensaje (404 si no tiene).

### 4.13 Consola (cambios)

`TelefonoFicha` añade:
```json
"whatsapp": { "autorizado": true, "excluido": false, "enviable": false,
              "motivos": [ { "codigo": "FUERA_DE_FRANJA", "mensaje": "…" } ],
              "conversacion_abierta": { "id": 12, "atendida_por": "humano", "ventana_abierta": true } }
```
`null` si la campaña no tiene WhatsApp o el teléfono es fijo. `enviable` = sin motivos de
cumplimiento de plantilla (§4.6) ∧ sin conversación abierta con ventana abierta. La ficha de voz no
bloquea la llamada por una conversación abierta (solo informa; ver §7).

### 4.14 Tiempo real (WebSocket con tickets existente, sin cambios de protocolo)

| tipo | datos |
|---|---|
| `conversacion.mensaje` | `{ "conversacion_id": 12, "mensaje_id": 101, "campana_id": 1, "usuario_asignado_id": 5, "direccion": "entrante", "autor": "cliente", "estado": "recibido", "accion": "nuevo" \| "estado" }` |
| `conversacion.estado` | `{ "conversacion_id": 12, "campana_id": 1, "estado": "abierta", "atendida_por": "humano", "usuario_asignado_id": 5, "usuario_anterior_id": null, "motivo_cierre": null }` |
| `atencion.cola` | `{ "cola_id": 40, "conversacion_id": 12, "campana_id": 1, "motivo": "entrante", "accion": "encolada" \| "asignada" \| "cerrada" }` |
| `trabajo.fallido` | `{ "trabajo_id": 88, "tipo": "whatsapp.enviar_mensaje", "codigo": "63003" }` |

Reparto (`conexiones.debe_recibir`): A/S reciben todo. Agente: `conversacion.*` si
`usuario_asignado_id == yo` o `usuario_anterior_id == yo`; `atencion.cola` siempre (solo ids, como
`consola.registro`; el filtrado por campañas asignadas es el mismo pendiente de 2F);
`trabajo.fallido` nunca. Sin texto ni números en los eventos.

### 4.15 Tipos TypeScript (`frontend/src/api/tipos.ts`, añadidos y cambios)

```ts
export type CanalExclusion = 'todos' | 'voz' | 'whatsapp';
export type OrigenExclusion = 'usuario' | 'sistema' | 'agente_ia';
export type Finalidad = 'venta' | 'cobranza' | 'todas';
// Exclusion (Fase 1) añade: canal: CanalExclusion; origen: OrigenExclusion; creado_por: number | null; conversacion_id: number | null
// ExclusionCrear añade: canal?: CanalExclusion
// Campana añade: whatsapp_habilitado: boolean; plantilla_inicial_id: number | null
// Tipificacion añade: conversacion_id: number | null
// TelefonoFicha añade: whatsapp: WhatsAppTelefono | null

export type EstadoConversacion = 'abierta' | 'cerrada';
export type AtendidaPor = 'sin_asignar' | 'humano' | 'ia';
export type MotivoCierre = 'agente' | 'supervisor' | 'inactividad' | 'opt_out' | 'sistema';
export type MotivoCola =
  | 'entrante' | 'sin_campana' | 'liberada' | 'agente_desconectado' | 'supervisor' | 'solicitud_cliente' | 'queja'
  | 'ia_no_resuelve' | 'identidad_bloqueada' | 'ia_rechazo' | 'ia_max_tokens' | 'ia_iteraciones'
  | 'ia_stop_inesperado' | 'ia_monto_no_respaldado' | 'ia_error' | 'presupuesto_excedido' | 'ia_desactivada';
export type DireccionMensaje = 'entrante' | 'saliente';
export type AutorMensaje = 'cliente' | 'agente' | 'ia' | 'sistema';
export type TipoMensaje = 'texto' | 'plantilla' | 'media' | 'boton' | 'no_soportado';
export type EstadoMensaje =
  'recibido' | 'pendiente' | 'retenido' | 'enviando' | 'enviado' | 'entregado' | 'leido' | 'fallido' | 'cancelado';
export type CategoriaMedia = 'imagen' | 'audio' | 'documento' | 'no_soportado';
export type CodigoMotivoPlantilla = CodigoMotivoCumplimiento | 'EXCLUIDO' | 'SIN_AUTORIZACION';

export interface ConfiguracionWhatsApp {
  proveedor: 'twilio' | 'falso'; simulacion: boolean; numero_empresa_mascara: string;
  margen_ventana_segundos: number; max_caracteres_texto: number; max_conversaciones_agente: number; media_max_bytes: number;
}
export interface UsuarioRef { id: number; nombre: string }
export interface CampanaRef { id: number; nombre: string; tipo: TipoCampana }
export interface ConversacionResumen {
  id: number; estado: EstadoConversacion; atendida_por: AtendidaPor; usuario_asignado: UsuarioRef | null;
  numero_mascara: string; numero_e164: string | null; nombre_perfil: string | null;
  campana: CampanaRef | null; cliente_nombre: string | null; iniciada_por: 'empresa' | 'cliente';
  ventana_abierta: boolean; ventana_expira_en: string | null; ultimo_mensaje_en: string; mensajes_sin_leer: number;
  motivo_cola: MotivoCola | null; abierta_en: string; cerrada_en: string | null; motivo_cierre: MotivoCierre | null;
}
export interface Conversacion extends ConversacionResumen {
  campana_cliente_id: number | null; cliente_id: number | null; telefono_id: number | null; tipificada: boolean;
  puede_responder: boolean;
  motivos_no_responder: Motivo<'NO_ES_DUENO' | 'CONVERSACION_CERRADA' | 'VENTANA_CERRADA' | 'CLIENTE_OPT_OUT'>[];
  alertas: Motivo<'EXCLUIDO_WHATSAPP' | 'SIN_AUTORIZACION' | 'SIN_CAMPANA' | 'VARIOS_REGISTROS'>[];
}
export interface MediaMensaje { indice: number; categoria: CategoriaMedia; tipo_contenido: string; disponible: boolean }
export interface Mensaje {
  id: number; conversacion_id: number; direccion: DireccionMensaje; autor: AutorMensaje; usuario: UsuarioRef | null;
  tipo: TipoMensaje; cuerpo: string | null; plantilla: { id: number; nombre: string } | null; media: MediaMensaje[];
  boton: { payload: string; texto: string | null } | null; estado: EstadoMensaje;
  error: { codigo: string; mensaje: string } | null; programado_para: string | null;
  creado_en: string; enviado_en: string | null; entregado_en: string | null; leido_en: string | null;
}
export interface PaginaMensajes { items: Mensaje[]; hay_mas: boolean }
export interface MensajeTextoCrear { texto: string; idempotencia_clave: string }
export interface PlantillaEnvioCrear { plantilla_id: number; idempotencia_clave: string }
export interface PlantillaConsolaCrear extends PlantillaEnvioCrear { telefono_id: number }
export interface ResultadoEnvioPlantilla {
  permitido: boolean; motivos: Motivo<CodigoMotivoPlantilla>[]; proxima_ventana_inicio: string | null;
  politica_version: number; conversacion_id: number | null; mensaje: Mensaje | null;
}
export interface ItemCola {
  id: number; conversacion_id: number; campana: { id: number; nombre: string } | null; motivo: MotivoCola;
  prioridad: 1 | 2 | 3; resumen: string | null; numero_mascara: string; creado_en: string; espera_segundos: number;
}
export interface RegistroCandidato { campana_cliente_id: number; campana: CampanaRef; cliente_nombre: string; estado: CampanaCliente['estado'] }
export interface CierreConversacionCrear { tipificacion: Omit<TipificacionCrear, 'llamada_id'> | null }
export interface CierreConversacion { conversacion: Conversacion; tipificacion: Tipificacion | null }
export type CampoPlantilla = 'primer_nombre' | 'empresa' | 'agente' | 'producto';
export interface Plantilla {
  id: number; content_sid: string; nombre: string; idioma: string;
  categoria: 'marketing' | 'utility' | 'authentication' | 'desconocida';
  estado_aprobacion: 'aprobada' | 'pendiente' | 'rechazada' | 'pausada' | 'deshabilitada' | 'eliminada' | 'desconocido';
  motivo_rechazo: string | null; cuerpo: string; variables: string[];
  botones: { tipo: 'respuesta_rapida' | 'url' | 'telefono' | 'otro'; texto: string; payload: string | null }[];
  tiene_boton_baja: boolean; mapeo_variables: Record<string, CampoPlantilla>; finalidad: Finalidad | null;
  activa: boolean; enviable: boolean; sincronizada_en: string;
}
export interface PlantillaActualizar { finalidad?: Finalidad; mapeo_variables?: Record<string, CampoPlantilla>; activa?: boolean }
export interface ResultadoSincronizacion { creadas: number; actualizadas: number; desactivadas: number }
export interface Autorizacion {
  id: number; numero_mascara: string; numero_e164: string | null; canal: 'whatsapp'; finalidad: Finalidad;
  origen: 'importacion' | 'cliente' | 'agente' | 'agente_ia'; evidencia: string; otorgada_en: string;
  vigente: boolean; revocada_en: string | null; motivo_revocacion: 'opt_out' | 'manual' | 'importacion' | null;
  registrada_por: UsuarioRef | null;
}
export interface AutorizacionCrear { telefono: string; finalidad: Finalidad; evidencia: string; otorgada_en?: string }
export interface AutorizacionConversacionCrear { finalidad: Finalidad; evidencia: string }
export interface WhatsAppTelefono {
  autorizado: boolean; excluido: boolean; enviable: boolean; motivos: Motivo<CodigoMotivoPlantilla>[];
  conversacion_abierta: { id: number; atendida_por: AtendidaPor; ventana_abierta: boolean } | null;
}
export interface EstadoTrabajos {
  trabajadores: { trabajador: string; ultimo_latido: string; activo: boolean }[];
  por_estado: { tipo: string; estado: 'pendiente' | 'en_proceso' | 'completado' | 'fallido' | 'cancelado'; total: number }[];
  fallidos_recientes: { id: number; tipo: string; ultimo_error: string | null; intentos: number; actualizado_en: string }[];
}
export interface SimulacionEntrante {
  numero: string; texto?: string | null; nombre_perfil?: string | null;
  media?: { tipo_contenido: string }[]; boton_payload?: string | null; boton_texto?: string | null;
}

// EventoTiempoReal añade:
//  | { tipo: 'conversacion.mensaje'; datos: { conversacion_id: number; mensaje_id: number; campana_id: number | null;
//        usuario_asignado_id: number | null; direccion: DireccionMensaje; autor: AutorMensaje; estado: EstadoMensaje;
//        accion: 'nuevo' | 'estado' }; emitido_en: string }
//  | { tipo: 'conversacion.estado'; datos: { conversacion_id: number; campana_id: number | null; estado: EstadoConversacion;
//        atendida_por: AtendidaPor; usuario_asignado_id: number | null; usuario_anterior_id: number | null;
//        motivo_cierre: MotivoCierre | null }; emitido_en: string }
//  | { tipo: 'atencion.cola'; datos: { cola_id: number; conversacion_id: number; campana_id: number | null;
//        motivo: MotivoCola; accion: 'encolada' | 'asignada' | 'cerrada' }; emitido_en: string }
//  | { tipo: 'trabajo.fallido'; datos: { trabajo_id: number; tipo: string; codigo: string }; emitido_en: string }
```

---

## 5. Configuración y docker-compose

### 5.1 `.env.example` (añadidos)

```
# WhatsApp (2B)
WHATSAPP_PROVEEDOR=falso                  # falso | twilio
WHATSAPP_NUMERO_EMPRESA=+573000000001     # E.164 del sender de WhatsApp (obligatorio y real con twilio)
WHATSAPP_MARGEN_VENTANA_SEGUNDOS=60
WHATSAPP_MEDIA_MAX_BYTES=16777216
WHATSAPP_DIAS_RESOLUCION_PLANTILLA=30
WHATSAPP_PAYLOAD_BAJA=BAJA
WHATSAPP_FRASES_OPT_OUT=                  # vacío = lista por defecto (§4.10); separadas por |
WHATSAPP_FRASES_OPT_OUT_TODOS=
WHATSAPP_MENSAJE_OPT_OUT=Hemos registrado su solicitud. No le enviaremos más mensajes por WhatsApp.
WHATSAPP_MENSAJE_OPT_OUT_TODOS=Hemos registrado su solicitud. No volveremos a contactarle por ningún medio.
WHATSAPP_MENSAJE_ESPERA=Gracias por escribirnos. Un asesor le responderá en nuestro horario de atención.
WHATSAPP_MENSAJE_FUERA_DE_FRANJA=Recibimos su mensaje. Le responderemos dentro de nuestro horario de atención.
CONVERSACION_INACTIVIDAD_HORAS=24
ATENCION_MAX_CONVERSACIONES_AGENTE=5
# Worker (2B)
WORKER_INTERVALO_SEGUNDOS=1
WORKER_LOTE=10
WORKER_BLOQUEO_SEGUNDOS=300
```
Validación en `Settings`: `WHATSAPP_NUMERO_EMPRESA` E.164; `WHATSAPP_PROVEEDOR=twilio` exige
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET` y
`PUBLIC_BASE_URL` https (salvo `ENTORNO=test`); rangos: margen 0..3600, media 1 KiB..64 MiB,
inactividad 1..168 h, capacidad 1..50, intervalo 0.1..60 s, lote 1..100, bloqueo 30..3600 s. Mensajes
automáticos ≤ 1000 caracteres. La firma de los webhooks de WhatsApp usa el mismo `TWILIO_AUTH_TOKEN`
(misma regla de 2A: fuera de `test`/`desarrollo` no puede ser el de ejemplo).

Configuración en Twilio (documentar en `docs/whatsapp-twilio.md`): sender de WhatsApp → "Webhook URL
for incoming messages" `POST {PUBLIC_BASE_URL}/api/v1/whatsapp/webhooks/entrante#rc=3&rp=ct,rt,5xx`;
el callback de estado lo envía el backend en cada mensaje; autenticación HTTP de medios activada
("Enforce HTTP Auth on Media URLs" en cuentas antiguas; obligatoria en la API de medios actual).

### 5.2 docker-compose (deuda de 2A)

**Decisión: `env_file` común para `backend` y `worker`** (no lista explícita). La lista explícita fue
la causa de la deuda (ninguna variable de 2A llegó al contenedor) y volvería a quedarse atrás con
`WHATSAPP_*`, `WORKER_*` e `IA_*` (2C). `Settings` usa `extra="ignore"`, así que las variables ajenas
(`POSTGRES_*`, `VITE_*`) no molestan. `environment` solo fuerza lo que depende de la red de compose y
conserva la comprobación de `JWT_SECRETO`:

```yaml
x-backend-comun: &backend-comun
  build: ./backend
  env_file:
    - path: .env
      required: false            # Compose >= 2.24
  environment:
    DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-outbound}:${POSTGRES_PASSWORD:-outbound}@db:5432/${POSTGRES_DB:-outbound}
    JWT_SECRETO: ${JWT_SECRETO:?Defina JWT_SECRETO (>= 32 caracteres) en .env}
  volumes:
    - ./backend:/app

services:
  backend:
    <<: *backend-comun
    depends_on: { db: { condition: service_healthy } }
    command: >
      sh -c "alembic upgrade head &&
             python -m app.cli generar-festivos --desde 2025 --hasta 2028 &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    ports: ["8000:8000"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/salud', timeout=3)"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 60s
  worker:
    <<: *backend-comun
    depends_on: { backend: { condition: service_healthy } }   # migraciones aplicadas por backend
    command: python -m app.worker
    healthcheck:
      test: ["CMD", "python", "-m", "app.worker", "--healthcheck"]
      interval: 30s
      timeout: 5s
      retries: 3
```
`db` y `frontend` no cambian. Riesgo conocido: los comentarios en línea del `.env` (`VAR=valor  # …`)
los elimina el parser de Compose para valores sin comillas; se verifica en la aceptación con
`docker compose config`.

---

## 6. Tareas de la subfase 2B

### [backend]

**B21 — Configuración, dependencias y docker-compose.** Variables §5.1 con validación; `httpx` en
`pyproject` y `requirements.lock`; `.env.example`; `docker-compose.yml` según §5.2 (deuda de 2A).
*Acepta*: `ENTORNO=test` arranca sin variables de WhatsApp; `WHATSAPP_PROVEEDOR=twilio` sin
credenciales → error claro; `docker compose config` muestra en `backend` y `worker` las variables
`TELEFONIA_*`, `TWILIO_*`, `PUBLIC_BASE_URL`, `CONSOLA_*`, `PROMESA_MAX_DIAS`, `WS_REVALIDAR_SEGUNDOS`,
`BUS_EVENTOS`, `WHATSAPP_*`, `WORKER_*` sin el comentario en línea; `docker compose up` levanta
`worker` sano tras `backend`.

**B22 — Modelos y migración 0003.** §3.1-3.2, catálogos en `catalogos.py`.
*Acepta*: `upgrade head`, `downgrade 0002`, `upgrade head` en SQLite y PostgreSQL (marcador
`postgres`); `alembic check` sin diferencias; exclusiones existentes quedan `canal=todos`,
`origen=usuario`; datos de 2A intactos; los CHECK rechazan combinaciones inválidas (test por CHECK).

**B23 — Cola de trabajos y worker.** `app/trabajos/*`, `app/worker.py`, periódicos, latido,
`--healthcheck`, `GET /supervision/trabajos` (§4.7).
*Acepta*: deduplicación por `clave_unica` solo mientras pendiente; reintento con backoff exacto;
`fallido` al agotar intentos con auditoría y evento; recuperación de bloqueos caducados; SIGTERM
termina el trabajo en curso; `ejecutar_pendientes` ejecuta en orden; ningún payload contiene texto.

**B24 — Webhook común y proveedor WhatsApp.** Extraer `validar_peticion_twilio` a
`integraciones/twilio_webhook.py` (voz sigue pasando sus tests); `ProveedorWhatsApp` + Twilio + falso +
fábrica (§4.3).
*Acepta*: tests de 2A en verde sin cambios; parseo de entrante/estado con casos límite; Twilio probado
con `twilio` y `httpx.MockTransport` simulados (envío texto/plantilla, mapeo de errores, plantillas,
redirección sin `Authorization`, límite de bytes).

**B25 — Webhooks y entrante.** §4.4-4.5 (`servicio_entrante`, `servicio_estado`, `resolucion.py`).
*Acepta*: casos W1-W12 y R1-R8 de [qa].

**B26 — Conversaciones, dueño y bandeja.** `dueno.py`, `cambiar_dueno`, `atencion.py`, router §4.8
(listar, ver, mensajes, leída, tomar, tomar-siguiente, asignar, liberar, candidatos, vincular, ficha),
liberación al pasar a `desconectado`, cierre por inactividad.
*Acepta*: casos C1-C14 de [qa]; ninguna transición de dueño fuera de `cambiar_dueno` (test que busca
asignaciones directas a `atendida_por` en el código, salvo el servicio).

**B27 — Envío.** `ventana.py`, `servicio_envio.py`: texto, plantilla (consola y conversación),
automáticos, trabajo `whatsapp.enviar_mensaje` (§4.6).
*Acepta*: casos V1-V8 y E1-E12 de [qa]; la frecuencia ve los intentos de WhatsApp (una plantilla con
contacto directo limita la llamada de voz y viceversa).

**B28 — Plantillas y campañas.** `plantillas_render.py`, `servicio_plantillas.py`, router §4.9;
campos de campaña.
*Acepta*: casos T1-T8 de [qa].

**B29 — Opt-in, opt-out y exclusiones por canal.** `opt_out.py`, `aplicar_opt_out`, endpoints §4.10,
importación de autorizaciones, exclusiones con `canal` y **todas** las consultas de 2A actualizadas.
*Acepta*: tabla O1-O20 de [qa]; voz ignora exclusiones `canal=whatsapp` y respeta `todos`/`voz`;
número errado de voz sigue creando `canal=todos`.

**B30 — Cierre con tipificación.** Factorizar `consola/tipificacion.py` para reutilizar validación y
efectos con `conversacion_id` (§4.8 cerrar).
*Acepta*: casos K1-K8; tests de tipificación de 2A sin cambios.

**B31 — Medios.** `medios.py` y proxy §4.11. *Acepta*: casos M1-M7.

**B32 — Simulación, tiempo real y consola.** Router de simulación §4.12, eventos y reparto §4.14,
`TelefonoFicha.whatsapp` §4.13, `GET /whatsapp/configuracion`.
*Acepta*: simulación inexistente (404) con `produccion` o proveedor twilio; reparto por rol; ningún
evento contiene texto ni números (test que serializa todos los eventos emitidos en la suite de 2B y
busca `+57` y los textos usados).

**B33 — Auditoría y logs.** Acciones: `whatsapp.plantilla_enviada`, `whatsapp.plantilla_bloqueada`,
`whatsapp.plantillas_sincronizar`, `whatsapp.plantilla_actualizar`, `whatsapp.opt_out`,
`whatsapp.media_ver`, `conversacion.ver`, `conversacion.tomar`, `conversacion.asignar`,
`conversacion.dueno`, `conversacion.vincular`, `conversacion.cerrar`, `autorizacion.crear`,
`autorizacion.revocar`, `importacion.autorizaciones`, `trabajo.fallido`, `exclusion.crear` (con canal).
*Acepta*: ningún `detalle` con teléfonos, documentos, texto de mensajes ni evidencias; `caplog` de la
suite 2B sin textos de mensajes ni números completos.

### [frontend]

**F14 — Tipos, endpoints y tiempo real.** §4.15 en `tipos.ts`, `endpoints.ts`; manejo de los eventos
nuevos en `TiempoRealContext` (sin cambios en `conexion.ts`). Contador global de no leídos en el menú
("Bandeja (3)"), alimentado por `GET /conversaciones` y eventos.

**F15 — Bandeja** (`/bandeja`, todos los roles; entrada en el menú). Columna izquierda: cola de
atención (con "Tomar siguiente" para G, "Tomar"/"Asignar a…" para A/S, tiempo de espera en vivo) y
"Mis conversaciones" (G) / conversaciones con filtros (A/S). Vista central: historial con carga de
anteriores al hacer scroll arriba, burbujas por autor (cliente, agente, sistema, IA) con estado
(reloj, enviado, entregado, leído, fallido con mensaje, retenido con hora programada), adjuntos
(`AdjuntoMedia`: `fetch` con Bearer → `blob:`; imagen en miniatura, `<audio controls>`, PDF como
descarga; "Adjunto no soportado (tipo)"), banner de ventana (tiempo restante; cerrada → "Solo
plantillas"), alertas. Compositor: textarea con contador 4096, Enter envía / Mayús+Enter salto,
`idempotencia_clave` por intento de envío (se reutiliza en el reintento del mismo texto),
deshabilitado con el motivo de `motivos_no_responder`; selector de plantillas cuando la ventana está
cerrada con vista previa renderizada y motivos de bloqueo. Acciones: liberar, opt-out manual
(confirmación con alcance), registrar autorización (finalidad + evidencia), vincular registro
(candidatos), ver ficha (panel con `FichaCliente`), cerrar (reutiliza `FormularioTipificacion` en modo
conversación; sin registro, cerrar sin tipificación). Marca leída al abrir y al recibir mensajes con
la conversación visible. `aria-live="polite"` para mensajes nuevos.
*Acepta*: flujo con `fetch` y WebSocket simulados: entrante → aparece en cola → tomar siguiente →
responder → estado entregado por evento → cerrar con promesa; `VENTANA_CERRADA` muestra selector de
plantillas; plantilla bloqueada muestra motivos; nunca se muestra un E.164 completo a un agente; un
evento de otra conversación no altera la vista abierta.

**F16 — Consola: WhatsApp desde la ficha.** Insignia por teléfono (autorizado/excluido/conversación
abierta) y botón "Enviar plantilla" (deshabilitado si `!enviable`, con motivos); tras enviar, enlace a
la conversación en la bandeja. `FormularioTipificacion` reutilizable (`contexto: 'llamada' |
'conversacion'`; en conversación, `no_contesta` solo si no hubo entrantes, igual que el servidor).

**F17 — Plantillas, campañas, exclusiones y autorizaciones.** `/whatsapp/plantillas` (A/S): lista con
estado de aprobación, "Sincronizar" (A), edición de finalidad y mapeo (select por variable con la
lista blanca), activar con errores 422 por campo. Formulario de campaña: `whatsapp_habilitado` y
plantilla inicial. Exclusiones: columna, filtro y selector de `canal` en alta e importación.
`/autorizaciones` (A/S): búsqueda por número, alta, revocación.

**F18 — Simulador y estado del worker.** `/whatsapp/simulador` (visible solo si
`configuracion.simulacion`): enviar como cliente (número, texto, adjunto simulado, botón de baja) y
cambiar el estado de los salientes de una conversación. Tarjeta de estado del worker en supervisión
(A/S) con aviso si no hay trabajador activo.

### [qa]

Backend (`pytest`, sin Docker; reloj fijo vie 2026-10-23 10:00 -05:00 salvo indicación; política por
defecto; festivos 2026; `ProveedorWhatsAppFalso`; webhooks firmados con el helper de 2A; worker con
`ejecutar_pendientes`):

- **Opt-out** (`clasificar` con listas por defecto; esperado entre paréntesis):
  O1 `STOP` (whatsapp) · O2 `stop!!!` (whatsapp) · O3 `Stop 🙏` (whatsapp) · O4 `NO ME ESCRIBAN MÁS`
  (whatsapp) · O5 `Por favor no me escriban más, gracias.` (whatsapp) · O6 `Darme de baja` (whatsapp) ·
  O7 `no me contacten más` (todos) · O8 `No me llamen ni me escriban` (todos) · O9 `Buenos días, no me
  contacten` (todos) · O10 `quiero cancelar la deuda` (None) · O11 `cancelar` (None) · O12 `no`
  (None) · O13 `no me escriban mañana sino el lunes` (None) · O14 `¿Baja el precio?` (None) · O15
  `stopped` (None) · O16 texto de 81+ caracteres que contiene `stop` (None) · O17 `ButtonPayload=BAJA`
  con texto `Darme de baja` (whatsapp) · O18 `ButtonPayload=OTRO` con texto `hola` (None) · O19 lista
  configurada `WHATSAPP_FRASES_OPT_OUT=alto` → `ALTO.` (whatsapp) y `stop` (None) · O20 `None` (None).
- **Webhooks** (W): W1 firma inválida/ausente → 403 sin filas; W2 entrante válido → mensaje `recibido`
  sin conversación + trabajo; W3 mismo `MessageSid` dos veces → una fila, un trabajo, ambas 200; W4
  `To` de otro número → 200 sin filas; W5 `AccountSid` ajeno con proveedor twilio → 200 sin filas; W6
  `From` sin `whatsapp:` → 200 sin filas; W7 4 medios con tipos mezclados → categorías correctas
  (`video/mp4` → `no_soportado`); W8 estado `delivered` → `entregado`; W9 `read` y luego `delivered` →
  queda `leido`, dos eventos; W10 `failed` tras `delivered` → sigue `entregado`; W11 estado antes de que
  el worker guarde el SID (mensaje en `enviando`) → al completar el envío el mensaje queda `entregado`;
  W12 estado duplicado → un evento.
- **Resolución** (R): R1 número de un solo registro en campaña activa con WhatsApp → vinculada +
  intento `iniciado_por=cliente` con contacto directo; R2 dos registros (dos campañas) sin plantilla
  previa → sin registro, cola `sin_campana`, alerta `VARIOS_REGISTROS`; R3 dos registros y plantilla
  enviada hace 10 días desde uno → ese; R4 plantilla hace 31 días → como R2; R5 campaña sin
  `whatsapp_habilitado` o `pausada` → no cuenta; R6 número con exclusión `numero_errado` → sin
  registro; R7 número desconocido → sin registro; R8 segundo mensaje con conversación abierta → misma
  conversación sin repetir la resolución.
- **Ventana** (V): V1 entrante vie 10:00 → texto sáb 09:58 (margen 60 s) → 202; V2 texto sáb
  09:59:30 (a 30 s de expirar) → 409 `VENTANA_CERRADA`; V3 conversación abierta por plantilla sin
  respuesta → 409 `VENTANA_CERRADA`; V4 `responder_fuera_de_franja=false`, entrante vie 19:20 y
  respuesta vie 19:30 → 202 `retenido` con `programado_para=2026-10-24T08:00:00-05:00`; el trabajo no
  se ejecuta antes; con reloj sáb 08:00 se envía; V5 igual pero entrante sáb 15:20 y respuesta sáb
  15:30 → próxima franja lun 07:00 posterior al fin de la ventana → 409 `RESPUESTA_FUERA_DE_FRANJA`;
  V6 en el escenario V4 el aviso de fuera de franja se envía una sola vez aunque se retengan dos
  respuestas; V7 `responder_fuera_de_franja=true`, domingo 22:00 → 202 `pendiente`; V8 conversación
  sin campaña con política de venta `true` y de cobranza `false`, fuera de franja → `retenido`.
- **Envío** (E): E1 plantilla desde la consola permitida → conversación `humano` del agente, intento
  `empresa`, mensaje `pendiente`; al ejecutar el trabajo, `enviado` con SID; E2 sin autorización →
  `permitido=false` con `SIN_AUTORIZACION` y sin filas; E3 exclusión `canal=whatsapp` → `EXCLUIDO`; E4
  exclusión `canal=voz` → permitida; E5 domingo → `DIA_SIN_FRANJA` y `proxima_ventana_inicio`; E6
  llamada de voz con contacto directo hoy → `FRECUENCIA_DIA`; E7 plantilla el lunes respondida por el
  cliente (contacto directo) y llamada de voz el miércoles → la voz da `FRECUENCIA_MEDIOS`; E8 variable
  `producto` vacía → 422 `PLANTILLA_VARIABLE_VACIA`; E9 plantilla de venta en campaña de cobranza → 422
  `PLANTILLA_NO_DISPONIBLE`; E10 destino `…0000` → `fallido` `63003` sin reintentos; destino `…9999` →
  reintenta con backoff y queda `fallido` tras 5 intentos; E11 trabajo que encuentra el mensaje en
  `enviando` → `fallido` `ENVIO_INCIERTO` sin llamar al proveedor; E12 misma `idempotencia_clave` dos
  veces → un mensaje; de otro usuario → 409 `IDEMPOTENCIA_CONFLICTO`.
- **Conversaciones** (C): C1 tomar `sin_asignar` → dueño; C2 tomar una ajena → 409; C3 agente sin la
  campaña → 403; C4 agente en `pausa` → 409 `AGENTE_NO_DISPONIBLE`; C5 capacidad 5 → la sexta 409; C6
  tomar-siguiente respeta prioridad, antigüedad y campañas asignadas, y nunca da `sin_campana`; cola
  vacía → 204; C7 asignar por supervisor a agente sin la campaña → 422; C8 liberar → cola `liberada`;
  C9 agente pasa a `desconectado` (manual y por inactividad) → sus conversaciones a la cola; C10
  vincular registro candidato → intento creado y cola `entrante`; no candidato → 422; C11 G no ve
  conversaciones ajenas (403 en detalle, mensajes, media, ficha) ni las lista; C12 paginación de
  mensajes con `antes_de`/`hay_mas`; C13 cierre por inactividad a las 24 h del último mensaje, sin
  tipificación, cancela retenidos; C14 nuevo entrante tras el cierre → conversación nueva.
- **Cierre** (K): K1 promesa → tipificación `whatsapp_mensaje` con `conversacion_id`, registro
  `gestionado`, intento actualizado; K2 sin entrantes y `contactado` → 422 `RESULTADO_INCOHERENTE`; K3
  con entrantes y `no_contesta` → 422; K4 sin registro con tipificación → 422; sin registro sin
  tipificación → 200; K5 `numero_errado` → exclusión `todos`/`todas` del número; K6 registro reservado
  por otro agente de voz → tipificación anotada sin tocar su reserva (B2); K7 segunda vez → 409
  `CONVERSACION_CERRADA`; K8 `volver_a_llamar_en` en domingo → 422 con próxima ventana.
- **Opt-out en API**: `STOP` entrante → exclusión `solicitud_titular`/`whatsapp`/`todas`
  `origen=sistema`, autorizaciones revocadas, confirmación enviada, conversación cerrada `opt_out`,
  nada en cola; segundo `STOP` en una conversación nueva → sin exclusión duplicada; `no me contacten
  más` → `canal=todos` y la voz queda bloqueada (`EXCLUIDO`); tras el opt-out el cliente escribe
  "hola" → conversación nueva, el agente puede responder (exclusión anterior al entrante) pero la
  plantilla sigue bloqueada; opt-out manual por el agente.
- **Plantillas** (T): T1 sincronizar con el falso → 4 creadas; T2 resincronizar sin cambios → 0/0/0;
  T3 cambio de cuerpo remoto → mapeo vaciado y desactivada; T4 desaparece en remoto → `eliminada`; T5
  mapeo con `saldo_mora` → 422 `PLANTILLA_MAPEO_INVALIDO`; T6 activar pendiente → 422; T7 activar
  marketing sin baja → 422 `PLANTILLA_SIN_BAJA`; T8 G solo ve enviables de la finalidad de su campaña.
- **Autorizaciones**: alta, duplicada vigente → 409, revocación idempotente, nueva tras revocar;
  importación (`si`+fecha → una por móvil; `si` sin fecha → advertencia; `no` → revoca; fijo ignorado;
  mismo resultado en CSV y XLSX).
- **Medios** (M): M1 imagen → 200 con cabeceras de §4.11 y auditoría; M2 PDF → `attachment`; M3
  `no_soportado` → 404; M4 `/grande/` → 413; M5 URL fuera del prefijo → 404 y sin descarga; M6 G ajeno
  → 403; M7 Twilio con `MockTransport`: Basic Auth enviado a `api.twilio.com` y **no** en la
  redirección al CDN.
- **Worker** (unit): deduplicación por clave; backoff 5 s, 10 s, 20 s…, máx. 600 s; recuperación de
  bloqueo caducado; periódicos no duplicados.
- **WebSocket**: el agente recibe `conversacion.*` solo de las suyas (y la de reasignación como
  anterior); el supervisor recibe todo; ningún evento con texto.
- **Permisos**: matriz de §4.1 parametrizada (rol × endpoint nuevo).
- **Simulación**: flujo completo por API; 404 con `ENTORNO=produccion` o `WHATSAPP_PROVEEDOR=twilio`.
- **Migración**: `upgrade head` + `downgrade 0002` + `upgrade head` en SQLite con datos de 2A.
- **PostgreSQL 16 real** (marcador `postgres`, `TEST_DATABASE_URL`, hilos con sesiones propias y
  barrera):
  - P1 dos `tomar` simultáneos de la misma conversación → una 200 y una 409.
  - P2 dos agentes `tomar-siguiente` con una fila → una conversación y un 204; con dos filas → una cada
    uno (SKIP LOCKED, sin espera).
  - P3 dos workers sobre 50 trabajos → cada trabajo ejecutado exactamente una vez; un trabajo con
    bloqueo caducado lo recupera el otro.
  - P4 mismo webhook entrante (mismo `MessageSid`) en paralelo ×5 → una fila de mensaje y un trabajo.
  - P5 dos entrantes distintos de un número nuevo procesados a la vez → una sola conversación abierta
    con ambos mensajes.
  - P6 política con `max_contactos_dia=1` y `max_canales_semana=2`; intento de voz con contacto directo
    el lunes; el viernes, plantilla y TwiML saliente de voz simultáneos al mismo cliente → solo uno
    pasa y el otro obtiene `FRECUENCIA_DIA` (bloqueo de `clientes`).
  - P7 cierre de conversación y entrante simultáneos → sin interbloqueo; el entrante queda en la
    cerrada (si llegó antes) o abre otra.
  - P8 webhook de estado en paralelo con la Tx 2 del envío → estado final correcto (W11 con hilos).
  - P9 dos agentes envían plantilla al mismo número a la vez → una conversación; el segundo recibe 409
    `CONVERSACION_ASIGNADA`; nunca dos conversaciones abiertas.
  - P10 paso a `desconectado` simultáneo con `tomar` del mismo agente → estado coherente (la
    conversación queda en cola o la toma falla con `AGENTE_NO_DISPONIBLE`), sin interbloqueo.

Frontend (Vitest + Testing Library): bandeja (flujo F15 completo; ventana cerrada → plantillas;
motivos de bloqueo; contador de caracteres; reintento con la misma `idempotencia_clave`; reconexión
del WebSocket recarga la conversación abierta); `AdjuntoMedia` con `fetch` simulado (blob y
revocación de la URL al desmontar); plantillas (mapeo y 422 por campo); autorizaciones; exclusiones con
canal; ficha de consola con insignias y envío; simulador; formulario de tipificación en modo
conversación.

Prueba manual guiada (opcional, con credenciales; documentada por QA): mensaje real desde un móvil al
sender, respuesta en ventana, plantilla aprobada fuera de ventana, `STOP`, imagen y PDF entrantes,
estados `delivered`/`read`, firma válida a través del túnel.

Criterio global: `cd backend && pytest` (y `pytest -m postgres` con PostgreSQL 16) y
`cd frontend && npm test -- --run && npm run build && npm run lint` en verde; `docker compose up`
permite el flujo completo con el simulador y el worker.

### [docs]
- `README.md` raíz: novedades de 2B, cómo probar WhatsApp sin Twilio (simulador + worker) y con
  Twilio (sender, webhooks, túnel); servicio `worker`.
- `docs/whatsapp-twilio.md` (nuevo): sender y requisitos de Meta, webhook entrante con `#rc`, Content
  API y aprobación de plantillas (con botón de baja en marketing), autenticación de medios, firma,
  costes, solución de problemas (63016, 63003).
- `docs/bandeja-whatsapp.md` (nuevo): guía para agentes y supervisores (cola, tomar, ventana de 24 h,
  plantillas, opt-out, autorizaciones, cierre y tipificación, adjuntos).
- `docs/cumplimiento-frecuencia.md`: WhatsApp en la frecuencia, respuestas fuera de franja, opt-in,
  opt-out determinista (lista de frases y por qué se excluye "cancelar"), exclusiones por canal.
- `docs/importacion-csv.md`: columnas `autoriza_whatsapp`/`fecha_autorizacion_whatsapp`; `canal` en
  exclusiones.
- `docs/pendientes.md`: cerrar las deudas de §5 (docker-compose, ADR-0003/0017); añadir supuestos
  S-B1…S-B8 y preguntas de §7.
- `docs/arquitectura/README.md`: fila de ADR-0019 en el índice y enlace a `fase-2b.md`.
- `CHANGELOG.md` `[Unreleased]`: subfase 2B.

---

## 7. Riesgos y preguntas abiertas

### 7.1 Bloquean 2B
**Ninguna bloquea el desarrollo ni la verificación** (proveedor falso, simulador, reloj inyectable).
Supuestos adoptados, a confirmar por el orquestador con el usuario (cambio de coste bajo):

- **(S-B1)** Responder fuera de franja a quien escribe primero: **permitido por defecto**
  (`entrantes.responder_fuera_de_franja=true`), configurable por política; con `false` la respuesta
  se retiene hasta la próxima franja si cabe en la ventana, y si no se rechaza
  (`RESPUESTA_FUERA_DE_FRANJA`). Los **mensajes automáticos** (confirmación de opt-out, espera, aviso
  de fuera de franja) se envían siempre dentro de la ventana. Sin campaña: la política más
  restrictiva de las dos.
- **(S-B2)** El mensaje entrante autoriza a responder en esa conversación, no a enviar plantillas
  futuras (S-E2); las plantillas exigen autorización vigente de la finalidad.
- **(S-B3)** Opt-out por WhatsApp → `canal=whatsapp`, `aplica_a=todas`; frases de "no me contacten"
  → `canal=todos` (S-E3). Se revocan las autorizaciones. Un cliente con opt-out que vuelve a escribir
  puede recibir respuesta en esa conversación, no plantillas.
- **(S-B4)** Conversaciones `sin_campana` solo las atienden supervisores/administradores (vinculan o
  asignan); los agentes no ven números sin campaña.
- **(S-B5)** Capacidad de 5 conversaciones por agente; `tomar`/`tomar-siguiente` exigen
  `disponible`; `pausa` conserva las conversaciones y `desconectado` las devuelve a la cola.
- **(S-B6)** La plantilla no incrementa `intentos` del registro (se incrementa al tipificar el
  cierre); el cierre exige tipificación si hay registro; el cierre por inactividad no tipifica.
- **(S-B7)** Medios: solo imagen (jpeg/png/webp), audio (ogg/mpeg/mp4/aac/amr) y PDF, hasta 16 MiB,
  por proxy sin almacenar; sin medios salientes en 2B.
- **(S-B8)** Variables de plantilla solo de la lista blanca (`primer_nombre`, `empresa`, `agente`,
  `producto`); nunca montos.

### 7.2 No bloquean 2B

**Legales**: validar S-B1 (en especial los automáticos fuera de franja) y S-B3; si la Ley 2300 obliga
a respetar la franja también en respuestas, poner `responder_fuera_de_franja=false`. Evidencia válida
de opt-in (¿basta la columna de la base con fecha?). ¿El RNE excluye también las **respuestas** a
conversaciones iniciadas por el cliente? (hoy no las bloquea, solo las alerta). Conservación de los
medios en Twilio (retención en 2F).

**Negocio**: textos de los mensajes automáticos; capacidad por agente y SLA de la cola; si un agente
de voz debe poder llamar a un cliente con una conversación de WhatsApp abierta atendida por otro (hoy
la ficha lo **informa** sin bloquear; la frecuencia ya limita los contactos de la empresa); quién
aprueba y mapea plantillas.

**Técnicos**:
- Nombres exactos de campos de `content_and_approvals` y de la categoría/estado en la versión del SDK
  instalada → verificar en B24 (aislado en el adaptador).
- El estado `read` no siempre llega (privacidad del usuario); `failed` tras `delivered` se ignora.
- Envío "incierto" (red caída tras enviar): se prefiere no duplicar (`ENVIO_INCIERTO`) a reenviar.
- Con SQLite (desarrollo sin Docker) los eventos del worker no llegan al WebSocket de la API (bus en
  memoria por proceso); con PostgreSQL sí.
- `env_file` con `required: false` exige Docker Compose ≥ 2.24.
- Varias instancias de la API: el temporizador de desconexión sigue siendo por proceso (pendiente de
  2A), y ahora también devuelve conversaciones a la cola; resolver antes de escalar.
- Calidad del número y bloqueos por reportes de spam; coste por mensaje (Meta + US$0,005 Twilio).

### 7.3 Lo que 2B deja preparado para 2C (sin rehacer tablas)
- `conversaciones`: `atendida_por='ia'`, columnas de identidad, turnos, coste, modelo, esfuerzo,
  versión de prompt y aviso de IA (§3.1); `cambiar_dueno` y `decidir_dueno_inicial` como únicos puntos
  de cambio (§3.3).
- `mensajes.autor='ia'` y `procesado_ia_en` para "mensajes entrantes no procesados" del turno.
- `cola_atencion.motivo` con todos los motivos IA y `resumen`.
- `trabajos` genérico (`ia.turno` con `clave_unica="turno_ia:<conversacion_id>"`, liberada al tomarse:
  los mensajes que llegan durante un turno producen un turno posterior, debounce de ADR-0013).
- `exclusiones.origen='agente_ia'`, `autorizaciones_canal.origen='agente_ia'`,
  `tipificaciones.origen='agente_ia'` ya admitidos.
- Quedan para la migración `0004` solo tablas **nuevas** (`configuracion_ia_campana`, `ofertas_campana`,
  `promesa_cuotas`, `historial_ia`, `acciones_ia`, `uso_ia`, `instrucciones_supervisor`,
  `configuracion_global`), sin alterar tablas de 2B.

---

## 8. Revisión post-revisor 2B (cambios de contrato)

- **B1 — Plantillas y frecuencia (§4.6).** Toda plantilla permitida registra SIEMPRE su
  `intentos_contacto` (`canal=whatsapp_mensaje`, `iniciado_por=empresa`), también cuando reutiliza una
  conversación abierta. `conversaciones.intento_contacto_id` solo se fija si la conversación es nueva
  (o no tenía intento). Así cada plantilla cuenta para `FRECUENCIA_DIA`/`FRECUENCIA_MEDIOS` y la ve la voz.
- **S1 — Revalidación al enviar (§4.6, trabajo `whatsapp.enviar_mensaje`).** Para plantillas el
  trabajo revalida exclusión, autorización, plantilla enviable (activa, aprobada, finalidad, mapeo y, en
  marketing, botón de baja) **y franja/festivo** (`motor.evaluar_horario`). Si ya no se puede, el mensaje
  queda `fallido` sin llamar al proveedor, con `error_codigo` `CLIENTE_OPT_OUT` (exclusión
  `solicitud_titular`), `CONTACTO_NO_PERMITIDO` (otra exclusión o sin autorización),
  `PLANTILLA_NO_ENVIABLE` o `FUERA_DE_FRANJA`, y se emite `conversacion.mensaje` (`accion:"estado"`).
- **S7 — Auditoría de `conversacion.ver` (§4.8).** `GET /conversaciones/{id}` acepta el parámetro de
  query opcional `apertura` (booleano, por defecto `false`). **Solo con `apertura=true` se audita
  `conversacion.ver`.** El frontend debe enviar `GET /api/v1/conversaciones/{id}?apertura=true`
  **una única vez, al abrir la conversación en la bandeja**, y llamar SIN el parámetro en las
  recargas, los refrescos por eventos y la reconexión del WebSocket.
- **S3 — Proxy de medios (§4.11).** Máximo `WHATSAPP_MEDIA_CONCURRENCIA` (4) descargas simultáneas por
  proceso; excederlo responde `429 DEMASIADAS_DESCARGAS`. Duración total máxima de una descarga:
  `WHATSAPP_MEDIA_DURACION_SEGUNDOS` (30) → `502 PROVEEDOR_NO_DISPONIBLE`.
- **S4/S6 — Cola.** Un trabajo agotado por bloqueo caducado también ejecuta el gancho de agotamiento;
  el worker libera al arrancar sus propios `en_proceso`; el bloqueo se renueva al empezar cada trabajo
  del lote; los trabajos que vuelven a `pendiente` recuperan su `clave_unica`. `trabajos.purgar` borra
  además `latidos_worker` con más de 7 días e `eventos_mensaje` sin enlazar con más de
  `PURGA_EVENTOS_HUERFANOS_DIAS` (7); `GET /supervision/trabajos` solo lista workers con latido de la
  última hora.
- **S8.** Sincronizar desactiva (auditoría `whatsapp.plantilla_desactivada`) una plantilla activa que
  pasa a `marketing` sin botón de baja.
- **S9.** Opt-out: los patrones de voz ("no me llamen…") están siempre activos aunque haya listas
  configuradas; "no me contacten más por WhatsApp" → `whatsapp`; "no me contacten por ningún medio" →
  `todos`.
- **S10.** Crear una autorización con `otorgada_en` anterior a una revocación por `opt_out` del mismo
  número y finalidad → `409 AUTORIZACION_REVOCADA_POR_OPT_OUT`; en la importación se omite con la
  advertencia `AUTORIZACION_REVOCADA_POR_OPT_OUT` (cuenta como `ignoradas`).
- **S11.** Downgrade de `0003`: borra las exclusiones de canal `whatsapp`, convierte `voz` en `todos`,
  atribuye las del sistema al primer administrador (o primer usuario) y elimina duplicados; solo si no
  existe ningún usuario se borran las del sistema.
- **S2.** `vincular` bloquea `clientes` del candidato antes que la conversación (orden global §3.4).
- **S12.** Errores de conexión previos al envío (DNS, conexión rechazada) → `CONEXION` transitorio con
  reintento; el resto sigue siendo `ENVIO_INCIERTO`.

### 8.x Iteración 3 del revisor (regresión de S4)

- `liberar_propios` agota (gancho `AL_AGOTAR` y `fallido`) los trabajos con `intentos >= max_intentos`
  en lugar de devolverlos a la cola; `tomar` aplica también el límite a pendientes recuperados.
- `cola.ejecutar` recibe el nombre del worker y renueva el bloqueo con UPDATE condicional
  (`estado='en_proceso'` y `bloqueado_por=yo`); si otro worker retomó el trabajo, no lo ejecuta.
- El id del worker es `<host>-<pid>-<8 hex aleatorios>`. `liberar_propios` solo libera trabajos de
  instancias del mismo host sin latido reciente (< 60 s); al arrancar libera también los propios.
  Dos workers vivos nunca se liberan trabajos entre sí.
- El gancho `AL_AGOTAR` dentro de `tomar` corre en un savepoint; si falla se registra el tipo de
  error (sin datos personales) y el trabajo se marca `fallido` igualmente.
- `revocada_por_opt_out_posterior` considera también una `Exclusion` posterior por solicitud del
  titular (canal `todos` o `whatsapp`) del mismo número.
