import type {
  AccionIA, ConfiguracionGlobalIA, ConfiguracionIA, ConversacionIAResumen, EstadoIAConversacion, EvaluacionIA, Instruccion,
  MetricasIA, Oferta, ReglasCobranza, UsoIAConversacion,
} from '../api/tipos';
import { haceMin } from './utilesWhatsApp';
import { resumen } from './utilesWhatsApp';
import { respuesta, type Manejador } from './utiles';

export const reglasCobranza = (o: Partial<ReglasCobranza> = {}): ReglasCobranza => ({
  base_descuento: 'saldo_mora', descuento_max_pct: '20.00',
  descuento_max_pct_por_cuotas: [{ max_cuotas: 1, descuento_max_pct: '20.00' }, { max_cuotas: 3, descuento_max_pct: '10.00' }],
  monto_minimo_promesa: '100000.00', monto_minimo_cuota: '50000.00', max_cuotas: 6, plazo_max_dias_primer_pago: 14,
  plazo_max_dias_total: 90, periodicidades: ['quincenal', 'mensual'], ...o,
});

export const configIA = (o: Partial<ConfiguracionIA> = {}): ConfiguracionIA => ({
  campana_id: 5, campana_tipo: 'cobranza', configurada: true, activa: false, version: 3, modelo: 'claude-opus-5-5', esfuerzo: 'medium',
  prompt_version: 1, tratamiento: 'usted', instrucciones: 'Si el cliente menciona desempleo, ofrezca 6 cuotas.',
  verificacion: { factores: ['numero_documento'], max_intentos: 3 }, reglas: reglasCobranza(),
  presupuesto_usd_mensual: '200.00', max_costo_conversacion_usd: '0.8000', max_turnos_conversacion: 30, desactivada_motivo: null,
  activada_en: null, desactivada_en: null, gasto_mes_usd: '50.000000',
  requisitos: { cumple: true, faltantes: [] }, actualizado_por: { id: 2, nombre: 'Sara Supervisora' }, actualizado_en: '2026-10-23T15:00:00Z', ...o,
});

export const configGlobal = (o: Partial<ConfiguracionGlobalIA> = {}): ConfiguracionGlobalIA => ({
  ia_activa: true, ia_habilitada_entorno: true, proveedor: 'falso',
  modelos_permitidos: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5'], esfuerzos: ['low', 'medium', 'high', 'xhigh', 'max'],
  prompts: { chat: [1] }, exigir_evaluacion_online: false, actualizado_por: null, actualizado_en: '2026-10-23T14:00:00Z', ...o,
});

export const oferta = (o: Partial<Oferta> = {}): Oferta => ({
  id: 4, campana_id: 5, codigo: 'SEG-HOGAR', nombre: 'Seguro hogar', descripcion: 'Cobertura de incendio y robo.', precio: '89900.00',
  descuento_max_pct: '10.00', max_unidades: 1, condiciones: 'Vigencia anual.', activa: true, actualizado_en: '2026-10-23T15:00:00Z', ...o,
});

export const estadoIA = (o: Partial<EstadoIAConversacion> = {}): EstadoIAConversacion => ({
  identidad_verificada: true, turnos: 4, costo_usd: '0.084213', modelo: 'claude-opus-5-5', gestion: null, aviso_enviado: true,
  ultimo_traspaso: null, puede_devolver_ia: true, motivos_no_devolver: [], ...o,
});

export const resumenIA = (o: Partial<ConversacionIAResumen['ia']> = {}, base: Parameters<typeof resumen>[0] = {}): ConversacionIAResumen => ({
  ...resumen({ atendida_por: 'ia', usuario_asignado: null, ...base }),
  ia: {
    identidad_verificada: true, turnos: 4, costo_usd: '0.084213', modelo: 'claude-opus-5-5', gestion: null,
    ultima_accion: { herramienta: 'verificar_identidad', es_error: false, creado_en: haceMin(1) }, turno_en_curso: false,
    instrucciones_pendientes: 0, ...o,
  },
});

export const accion = (o: Partial<AccionIA> = {}): AccionIA => ({
  id: 77, tool_use_id: 'toolu_01A', herramienta: 'verificar_identidad', entrada: { numero_documento: '***4050' },
  resultado: { verificada: true }, es_error: false, codigo_error: null, efecto: 'identidad', referencia: null, duracion_ms: 12,
  creado_en: haceMin(3), ...o,
});

export const uso = (o: Partial<UsoIAConversacion> = {}): UsoIAConversacion => ({
  total: { llamadas: 1, input_tokens: 310, output_tokens: 420, cache_creation_input_tokens: 5200, cache_read_input_tokens: 26000, costo_usd: '0.084213', tasa_cache: 0.93 },
  llamadas: [{
    id: 301, iteracion: 1, modelo: 'claude-opus-5-5', modelo_servido: 'claude-opus-5-5', stop_reason: 'tool_use', input_tokens: 310, output_tokens: 420,
    cache_creation_input_tokens: 5200, cache_read_input_tokens: 0, costo_usd: '0.040840', duracion_ms: 4210, request_id: 'req_1', creado_en: haceMin(3),
  }], ...o,
});

export const instruccion = (o: Partial<Instruccion> = {}): Instruccion => ({
  id: 9, conversacion_id: 12, usuario: { id: 2, nombre: 'Sara Supervisora' }, texto: 'Ofrézcale 6 cuotas si lo pide.', creado_en: haceMin(2), aplicada_en: null, ...o,
});

export const metricas = (o: Partial<MetricasIA> = {}): MetricasIA => ({
  campana_id: null, desde: '2026-10-23', hasta: '2026-10-23', conversaciones: 120, con_identidad_verificada: 84, tasa_verificacion: 0.7,
  acuerdos: { numero: 31, monto_total: '8420000.00' }, ventas: { numero: 0, valor_total: '0.00' }, resultados: { promesa_pago: 31 },
  derivaciones: { solicitud_cliente: 12, ia_no_resuelve: 4 }, opt_outs: 5, cerradas_por_ia: 70, cerradas_por_inactividad: 22,
  costo_usd: '18.402100', costo_por_acuerdo_usd: '0.593616', tokens: { entrada: 1, salida: 2, cache_escritura: 3, cache_lectura: 4 }, tasa_cache: 0.87,
  tiempo_respuesta_ms: { p50: 9200, p95: 21000 }, errores: { RATE_LIMIT: 3 }, guardas: { MONTO_NO_RESPALDADO: 2 }, ...o,
});

export const evaluacion = (o: Partial<EvaluacionIA> = {}): EvaluacionIA => ({
  id: 5, modo: 'offline', canal: 'chat', campana_id: null, modelo: null, esfuerzo: null, prompt_version: 1, huella: '9f2c1d3e4b5a69788796a5b4c3d2e1f0',
  patron_casos: null, estado: 'completada', aprobada: true,
  resumen: { total: 2, aprobados: 2, por_categoria: { negociacion: { total: 2, aprobados: 2 } }, costo_usd: '0.000000' },
  casos: [{ id: 'cobranza_pago_unico_dentro', categoria: 'negociacion', aprobado: true, fallos: [] }, { id: 'cobranza_cuotas_dentro', categoria: 'negociacion', aprobado: true, fallos: [] }],
  iniciada_por: { id: 1, nombre: 'Admin' }, creado_en: haceMin(30), completada_en: haceMin(29), ...o,
});

/** Manejador JSON para una ruta exacta y método. */
export const ruta = (metodo: string, path: string, f: (cuerpo: Record<string, unknown>, url: string) => Response | Promise<Response>): Manejador =>
  (url, i) => (url.split('?')[0] === `/api/v1${path}` && (i.method ?? 'GET') === metodo
    ? f(i.body ? JSON.parse(String(i.body)) : {}, url)
    : undefined);
export const rutaJson = (metodo: string, path: string, cuerpo: () => unknown, status = 200): Manejador =>
  ruta(metodo, path, () => respuesta(status, cuerpo()));
