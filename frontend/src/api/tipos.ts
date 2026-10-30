export type Rol = 'administrador' | 'supervisor' | 'agente';
export type TipoCampana = 'venta' | 'cobranza';
export type EstadoCampana = 'borrador' | 'activa' | 'pausada' | 'finalizada';
export type Severidad = 'error' | 'advertencia';
export type MotivoExclusion = 'rne' | 'solicitud_titular' | 'numero_errado' | 'manual';
export type AplicaA = 'venta' | 'cobranza' | 'todas';
export type DiaSemana = 'lunes'|'martes'|'miercoles'|'jueves'|'viernes'|'sabado'|'domingo';

export interface ErrorRespuesta { error: { codigo: string; mensaje: string; detalles: { campo: string | null; mensaje: string }[] } }
export interface Pagina<T> { items: T[]; total: number; page: number; page_size: number }

export interface Usuario { id: number; email: string; nombre: string; rol: Rol; activo: boolean; creado_en?: string; actualizado_en?: string }
export interface RespuestaLogin { access_token: string; token_type: 'bearer'; expires_in: number; usuario: Usuario }

export interface Campana {
  id: number; nombre: string; tipo: TipoCampana; descripcion: string | null; estado: EstadoCampana;
  fecha_inicio: string | null; fecha_fin: string | null; guion: string | null;
  max_intentos: number; intervalo_reintento_minutos: number; total_clientes: number;
  whatsapp_habilitado: boolean; plantilla_inicial_id: number | null;
  creado_por: number; creado_en: string; actualizado_en: string;
}
export type CampanaCrear = Pick<Campana, 'nombre' | 'tipo'> & Partial<Pick<Campana,
  'descripcion' | 'fecha_inicio' | 'fecha_fin' | 'guion' | 'max_intentos' | 'intervalo_reintento_minutos' |
  'whatsapp_habilitado' | 'plantilla_inicial_id'>>;
export type CampanaActualizar = Partial<Omit<CampanaCrear, 'tipo'> & { estado: EstadoCampana }>;

export interface ErrorImportacion { fila: number; campo: string | null; codigo: string; mensaje: string; severidad: Severidad }
export interface Importacion {
  id: number; campana_id: number; nombre_archivo: string; estado: 'completada' | 'fallida';
  total_filas: number; filas_importadas: number; filas_duplicadas: number; filas_invalidas: number; filas_excluidas: number;
  creado_por: number; creado_en: string; errores?: ErrorImportacion[]; errores_truncados?: boolean;
}
export interface Telefono { id: number; numero_e164: string; tipo_linea: 'movil' | 'fijo'; prioridad: number; excluido: boolean }
export interface CampanaCliente {
  id: number; estado: 'pendiente' | 'en_gestion' | 'gestionado' | 'descartado'; intentos: number;
  cliente: { id: number; tipo_documento: string; numero_documento: string; nombre: string; email: string | null; ciudad: string | null };
  telefonos: Telefono[];
  numero_obligacion: string | null; saldo_total: string | null; saldo_mora: string | null; dias_mora: number | null;
  fecha_vencimiento: string | null; producto: string | null; oferta: string | null;
  datos_adicionales: Record<string, string>; importacion_id: number | null; creado_en: string;
}
export type CanalExclusion = 'todos' | 'voz' | 'whatsapp';
export type OrigenExclusion = 'usuario' | 'sistema' | 'agente_ia';
export type Finalidad = 'venta' | 'cobranza' | 'todas';
export interface Exclusion {
  id: number; numero_e164: string; motivo: MotivoExclusion; aplica_a: AplicaA; observacion: string | null;
  creado_por: number | null; creado_en: string;
  canal: CanalExclusion; origen: OrigenExclusion; conversacion_id: number | null;
}
export interface ResultadoImportacionExclusiones { total_filas: number; creadas: number; duplicadas: number; invalidas: number; errores: ErrorImportacion[]; errores_truncados: boolean }

export interface Franja { inicio: string; fin: string }
export interface Politica { id: number; tipo_campana: TipoCampana; version: number; activa: boolean; configuracion: ConfiguracionPolitica; creado_por: number | null; creado_en: string }
export interface Festivo { id: number; fecha: string; nombre: string; origen: 'calculado' | 'manual'; activo: boolean }

// ---------------------------------------------------------------------------------------------
// Fase 2A (fase-2.md §4.11)
// ---------------------------------------------------------------------------------------------
export type Canal = 'voz' | 'whatsapp_mensaje' | 'whatsapp_llamada';
export type EstadoAgenteValor = 'desconectado' | 'disponible' | 'pausa' | 'en_llamada' | 'tipificando';
export type MotivoPausa = 'descanso' | 'almuerzo' | 'capacitacion' | 'reunion' | 'otro';
export type ResultadoTipificacion =
  'contactado' | 'no_contesta' | 'numero_errado' | 'promesa_pago' | 'venta' | 'rechazo' | 'volver_a_llamar';
export type OrigenGestion = 'agente' | 'agente_ia' | 'sistema';
export type EstadoLlamada =
  'iniciando' | 'sonando' | 'en_curso' | 'completada' | 'ocupado' | 'no_contesta' | 'fallida' | 'cancelada' | 'bloqueada';
export type CodigoMotivoCumplimiento =
  'FESTIVO' | 'DIA_SIN_FRANJA' | 'FUERA_DE_FRANJA' | 'FRECUENCIA_DIA' | 'FRECUENCIA_MEDIOS';
export type CodigoMotivoBloqueo = CodigoMotivoCumplimiento |
  'AGENTE_INVALIDO' | 'PARAMETROS_INVALIDOS' | 'TIPIFICACION_PENDIENTE' | 'AGENTE_NO_DISPONIBLE' |
  'CAMPANA_NO_ACTIVA' | 'CAMPANA_NO_ASIGNADA' | 'REGISTRO_NO_RESERVADO' | 'INTENTOS_AGOTADOS' | 'EXCLUIDO';
export interface Motivo<C extends string = string> { codigo: C; mensaje: string }

// Cumplimiento (reemplazan las definiciones de Fase 1)
export interface ConfiguracionPolitica {
  zona_horaria: string; franjas: Record<DiaSemana, Franja[]>; permitir_festivos: boolean;
  frecuencia: { max_contactos_dia: number; max_canales_semana: number; semana: 'calendario' | 'movil_7_dias';
                solo_tras_contacto_directo: boolean; contar_intentos_sin_contacto: boolean };
  entrantes: { responder_fuera_de_franja: boolean; establecen_contacto_directo: boolean };
}
export interface ResultadoEvaluacion {
  permitido: boolean; motivos: Motivo<CodigoMotivoCumplimiento>[];
  momento_local: string; proxima_ventana_inicio: string | null; politica_version: number;
}

export interface AgenteAsignado { usuario_id: number; nombre: string; email: string; activo: boolean; asignado_en: string }

export interface EstadoAgente {
  estado: EstadoAgenteValor; desde: string; motivo_pausa: MotivoPausa | null; llamada_id: number | null;
  tipificacion_pendiente: { llamada_id: number; campana_cliente_id: number } | null;
}
export interface CambioEstadoAgente { estado: 'disponible' | 'pausa' | 'desconectado'; motivo_pausa?: MotivoPausa | null }

export interface CampanaConsola { id: number; nombre: string; tipo: TipoCampana; pendientes: number }
export interface RegistroTrabajo {
  id: number; campana_id: number; campana_nombre: string; tipo_campana: TipoCampana; nombre_cliente: string;
  estado: CampanaCliente['estado']; intentos: number; max_intentos: number;
  ultimo_resultado: ResultadoTipificacion | null; ultima_gestion_en: string | null; proximo_intento_en: string | null;
  saldo_mora: string | null; dias_mora: number | null; producto: string | null; reservado_por_mi: boolean;
}
export interface TelefonoFicha {
  id: number; numero_mascara: string; tipo_linea: 'movil' | 'fijo'; prioridad: number;
  excluido: boolean; llamable: boolean; motivos: Motivo<CodigoMotivoCumplimiento | 'EXCLUIDO'>[];
  whatsapp: WhatsAppTelefono | null;
}
export interface PromesaPago {
  id: number; monto: string; fecha_pago: string; numero_cuotas: number; descuento_porcentaje: string;
  estado: 'vigente' | 'cumplida' | 'incumplida' | 'anulada';
}
export interface Venta { id: number; producto: string; valor: string; unidades: number }
export interface GestionHistorial {
  id: number; canal: Canal; origen: OrigenGestion; agente_nombre: string | null; resultado: ResultadoTipificacion;
  contacto_directo: boolean; observacion: string | null; creado_en: string;
  promesa: PromesaPago | null; venta: Venta | null; volver_a_llamar_en: string | null;
}
export interface FichaCliente {
  id: number; campana: { id: number; nombre: string; tipo: TipoCampana };
  estado: CampanaCliente['estado']; reservado_hasta: string | null; intentos: number; max_intentos: number;
  ultimo_resultado: ResultadoTipificacion | null; proximo_intento_en: string | null;
  cliente: CampanaCliente['cliente']; telefonos: TelefonoFicha[];
  numero_obligacion: string | null; saldo_total: string | null; saldo_mora: string | null; dias_mora: number | null;
  fecha_vencimiento: string | null; producto: string | null; oferta: string | null; datos_adicionales: Record<string, string>;
  guion: string | null; cumplimiento: ResultadoEvaluacion; historial: GestionHistorial[];
}

export interface TokenTelefonia { proveedor: 'twilio' | 'falso'; token: string; identity: string; expira_en: string }
export interface Llamada {
  id: number; campana_cliente_id: number; telefono_id: number; canal: 'voz' | 'whatsapp_llamada';
  direccion: 'saliente' | 'entrante'; estado: EstadoLlamada; motivos_bloqueo: Motivo<CodigoMotivoBloqueo>[];
  iniciada_en: string; contestada_en: string | null; finalizada_en: string | null; duracion_segundos: number | null;
  tipificada: boolean;
}
export interface ResultadoSimulacion { llamada_id: number | null; permitida: boolean; motivos: Motivo<CodigoMotivoBloqueo>[] }
export type EventoSimulacion =
  | { evento: 'contestada' }
  | { evento: 'finalizada'; resultado: 'completed' | 'busy' | 'no-answer' | 'failed' | 'canceled'; duracion_segundos?: number };

export interface TipificacionCrear {
  llamada_id: number; resultado: ResultadoTipificacion; observacion?: string | null; contacto_directo?: boolean | null;
  promesa?: { monto: string; fecha_pago: string } | null;
  venta?: { producto: string; valor: string } | null;
  volver_a_llamar_en?: string | null;
}
export interface Tipificacion {
  id: number; campana_cliente_id: number; llamada_id: number | null; conversacion_id: number | null;
  canal: Canal; origen: OrigenGestion;
  usuario_id: number | null; resultado: ResultadoTipificacion; contacto_directo: boolean; observacion: string | null;
  promesa: PromesaPago | null; venta: Venta | null; volver_a_llamar_en: string | null; creado_en: string;
  registro?: { estado: CampanaCliente['estado']; intentos: number; proximo_intento_en: string | null };
  cliente_nombre?: string; agente_nombre?: string | null;
}

export interface AgenteSupervision {
  usuario_id: number; nombre: string; estado: EstadoAgenteValor; desde: string; motivo_pausa: MotivoPausa | null;
  campanas: number[]; llamada: { id: number; estado: EstadoLlamada; campana_id: number; campana_nombre: string } | null;
}

export type EventoTiempoReal =
  | { tipo: 'conexion.lista'; datos: { usuario_id: number; rol: Rol }; emitido_en: string }
  | { tipo: 'pong'; datos: Record<string, never>; emitido_en: string }
  | { tipo: 'agente.estado'; datos: { usuario_id: number; estado: EstadoAgenteValor; desde: string; motivo_pausa: MotivoPausa | null; llamada_id: number | null }; emitido_en: string }
  | { tipo: 'llamada.estado'; datos: { llamada_id: number; usuario_id: number; campana_id: number; campana_cliente_id: number; estado: EstadoLlamada; motivos: Motivo<CodigoMotivoBloqueo>[] }; emitido_en: string }
  | { tipo: 'consola.registro'; datos: { campana_id: number; campana_cliente_id: number | null; accion: 'reservado' | 'liberado' | 'gestionado' | 'asignacion' }; emitido_en: string }
  | { tipo: 'conversacion.mensaje'; datos: { conversacion_id: number; mensaje_id: number; campana_id: number | null;
        usuario_asignado_id: number | null; direccion: DireccionMensaje; autor: AutorMensaje; estado: EstadoMensaje;
        accion: 'nuevo' | 'estado' }; emitido_en: string }
  | { tipo: 'conversacion.estado'; datos: { conversacion_id: number; campana_id: number | null; estado: EstadoConversacion;
        atendida_por: AtendidaPor; usuario_asignado_id: number | null; usuario_anterior_id: number | null;
        motivo_cierre: MotivoCierre | null }; emitido_en: string }
  | { tipo: 'atencion.cola'; datos: { cola_id: number; conversacion_id: number; campana_id: number | null;
        motivo: MotivoCola; accion: 'encolada' | 'asignada' | 'cerrada' }; emitido_en: string }
  | { tipo: 'trabajo.fallido'; datos: { trabajo_id: number; tipo: string; codigo: string }; emitido_en: string }
  | { tipo: 'ia.turno'; datos: { conversacion_id: number | null; llamada_id: number | null; campana_id: number;
        estado: 'en_curso' | 'completado' | 'derivado' | 'error' | 'sin_respuesta'; iteraciones: number }; emitido_en: string }
  | { tipo: 'ia.accion'; datos: { conversacion_id: number | null; llamada_id: number | null; campana_id: number; accion_id: number;
        herramienta: string; es_error: boolean; codigo_error: string | null }; emitido_en: string }
  | { tipo: 'ia.alerta'; datos: { tipo: TipoAlertaIA; nivel: 'aviso' | 'critico'; campana_id: number | null;
        conversacion_id: number | null }; emitido_en: string }
  | { tipo: 'ia.configuracion'; datos: { campana_id: number | null; activa: boolean; version: number | null;
        desactivada_motivo: MotivoDesactivacionIA | null }; emitido_en: string }
  | { tipo: 'ia.evaluacion'; datos: { evaluacion_id: number; estado: EstadoEvaluacionIA; aprobada: boolean | null }; emitido_en: string };

/** `POST /ws/ticket`: ticket de un solo uso; `expira_en` en segundos. */
export interface TicketWs { ticket: string; expira_en: number }

// ---------------------------------------------------------------------------------------------
// Fase 2B (fase-2b.md §4.15)
// ---------------------------------------------------------------------------------------------
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
  /** Fase 2C (fase-2c.md §6.7): `null` si la conversación nunca tuvo IA y su campaña no tiene IA activa. */
  ia: EstadoIAConversacion | null;
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

// ---------------------------------------------------------------------------------------------
// Fase 2C (fase-2c.md §6.11): agente IA, supervisión y evaluaciones
// ---------------------------------------------------------------------------------------------
export type EsfuerzoIA = 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export type Tratamiento = 'usted' | 'tu';
export type Periodicidad = 'unica' | 'semanal' | 'quincenal' | 'mensual';
export type MotivoDesactivacionIA = 'manual' | 'presupuesto' | 'errores';
export type CodigoRequisitoIA =
  | 'WHATSAPP_NO_HABILITADO' | 'SIN_CONFIGURACION' | 'REGLAS_INVALIDAS' | 'SIN_OFERTAS_ACTIVAS' | 'PRESUPUESTO_CERO'
  | 'SIN_AGENTES_ASIGNADOS' | 'EVALUACION_OFFLINE_PENDIENTE' | 'EVALUACION_ONLINE_PENDIENTE' | 'IA_GLOBAL_DESACTIVADA'
  | 'PROVEEDOR_FALSO_EN_PRODUCCION' | 'MODELO_SIN_PRECIO';
export type TipoAlertaIA =
  'presupuesto_campana' | 'presupuesto_conversacion' | 'errores' | 'kill_switch' | 'rechazo_modelo' | 'evaluacion_fallida';
export type EstadoEvaluacionIA = 'pendiente' | 'en_curso' | 'completada' | 'fallida';
export interface TramoCuotas { max_cuotas: number; descuento_max_pct: string }
export interface ReglasCobranza {
  base_descuento: 'saldo_mora' | 'saldo_total'; descuento_max_pct: string; descuento_max_pct_por_cuotas: TramoCuotas[];
  monto_minimo_promesa: string; monto_minimo_cuota: string; max_cuotas: number;
  plazo_max_dias_primer_pago: number; plazo_max_dias_total: number; periodicidades: Exclude<Periodicidad, 'unica'>[];
}
export interface ReglasVenta { max_unidades_por_venta: number; requiere_aceptacion_terminos: boolean }
export interface VerificacionIA { factores: 'numero_documento'[]; max_intentos: number }
export interface RequisitosActivacion { cumple: boolean; faltantes: Motivo<CodigoRequisitoIA>[] }
export interface ConfiguracionIA {
  campana_id: number; campana_tipo: TipoCampana; configurada: boolean; activa: boolean; version: number;
  modelo: string; esfuerzo: EsfuerzoIA; prompt_version: number; tratamiento: Tratamiento; instrucciones: string | null;
  verificacion: VerificacionIA; reglas: ReglasCobranza | ReglasVenta | null;
  presupuesto_usd_mensual: string; max_costo_conversacion_usd: string; max_turnos_conversacion: number;
  desactivada_motivo: MotivoDesactivacionIA | null; activada_en: string | null; desactivada_en: string | null;
  gasto_mes_usd: string; requisitos: RequisitosActivacion; actualizado_por: UsuarioRef | null; actualizado_en: string | null;
}
export interface ConfiguracionIAActualizar {
  version_esperada: number; modelo: string; esfuerzo: EsfuerzoIA; prompt_version: number; tratamiento: Tratamiento;
  instrucciones: string | null; verificacion: VerificacionIA; reglas: ReglasCobranza | ReglasVenta;
  presupuesto_usd_mensual: string; max_costo_conversacion_usd: string; max_turnos_conversacion: number;
}
export interface Oferta {
  id: number; campana_id: number; codigo: string; nombre: string; descripcion: string | null; precio: string;
  descuento_max_pct: string; max_unidades: number; condiciones: string | null; activa: boolean; actualizado_en: string;
}
export type OfertaCrear = Omit<Oferta, 'id' | 'campana_id' | 'actualizado_en' | 'activa'> & { activa?: boolean };
export type OfertaActualizar = Partial<Omit<OfertaCrear, 'codigo'>>;
export interface ConfiguracionGlobalIA {
  ia_activa: boolean; ia_habilitada_entorno: boolean; proveedor: 'falso' | 'anthropic'; modelos_permitidos: string[];
  esfuerzos: EsfuerzoIA[]; prompts: { chat: number[] }; exigir_evaluacion_online: boolean;
  actualizado_por: UsuarioRef | null; actualizado_en: string;
}
export interface GestionIA { resultado: ResultadoTipificacion; tipificacion_id: number }
export interface EstadoIAConversacion {
  identidad_verificada: boolean; turnos: number; costo_usd: string | null; modelo: string | null; gestion: GestionIA | null;
  aviso_enviado: boolean; ultimo_traspaso: { motivo: MotivoCola; resumen: string | null; creado_en: string } | null;
  puede_devolver_ia: boolean; motivos_no_devolver: Motivo<'CONVERSACION_CERRADA' | 'IA_NO_DISPONIBLE' | 'CLIENTE_OPT_OUT'>[];
}
export interface ConversacionIAResumen extends ConversacionResumen {
  ia: { identidad_verificada: boolean; turnos: number; costo_usd: string; modelo: string; gestion: GestionIA | null;
        ultima_accion: { herramienta: string; es_error: boolean; creado_en: string } | null;
        turno_en_curso: boolean; instrucciones_pendientes: number };
}
export type EfectoAccionIA = 'ninguno' | 'identidad' | 'tipificacion' | 'promesa' | 'venta' | 'seguimiento'
  | 'exclusion' | 'autorizacion' | 'derivacion' | 'cierre_pendiente';
export interface AccionIA {
  id: number; tool_use_id: string; herramienta: string; entrada: Record<string, unknown>;
  resultado: Record<string, unknown> | null; es_error: boolean; codigo_error: string | null; efecto: EfectoAccionIA;
  referencia: { tipo: string; id: number } | null; duracion_ms: number; creado_en: string;
}
export interface LlamadaModelo {
  id: number; iteracion: number; modelo: string; modelo_servido: string; stop_reason: string;
  input_tokens: number; output_tokens: number; cache_creation_input_tokens: number; cache_read_input_tokens: number;
  costo_usd: string; duracion_ms: number; request_id: string | null; creado_en: string;
}
export interface UsoIAConversacion {
  total: { llamadas: number; input_tokens: number; output_tokens: number; cache_creation_input_tokens: number;
           cache_read_input_tokens: number; costo_usd: string; tasa_cache: number | null };
  llamadas: LlamadaModelo[];
}
export interface Instruccion { id: number; conversacion_id: number; usuario: UsuarioRef; texto: string; creado_en: string; aplicada_en: string | null }
export interface MetricasIA {
  campana_id: number | null; desde: string; hasta: string; conversaciones: number; con_identidad_verificada: number;
  tasa_verificacion: number | null; acuerdos: { numero: number; monto_total: string }; ventas: { numero: number; valor_total: string };
  resultados: Partial<Record<ResultadoTipificacion, number>>; derivaciones: Partial<Record<MotivoCola, number>>;
  opt_outs: number; cerradas_por_ia: number; cerradas_por_inactividad: number; costo_usd: string; costo_por_acuerdo_usd: string | null;
  tokens: { entrada: number; salida: number; cache_escritura: number; cache_lectura: number }; tasa_cache: number | null;
  tiempo_respuesta_ms: { p50: number | null; p95: number | null }; errores: Record<string, number>; guardas: Record<string, number>;
}
export interface EvaluacionIA {
  id: number; modo: 'offline' | 'online'; canal: 'chat' | 'voz'; campana_id: number | null; modelo: string | null;
  esfuerzo: EsfuerzoIA | null; prompt_version: number; huella: string; patron_casos: string | null;
  estado: EstadoEvaluacionIA; aprobada: boolean | null;
  resumen: { total?: number; aprobados?: number; por_categoria?: Record<string, { total: number; aprobados: number }>;
             costo_usd?: string; tasa_cache?: number | null; duracion_ms?: number };
  casos: { id: string; categoria: string; aprobado: boolean; fallos: string[] }[];
  iniciada_por: UsuarioRef | null; creado_en: string; completada_en: string | null;
}
export interface EvaluacionCrear { modo: 'offline' | 'online'; canal: 'chat'; campana_id?: number; casos?: string }
