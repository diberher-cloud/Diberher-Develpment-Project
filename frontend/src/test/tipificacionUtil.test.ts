import { describe, expect, it } from 'vitest';
import {
  aCuerpoTipificacion, resultadosPermitidos, TIPIFICACION_VACIA, validarTipificacion, type ValoresTipificacion,
} from '../utilidades/tipificacion';
import { hoyBogota, sumarDias } from '../utilidades/formato';

const AHORA = new Date('2026-10-23T15:00:00Z'); // 10:00 en Bogotá
const ctx = { tipoCampana: 'cobranza' as const, saldoTotal: '1500000.00', ahora: AHORA };
const v = (o: Partial<ValoresTipificacion>): ValoresTipificacion => ({ ...TIPIFICACION_VACIA, ...o });

describe('resultadosPermitidos', () => {
  it('promesa_pago solo en cobranza y venta solo en venta', () => {
    expect(resultadosPermitidos({ tipoCampana: 'cobranza' })).toContain('promesa_pago');
    expect(resultadosPermitidos({ tipoCampana: 'cobranza' })).not.toContain('venta');
    expect(resultadosPermitidos({ tipoCampana: 'venta' })).toContain('venta');
    expect(resultadosPermitidos({ tipoCampana: 'venta' })).not.toContain('promesa_pago');
  });
  it('si la llamada nunca se contestó solo no_contesta y numero_errado', () => {
    for (const estadoLlamada of ['no_contesta', 'ocupado', 'fallida', 'cancelada'] as const) {
      expect(resultadosPermitidos({ tipoCampana: 'venta', estadoLlamada })).toEqual(['no_contesta', 'numero_errado']);
    }
    expect(resultadosPermitidos({ tipoCampana: 'venta', estadoLlamada: 'completada' })).toHaveLength(6);
  });
});

describe('validarTipificacion', () => {
  it('exige resultado', () => {
    expect(validarTipificacion(v({}), ctx).resultado).toBeTruthy();
  });

  it('resultados sin campos extra son válidos', () => {
    for (const resultado of ['contactado', 'no_contesta', 'numero_errado', 'rechazo'] as const) {
      expect(validarTipificacion(v({ resultado }), ctx)).toEqual({});
    }
  });

  it('promesa: monto > 0, <= 2 decimales, <= saldo total; fecha entre hoy y hoy + 60 días', () => {
    const hoy = hoyBogota(AHORA);
    const ok = v({ resultado: 'promesa_pago', montoPromesa: '250000.50', fechaPago: hoy });
    expect(validarTipificacion(ok, ctx)).toEqual({});
    expect(validarTipificacion({ ...ok, fechaPago: sumarDias(hoy, 60) }, ctx)).toEqual({});
    expect(validarTipificacion({ ...ok, montoPromesa: '' }, ctx).monto).toBeTruthy();
    expect(validarTipificacion({ ...ok, montoPromesa: '0' }, ctx).monto).toMatch(/mayor que cero/);
    expect(validarTipificacion({ ...ok, montoPromesa: '10.123' }, ctx).monto).toMatch(/2 decimales/);
    expect(validarTipificacion({ ...ok, montoPromesa: '250.000,50' }, ctx).monto).toBeTruthy();
    expect(validarTipificacion({ ...ok, montoPromesa: '1500000.01' }, ctx).monto).toMatch(/saldo total/);
    expect(validarTipificacion({ ...ok, montoPromesa: '1500000.00' }, ctx)).toEqual({});
    expect(validarTipificacion({ ...ok, montoPromesa: '999999999' }, { ...ctx, saldoTotal: null })).toEqual({});
    expect(validarTipificacion({ ...ok, fechaPago: '' }, ctx).fecha_pago).toBeTruthy();
    expect(validarTipificacion({ ...ok, fechaPago: sumarDias(hoy, -1) }, ctx).fecha_pago).toMatch(/anterior a hoy/);
    expect(validarTipificacion({ ...ok, fechaPago: sumarDias(hoy, 61) }, ctx).fecha_pago).toMatch(/60 días/);
  });

  it('venta: producto 2..120 y valor > 0', () => {
    const ctxV = { ...ctx, tipoCampana: 'venta' as const };
    const ok = v({ resultado: 'venta', producto: 'Seguro hogar', valorVenta: '89900.00' });
    expect(validarTipificacion(ok, ctxV)).toEqual({});
    expect(validarTipificacion({ ...ok, producto: ' a ' }, ctxV).producto).toBeTruthy();
    expect(validarTipificacion({ ...ok, producto: 'x'.repeat(121) }, ctxV).producto).toBeTruthy();
    expect(validarTipificacion({ ...ok, valorVenta: '-5' }, ctxV).valor).toBeTruthy();
  });

  it('volver a llamar: contacto directo obligatorio y fecha entre 5 minutos y 30 días', () => {
    // 2026-10-23 10:00 Bogotá = ahora
    const ok = v({ resultado: 'volver_a_llamar', contactoDirecto: 'no', volverALlamarEn: '2026-10-26T09:00' });
    expect(validarTipificacion(ok, ctx)).toEqual({});
    expect(validarTipificacion({ ...ok, contactoDirecto: '' }, ctx).contacto_directo).toBeTruthy();
    expect(validarTipificacion({ ...ok, volverALlamarEn: '' }, ctx).volver_a_llamar_en).toBeTruthy();
    expect(validarTipificacion({ ...ok, volverALlamarEn: '2026-10-23T10:04' }, ctx).volver_a_llamar_en).toMatch(/5 minutos/);
    expect(validarTipificacion({ ...ok, volverALlamarEn: '2026-10-23T10:06' }, ctx)).toEqual({});
    expect(validarTipificacion({ ...ok, volverALlamarEn: '2026-11-22T10:01' }, ctx).volver_a_llamar_en).toMatch(/30 días/);
  });

  it('rechaza resultados incompatibles con la llamada y observaciones largas', () => {
    expect(validarTipificacion(v({ resultado: 'rechazo' }), { ...ctx, estadoLlamada: 'no_contesta' }).resultado).toBeTruthy();
    expect(validarTipificacion(v({ resultado: 'venta' }), ctx).resultado).toBeTruthy();
    expect(validarTipificacion(v({ resultado: 'rechazo', observacion: 'x'.repeat(1001) }), ctx).observacion).toBeTruthy();
  });
});

describe('aCuerpoTipificacion', () => {
  it('envía solo los campos del resultado elegido', () => {
    const base = { observacion: '  nota  ', montoPromesa: '10', fechaPago: '2026-10-30', producto: 'P', valorVenta: '5', volverALlamarEn: '2026-10-26T09:00' };
    expect(aCuerpoTipificacion(1, v({ ...base, resultado: 'rechazo', contactoDirecto: 'si' }))).toEqual({
      llamada_id: 1, resultado: 'rechazo', observacion: 'nota',
    });
    expect(aCuerpoTipificacion(1, v({ ...base, resultado: 'promesa_pago' }))).toEqual({
      llamada_id: 1, resultado: 'promesa_pago', observacion: 'nota', promesa: { monto: '10', fecha_pago: '2026-10-30' },
    });
    expect(aCuerpoTipificacion(1, v({ ...base, resultado: 'volver_a_llamar', contactoDirecto: 'si', observacion: '' }))).toEqual({
      llamada_id: 1, resultado: 'volver_a_llamar', observacion: null, volver_a_llamar_en: '2026-10-26T09:00:00-05:00', contacto_directo: true,
    });
  });
});
