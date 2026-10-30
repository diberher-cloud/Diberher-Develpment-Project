import { ErrorApi } from '../api/cliente';
import type {
  CodigoRequisitoIA, ConfiguracionIA, ConfiguracionIAActualizar, EfectoAccionIA, EsfuerzoIA, EstadoEvaluacionIA,
  MotivoDesactivacionIA, Periodicidad, ReglasCobranza, ReglasVenta, TipoAlertaIA, TipoCampana, Tratamiento,
} from '../api/tipos';

// ---------------------------------------------------------------------------------------------
// Etiquetas
// ---------------------------------------------------------------------------------------------
export const ETIQUETA_ESFUERZO: Record<EsfuerzoIA, string> = {
  low: 'Bajo', medium: 'Medio', high: 'Alto', xhigh: 'Muy alto', max: 'Máximo',
};
export const AYUDA_ESFUERZO: Record<EsfuerzoIA, string> = {
  low: 'Respuestas más rápidas y de menor coste; menos razonamiento.',
  medium: 'Equilibrio entre calidad, velocidad y coste.',
  high: 'Más razonamiento por turno; el coste y la latencia suben.',
  xhigh: 'Razonamiento extendido; coste y latencia altos.',
  max: 'Máximo razonamiento; el coste por conversación puede multiplicarse.',
};
export const ETIQUETA_TRATAMIENTO: Record<Tratamiento, string> = { usted: 'Usted (formal)', tu: 'Tú (cercano)' };
export const ETIQUETA_PERIODICIDAD: Record<Exclude<Periodicidad, 'unica'>, string> = {
  semanal: 'Semanal (cada 7 días)', quincenal: 'Quincenal (cada 15 días)', mensual: 'Mensual',
};
export const PERIODICIDADES_PLAN: Exclude<Periodicidad, 'unica'>[] = ['semanal', 'quincenal', 'mensual'];
export const ETIQUETA_DESACTIVADA: Record<MotivoDesactivacionIA, string> = {
  manual: 'desactivada manualmente', presupuesto: 'presupuesto mensual agotado', errores: 'errores repetidos del proveedor',
};
export const ETIQUETA_REQUISITO: Record<CodigoRequisitoIA, string> = {
  WHATSAPP_NO_HABILITADO: 'WhatsApp no habilitado en la campaña',
  SIN_CONFIGURACION: 'Sin configuración guardada',
  REGLAS_INVALIDAS: 'Reglas de negocio inválidas',
  SIN_OFERTAS_ACTIVAS: 'Sin ofertas activas',
  PRESUPUESTO_CERO: 'Presupuesto mensual en cero',
  SIN_AGENTES_ASIGNADOS: 'Sin agentes humanos asignados',
  EVALUACION_OFFLINE_PENDIENTE: 'Evaluación offline pendiente',
  EVALUACION_ONLINE_PENDIENTE: 'Evaluación online pendiente',
  IA_GLOBAL_DESACTIVADA: 'IA desactivada globalmente',
  PROVEEDOR_FALSO_EN_PRODUCCION: 'Proveedor de pruebas en producción',
  MODELO_SIN_PRECIO: 'Modelo sin precio configurado',
};
export const ETIQUETA_ALERTA_IA: Record<TipoAlertaIA, string> = {
  presupuesto_campana: 'Presupuesto de la campaña', presupuesto_conversacion: 'Coste de una conversación',
  errores: 'Errores del proveedor de IA', kill_switch: 'Kill switch', rechazo_modelo: 'Rechazo del modelo',
  evaluacion_fallida: 'Evaluación fallida',
};
export const ETIQUETA_EFECTO: Record<EfectoAccionIA, string> = {
  ninguno: 'Sin efecto', identidad: 'Identidad', tipificacion: 'Gestión', promesa: 'Acuerdo de pago', venta: 'Venta',
  seguimiento: 'Seguimiento', exclusion: 'Exclusión', autorizacion: 'Autorización', derivacion: 'Traspaso',
  cierre_pendiente: 'Cierre',
};
export const ETIQUETA_ESTADO_EVALUACION: Record<EstadoEvaluacionIA, string> = {
  pendiente: 'Pendiente', en_curso: 'En curso', completada: 'Completada', fallida: 'Fallida',
};

/** Texto del aviso global para una alerta `ia.alerta` (los eventos no llevan texto ni cifras de clientes). */
export function textoAlertaIA(
  tipo: TipoAlertaIA, nivel: 'aviso' | 'critico', campanaId: number | null, conversacionId: number | null,
): string {
  const donde = campanaId === null ? '' : ` en la campaña #${campanaId}`;
  switch (tipo) {
    case 'kill_switch':
      return campanaId === null
        ? 'Kill switch global: la IA se desactivó y sus conversaciones pasan a la cola de atención humana.'
        : `Kill switch: la IA se desactivó en la campaña #${campanaId} y sus conversaciones pasan a la cola de atención humana.`;
    case 'presupuesto_campana':
      return nivel === 'critico'
        ? `Se agotó el presupuesto mensual de IA${donde}: la IA se desactivó.`
        : `El gasto de IA${donde} alcanzó el umbral de aviso de su presupuesto mensual.`;
    case 'presupuesto_conversacion':
      return `Una conversación${conversacionId === null ? '' : ` (#${conversacionId})`}${donde} superó su coste máximo y se traspasó a un asesor.`;
    case 'errores':
      return `Errores repetidos del proveedor de IA${donde}.${nivel === 'critico' ? ' La IA se desactivó automáticamente.' : ''}`;
    case 'rechazo_modelo':
      return `El modelo rechazó responder una conversación${conversacionId === null ? '' : ` (#${conversacionId})`}${donde}.`;
    case 'evaluacion_fallida':
      return 'Una evaluación de la IA falló.';
  }
}

// ---------------------------------------------------------------------------------------------
// Formato
// ---------------------------------------------------------------------------------------------
const usd = (d: number) => new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'USD', minimumFractionDigits: d, maximumFractionDigits: d });
const FORMATOS_USD = new Map<number, Intl.NumberFormat>();

/** Dólares (coste de la IA) con `decimales` cifras. Acepta el string decimal de la API. */
export function formatearUSD(valor: string | number | null | undefined, decimales = 2): string {
  if (valor === null || valor === undefined || valor === '') return '—';
  const n = typeof valor === 'number' ? valor : Number(valor);
  if (!Number.isFinite(n)) return String(valor);
  let f = FORMATOS_USD.get(decimales);
  if (!f) {
    f = usd(decimales);
    FORMATOS_USD.set(decimales, f);
  }
  return f.format(n);
}

/** 0.93 -> "93 %". */
export function formatearPorcentaje(razon: number | null | undefined): string {
  if (razon === null || razon === undefined || !Number.isFinite(razon)) return '—';
  return `${Math.round(razon * 1000) / 10} %`;
}

export function formatearEntero(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : new Intl.NumberFormat('es-CO').format(n);
}

/** Milisegundos -> "9,2 s". */
export function formatearSegundos(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? '—' : `${(ms / 1000).toFixed(1).replace('.', ',')} s`;
}

const CLAVE_SENSIBLE = /documento|cedula|cédula|telefono|teléfono|numero_e164/i;

/**
 * Entrada de una acción de la IA lista para mostrar. El servidor ya la devuelve enmascarada (`***4050`); como defensa
 * en profundidad, cualquier valor de una clave sensible que no venga enmascarado se enmascara aquí.
 */
export function entradaEnmascarada(entrada: Record<string, unknown>): string {
  const seguro: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(entrada ?? {})) {
    if (CLAVE_SENSIBLE.test(k) && (typeof v === 'string' || typeof v === 'number')) {
      const t = String(v);
      seguro[k] = t.startsWith('***') ? t : `***${t.slice(-4)}`;
    } else {
      seguro[k] = v;
    }
  }
  const texto = JSON.stringify(seguro);
  return texto === '{}' ? '—' : texto;
}

/** Resultado de una herramienta resumido a una línea (puede ser `null`: el gestor dueño no ve ciertos resultados). */
export function resumirResultado(resultado: Record<string, unknown> | null, max = 160): string {
  if (resultado === null || resultado === undefined) return '—';
  const t = JSON.stringify(resultado);
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

// ---------------------------------------------------------------------------------------------
// Errores
// ---------------------------------------------------------------------------------------------
const MENSAJES_ERROR_IA: Record<string, string> = {
  IA_PROVEEDOR_NO_CONFIGURADO:
    'La evaluación online necesita el proveedor real de IA (IA_PROVEEDOR=anthropic) y la clave del proveedor configurados en el servidor. Use la evaluación offline o pida a un administrador que configure el proveedor.',
  EVALUACION_EN_CURSO: 'Ya hay una evaluación pendiente o en curso del mismo modo y campaña. Espere a que termine.',
  CONVERSACION_NO_IA: 'La conversación ya no está atendida por la IA (alguien la tomó o la traspasó).',
  IA_NO_DISPONIBLE: 'La IA no está disponible para esta conversación: la campaña o la IA global están desactivadas, o falta configuración.',
  OFERTA_DUPLICADA: 'Ya existe una oferta con ese código en la campaña.',
  CAMPANA_FINALIZADA: 'La campaña está finalizada: no se puede cambiar la configuración de IA ni las ofertas.',
};

/** Sustituye el mensaje de ciertos códigos de IA por una explicación más clara; conserva `detalles`. */
export function traducirErrorIA(e: ErrorApi): ErrorApi {
  const m = MENSAJES_ERROR_IA[e.codigo];
  return m ? new ErrorApi(e.status, e.codigo, m, e.detalles) : e;
}

// ---------------------------------------------------------------------------------------------
// Formulario de configuración
// ---------------------------------------------------------------------------------------------
export interface FormTramo { max_cuotas: string; descuento_max_pct: string }
export interface FormCobranza {
  base_descuento: 'saldo_mora' | 'saldo_total'; descuento_max_pct: string; tramos: FormTramo[];
  monto_minimo_promesa: string; monto_minimo_cuota: string; max_cuotas: string;
  plazo_max_dias_primer_pago: string; plazo_max_dias_total: string; periodicidades: Exclude<Periodicidad, 'unica'>[];
}
export interface FormVenta { max_unidades_por_venta: string; requiere_aceptacion_terminos: boolean }
export interface FormIA {
  modelo: string; esfuerzo: EsfuerzoIA; prompt_version: string; tratamiento: Tratamiento; instrucciones: string;
  max_intentos: string; presupuesto_usd_mensual: string; max_costo_conversacion_usd: string; max_turnos_conversacion: string;
  cobranza: FormCobranza; venta: FormVenta;
}

export const MAX_INSTRUCCIONES = 2000;

const COBRANZA_DEFECTO: FormCobranza = {
  base_descuento: 'saldo_mora', descuento_max_pct: '0.00', tramos: [], monto_minimo_promesa: '0.00', monto_minimo_cuota: '0.00',
  max_cuotas: '1', plazo_max_dias_primer_pago: '7', plazo_max_dias_total: '30', periodicidades: ['mensual'],
};
const VENTA_DEFECTO: FormVenta = { max_unidades_por_venta: '1', requiere_aceptacion_terminos: true };

export function formDesdeConfig(c: ConfiguracionIA): FormIA {
  let cobranza = COBRANZA_DEFECTO;
  let venta = VENTA_DEFECTO;
  if (c.reglas && c.campana_tipo === 'cobranza') {
    const r = c.reglas as ReglasCobranza;
    cobranza = {
      base_descuento: r.base_descuento, descuento_max_pct: r.descuento_max_pct,
      tramos: (r.descuento_max_pct_por_cuotas ?? []).map((t) => ({ max_cuotas: String(t.max_cuotas), descuento_max_pct: t.descuento_max_pct })),
      monto_minimo_promesa: r.monto_minimo_promesa, monto_minimo_cuota: r.monto_minimo_cuota, max_cuotas: String(r.max_cuotas),
      plazo_max_dias_primer_pago: String(r.plazo_max_dias_primer_pago), plazo_max_dias_total: String(r.plazo_max_dias_total),
      periodicidades: [...(r.periodicidades ?? [])],
    };
  } else if (c.reglas && c.campana_tipo === 'venta') {
    const r = c.reglas as ReglasVenta;
    venta = { max_unidades_por_venta: String(r.max_unidades_por_venta), requiere_aceptacion_terminos: r.requiere_aceptacion_terminos };
  }
  return {
    modelo: c.modelo, esfuerzo: c.esfuerzo, prompt_version: String(c.prompt_version), tratamiento: c.tratamiento,
    instrucciones: c.instrucciones ?? '', max_intentos: String(c.verificacion.max_intentos),
    presupuesto_usd_mensual: c.presupuesto_usd_mensual, max_costo_conversacion_usd: c.max_costo_conversacion_usd,
    max_turnos_conversacion: String(c.max_turnos_conversacion), cobranza, venta,
  };
}

const normalizar = (s: string) => s.trim().replace(',', '.');
const esEntero = (s: string) => /^\d+$/.test(s.trim());
/** Decimal no negativo con a lo sumo `dec` cifras decimales (admite coma o punto). */
export function esDecimal(s: string, dec: number): boolean {
  return new RegExp(`^\\d+(\\.\\d{1,${dec}})?$`).test(normalizar(s));
}
const aDecimal = (s: string, dec: number) => Number(normalizar(s)).toFixed(dec);

function validarCobranza(f: FormCobranza, e: Record<string, string>) {
  const P = 'reglas.';
  const dec2 = (campo: keyof FormCobranza, min: number, minimoExclusivo: boolean, texto: string) => {
    const v = f[campo] as string;
    if (!esDecimal(v, 2)) e[P + campo] = `${texto} debe ser un número con hasta 2 decimales.`;
    else {
      const n = Number(normalizar(v));
      if (minimoExclusivo ? n <= min : n < min) e[P + campo] = minimoExclusivo ? `${texto} debe ser mayor que ${min}.` : `${texto} no puede ser menor que ${min}.`;
    }
  };
  if (!esDecimal(f.descuento_max_pct, 2) || Number(normalizar(f.descuento_max_pct)) > 100) {
    e[`${P}descuento_max_pct`] = 'El descuento máximo debe estar entre 0 y 100, con hasta 2 decimales.';
  }
  dec2('monto_minimo_promesa', 0, true, 'El monto mínimo de la promesa');
  dec2('monto_minimo_cuota', 0, true, 'El monto mínimo de la cuota');
  let maxCuotas = NaN;
  if (!esEntero(f.max_cuotas) || Number(f.max_cuotas) < 1 || Number(f.max_cuotas) > 36) {
    e[`${P}max_cuotas`] = 'El máximo de cuotas debe ser un entero entre 1 y 36.';
  } else maxCuotas = Number(f.max_cuotas);
  let primero = NaN;
  if (!esEntero(f.plazo_max_dias_primer_pago) || Number(f.plazo_max_dias_primer_pago) > 90) {
    e[`${P}plazo_max_dias_primer_pago`] = 'El plazo del primer pago debe ser un entero entre 0 y 90 días.';
  } else primero = Number(f.plazo_max_dias_primer_pago);
  if (!esEntero(f.plazo_max_dias_total) || Number(f.plazo_max_dias_total) > 365) {
    e[`${P}plazo_max_dias_total`] = 'El plazo total debe ser un entero entre 0 y 365 días.';
  } else if (!Number.isNaN(primero) && Number(f.plazo_max_dias_total) < primero) {
    e[`${P}plazo_max_dias_total`] = 'El plazo total no puede ser menor que el del primer pago.';
  }
  if (maxCuotas > 1 && f.periodicidades.length === 0) {
    e[`${P}periodicidades`] = 'Elija al menos una periodicidad cuando se permiten varias cuotas.';
  }
  // Tramos: max_cuotas estrictamente crecientes y <= max_cuotas; cada descuento <= el general.
  const general = esDecimal(f.descuento_max_pct, 2) ? Number(normalizar(f.descuento_max_pct)) : NaN;
  let previo = 0;
  f.tramos.forEach((t, i) => {
    const base = `${P}descuento_max_pct_por_cuotas.${i}.`;
    if (!esEntero(t.max_cuotas) || Number(t.max_cuotas) < 1) {
      e[`${base}max_cuotas`] = 'Indique un número de cuotas entero mayor que 0.';
    } else {
      const n = Number(t.max_cuotas);
      if (n <= previo) e[`${base}max_cuotas`] = 'Los tramos deben ir en orden estrictamente creciente de cuotas.';
      else if (!Number.isNaN(maxCuotas) && n > maxCuotas) e[`${base}max_cuotas`] = `No puede superar el máximo de cuotas (${maxCuotas}).`;
      previo = Math.max(previo, n);
    }
    if (!esDecimal(t.descuento_max_pct, 2) || Number(normalizar(t.descuento_max_pct)) > 100) {
      e[`${base}descuento_max_pct`] = 'El descuento debe estar entre 0 y 100, con hasta 2 decimales.';
    } else if (!Number.isNaN(general) && Number(normalizar(t.descuento_max_pct)) > general) {
      e[`${base}descuento_max_pct`] = `No puede superar el descuento máximo general (${general} %).`;
    }
  });
}

/** Validación local previa al envío. Las claves son las rutas de campo que usa la API en sus errores 422. */
export function validarFormIA(f: FormIA, tipo: TipoCampana): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.modelo.trim()) e.modelo = 'Elija un modelo.';
  if (!esEntero(f.prompt_version) || Number(f.prompt_version) < 1) e.prompt_version = 'Elija una versión de prompt.';
  if (f.instrucciones.length > MAX_INSTRUCCIONES) e.instrucciones = `Las instrucciones no pueden superar ${MAX_INSTRUCCIONES} caracteres.`;
  if (!esEntero(f.max_intentos) || Number(f.max_intentos) < 1 || Number(f.max_intentos) > 5) {
    e['verificacion.max_intentos'] = 'Los intentos de verificación deben ser un entero entre 1 y 5.';
  }
  if (!esDecimal(f.presupuesto_usd_mensual, 2)) e.presupuesto_usd_mensual = 'El presupuesto debe ser un número (USD) con hasta 2 decimales.';
  if (!esDecimal(f.max_costo_conversacion_usd, 4) || Number(normalizar(f.max_costo_conversacion_usd)) < 0.01 || Number(normalizar(f.max_costo_conversacion_usd)) > 10) {
    e.max_costo_conversacion_usd = 'El coste máximo por conversación debe estar entre 0,01 y 10 USD.';
  }
  if (!esEntero(f.max_turnos_conversacion) || Number(f.max_turnos_conversacion) < 1 || Number(f.max_turnos_conversacion) > 200) {
    e.max_turnos_conversacion = 'Los turnos máximos deben ser un entero entre 1 y 200.';
  }
  if (tipo === 'cobranza') validarCobranza(f.cobranza, e);
  else if (!esEntero(f.venta.max_unidades_por_venta) || Number(f.venta.max_unidades_por_venta) < 1 || Number(f.venta.max_unidades_por_venta) > 100) {
    e['reglas.max_unidades_por_venta'] = 'Las unidades máximas por venta deben ser un entero entre 1 y 100.';
  }
  return e;
}

/** Cuerpo del PUT. Solo se invoca con el formulario ya validado. */
export function construirActualizacion(f: FormIA, tipo: TipoCampana, versionEsperada: number): ConfiguracionIAActualizar {
  const reglas: ReglasCobranza | ReglasVenta = tipo === 'cobranza'
    ? {
        base_descuento: f.cobranza.base_descuento, descuento_max_pct: aDecimal(f.cobranza.descuento_max_pct, 2),
        descuento_max_pct_por_cuotas: f.cobranza.tramos.map((t) => ({ max_cuotas: Number(t.max_cuotas), descuento_max_pct: aDecimal(t.descuento_max_pct, 2) })),
        monto_minimo_promesa: aDecimal(f.cobranza.monto_minimo_promesa, 2), monto_minimo_cuota: aDecimal(f.cobranza.monto_minimo_cuota, 2),
        max_cuotas: Number(f.cobranza.max_cuotas), plazo_max_dias_primer_pago: Number(f.cobranza.plazo_max_dias_primer_pago),
        plazo_max_dias_total: Number(f.cobranza.plazo_max_dias_total), periodicidades: [...f.cobranza.periodicidades],
      }
    : { max_unidades_por_venta: Number(f.venta.max_unidades_por_venta), requiere_aceptacion_terminos: f.venta.requiere_aceptacion_terminos };
  const instrucciones = f.instrucciones.trim();
  return {
    version_esperada: versionEsperada, modelo: f.modelo, esfuerzo: f.esfuerzo, prompt_version: Number(f.prompt_version),
    tratamiento: f.tratamiento, instrucciones: instrucciones === '' ? null : instrucciones,
    verificacion: { factores: ['numero_documento'], max_intentos: Number(f.max_intentos) }, reglas,
    presupuesto_usd_mensual: aDecimal(f.presupuesto_usd_mensual, 2),
    max_costo_conversacion_usd: aDecimal(f.max_costo_conversacion_usd, esDecimal(f.max_costo_conversacion_usd, 2) ? 2 : 4),
    max_turnos_conversacion: Number(f.max_turnos_conversacion),
  };
}

/** Porcentaje (0..100) del presupuesto gastado; `null` si no hay presupuesto. */
export function porcentajeGasto(gasto: string, presupuesto: string): number | null {
  const p = Number(presupuesto);
  const g = Number(gasto);
  if (!Number.isFinite(p) || p <= 0 || !Number.isFinite(g)) return null;
  return Math.min(100, Math.round((g / p) * 100));
}
