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
  creado_por: number; creado_en: string; actualizado_en: string;
}
export type CampanaCrear = Pick<Campana, 'nombre' | 'tipo'> & Partial<Pick<Campana,
  'descripcion' | 'fecha_inicio' | 'fecha_fin' | 'guion' | 'max_intentos' | 'intervalo_reintento_minutos'>>;
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
export interface Exclusion { id: number; numero_e164: string; motivo: MotivoExclusion; aplica_a: AplicaA; observacion: string | null; creado_por: number; creado_en: string }
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
  id: number; campana_cliente_id: number; llamada_id: number | null; canal: Canal; origen: OrigenGestion;
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
  | { tipo: 'consola.registro'; datos: { campana_id: number; campana_cliente_id: number | null; accion: 'reservado' | 'liberado' | 'gestionado' | 'asignacion' }; emitido_en: string };
