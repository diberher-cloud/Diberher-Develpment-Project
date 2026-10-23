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
export interface ConfiguracionPolitica {
  zona_horaria: string; franjas: Record<DiaSemana, Franja[]>; permitir_festivos: boolean;
  frecuencia: { max_contactos_dia: number; max_canales_semana: number; semana: 'calendario' | 'movil_7_dias'; solo_tras_contacto_directo: boolean };
}
export interface Politica { id: number; tipo_campana: TipoCampana; version: number; activa: boolean; configuracion: ConfiguracionPolitica; creado_por: number | null; creado_en: string }
export interface Festivo { id: number; fecha: string; nombre: string; origen: 'calculado' | 'manual'; activo: boolean }
export interface ResultadoEvaluacion {
  permitido: boolean; motivos: { codigo: 'FESTIVO' | 'DIA_SIN_FRANJA' | 'FUERA_DE_FRANJA'; mensaje: string }[];
  momento_local: string; proxima_ventana_inicio: string | null; politica_version: number;
}
