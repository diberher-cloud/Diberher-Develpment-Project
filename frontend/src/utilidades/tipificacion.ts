import type { EstadoLlamada, ResultadoTipificacion, TipificacionCrear, TipoCampana } from '../api/tipos';
import { hoyBogota, momentoBogota, sumarDias } from './formato';

export const ETIQUETA_RESULTADO: Record<ResultadoTipificacion, string> = {
  contactado: 'Contactado',
  no_contesta: 'No contesta',
  numero_errado: 'Número errado',
  promesa_pago: 'Promesa de pago',
  venta: 'Venta',
  rechazo: 'Rechazo',
  volver_a_llamar: 'Volver a llamar',
};

export const RESULTADOS: ResultadoTipificacion[] = [
  'contactado', 'no_contesta', 'numero_errado', 'promesa_pago', 'venta', 'rechazo', 'volver_a_llamar',
];

/** Límite de días de una promesa (PROMESA_MAX_DIAS por defecto en el servidor; el servidor es la autoridad). */
export const PROMESA_MAX_DIAS = 60;
const MIN_REAGENDA_MS = 5 * 60_000;
const MAX_REAGENDA_MS = 30 * 24 * 3_600_000;
const NO_CONTESTADAS: EstadoLlamada[] = ['no_contesta', 'ocupado', 'fallida', 'cancelada'];

export interface ValoresTipificacion {
  resultado: ResultadoTipificacion | '';
  observacion: string;
  montoPromesa: string;
  fechaPago: string;
  producto: string;
  valorVenta: string;
  volverALlamarEn: string; // datetime-local en hora de Bogotá
  contactoDirecto: '' | 'si' | 'no';
}

export const TIPIFICACION_VACIA: ValoresTipificacion = {
  resultado: '', observacion: '', montoPromesa: '', fechaPago: '', producto: '', valorVenta: '',
  volverALlamarEn: '', contactoDirecto: '',
};

export interface ContextoTipificacion {
  tipoCampana: TipoCampana;
  saldoTotal: string | null;
  /** Estado técnico de la llamada, si se conoce. */
  estadoLlamada?: EstadoLlamada | null;
  ahora?: Date;
}

/** Resultados que el servidor aceptará para esta campaña y llamada (RESULTADO_NO_PERMITIDO / _INCOHERENTE). */
export function resultadosPermitidos(ctx: Pick<ContextoTipificacion, 'tipoCampana' | 'estadoLlamada'>): ResultadoTipificacion[] {
  return RESULTADOS.filter((r) => {
    if (r === 'promesa_pago' && ctx.tipoCampana !== 'cobranza') return false;
    if (r === 'venta' && ctx.tipoCampana !== 'venta') return false;
    if (ctx.estadoLlamada && NO_CONTESTADAS.includes(ctx.estadoLlamada) && r !== 'no_contesta' && r !== 'numero_errado') return false;
    return true;
  });
}

const DECIMAL = /^\d+(\.\d{1,2})?$/;

function validarMonto(valor: string, maximo?: string | null): string | undefined {
  const v = valor.trim();
  if (!v) return 'Ingrese el monto.';
  if (!DECIMAL.test(v)) return 'Use solo dígitos y punto decimal, con máximo 2 decimales (ej. 250000.50).';
  const n = Number(v);
  if (!(n > 0)) return 'El monto debe ser mayor que cero.';
  if (maximo != null && maximo !== '' && n > Number(maximo)) return 'El monto no puede superar el saldo total de la obligación.';
  return undefined;
}

/** Validación en cliente equivalente a fase-2.md §4.6. Devuelve errores por campo ({} si es válido). */
export function validarTipificacion(v: ValoresTipificacion, ctx: ContextoTipificacion): Record<string, string> {
  const e: Record<string, string> = {};
  const ahora = ctx.ahora ?? new Date();
  if (!v.resultado) {
    e.resultado = 'Seleccione el resultado de la gestión.';
    return e;
  }
  if (!resultadosPermitidos(ctx).includes(v.resultado)) e.resultado = 'Este resultado no es posible para esta llamada o campaña.';
  if (v.observacion.length > 1000) e.observacion = 'No puede superar 1000 caracteres.';

  if (v.resultado === 'promesa_pago') {
    const m = validarMonto(v.montoPromesa, ctx.saldoTotal);
    if (m) e.monto = m;
    const hoy = hoyBogota(ahora);
    if (!v.fechaPago) e.fecha_pago = 'Seleccione la fecha de pago.';
    else if (v.fechaPago < hoy) e.fecha_pago = 'La fecha de pago no puede ser anterior a hoy.';
    else if (v.fechaPago > sumarDias(hoy, PROMESA_MAX_DIAS)) {
      e.fecha_pago = `La fecha de pago no puede superar ${PROMESA_MAX_DIAS} días desde hoy.`;
    }
  }
  if (v.resultado === 'venta') {
    const p = v.producto.trim();
    if (p.length < 2 || p.length > 120) e.producto = 'El producto debe tener entre 2 y 120 caracteres.';
    const m = validarMonto(v.valorVenta);
    if (m) e.valor = m;
  }
  if (v.resultado === 'volver_a_llamar') {
    if (!v.contactoDirecto) e.contacto_directo = 'Indique si hubo contacto directo.';
    if (!v.volverALlamarEn) e.volver_a_llamar_en = 'Seleccione la fecha y hora de la nueva llamada.';
    else {
      const t = new Date(momentoBogota(v.volverALlamarEn)).getTime();
      if (Number.isNaN(t)) e.volver_a_llamar_en = 'Fecha y hora no válidas.';
      else if (t <= ahora.getTime() + MIN_REAGENDA_MS) e.volver_a_llamar_en = 'Debe ser al menos 5 minutos en el futuro.';
      else if (t > ahora.getTime() + MAX_REAGENDA_MS) e.volver_a_llamar_en = 'No puede superar 30 días desde ahora.';
    }
  }
  return e;
}

/** Cuerpo de `POST /consola/tipificaciones`: solo los campos que corresponden al resultado. */
export function aCuerpoTipificacion(llamadaId: number, v: ValoresTipificacion): TipificacionCrear {
  if (!v.resultado) throw new Error('Resultado no seleccionado.');
  const cuerpo: TipificacionCrear = {
    llamada_id: llamadaId,
    resultado: v.resultado,
    observacion: v.observacion.trim() || null,
  };
  if (v.resultado === 'promesa_pago') cuerpo.promesa = { monto: v.montoPromesa.trim(), fecha_pago: v.fechaPago };
  if (v.resultado === 'venta') cuerpo.venta = { producto: v.producto.trim(), valor: v.valorVenta.trim() };
  if (v.resultado === 'volver_a_llamar') {
    cuerpo.volver_a_llamar_en = momentoBogota(v.volverALlamarEn);
    cuerpo.contacto_directo = v.contactoDirecto === 'si';
  }
  return cuerpo;
}
