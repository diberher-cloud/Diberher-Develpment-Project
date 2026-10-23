import { describe, expect, it } from 'vitest';
import {
  MAX_BYTES_ARCHIVO, formatearCOP, formatearFecha, formatearFechaHora, momentoBogota, validarArchivoCsv,
} from '../utilidades/formato';
import { CAMPANA_VACIA, validarCampana, aCuerpoCampana } from '../utilidades/campanas';

function archivo(nombre: string, bytes: number): File {
  const f = new File(['x'], nombre, { type: 'text/csv' });
  Object.defineProperty(f, 'size', { value: bytes });
  return f;
}

describe('formato', () => {
  it('momentoBogota añade segundos y offset -05:00 (con y sin segundos)', () => {
    expect(momentoBogota('2026-11-02T10:00')).toBe('2026-11-02T10:00:00-05:00');
    expect(momentoBogota('2026-11-02T10:00:30')).toBe('2026-11-02T10:00:30-05:00');
    expect(momentoBogota('  2026-10-23T19:00 ')).toBe('2026-10-23T19:00:00-05:00');
  });

  it('formatearCOP usa es-CO y acepta strings decimales de la API', () => {
    expect(formatearCOP('1500000.00').replace(/\s/g, ' ')).toMatch(/^\$\s?1\.500\.000(,00)?$/);
    expect(formatearCOP('250000.50').replace(/\s/g, ' ')).toMatch(/250\.000,50/);
    expect(formatearCOP(null)).toBe('—');
    expect(formatearCOP(undefined)).toBe('—');
    expect(formatearCOP('')).toBe('—');
    expect(formatearCOP('no-numero')).toBe('no-numero');
    expect(formatearCOP('0.00')).toMatch(/0/);
  });

  it('formatearFecha no desplaza el día por la zona horaria', () => {
    expect(formatearFecha('2026-09-15')).toBe('15/09/2026');
    expect(formatearFecha('2026-01-01')).toBe('01/01/2026');
    expect(formatearFecha(null)).toBe('—');
    expect(formatearFecha('basura')).toBe('basura');
  });

  it('formatearFechaHora muestra la hora de Bogotá a partir de UTC', () => {
    const texto = formatearFechaHora('2026-10-23T12:00:00Z');
    expect(texto).toMatch(/7:00|07:00/);
    expect(formatearFechaHora('2026-10-24T01:00:00Z')).toMatch(/23/); // 8:00 p. m. del día 23 en Bogotá
    expect(formatearFechaHora(null)).toBe('—');
    expect(formatearFechaHora('no-fecha')).toBe('no-fecha');
  });

  describe('validarArchivoCsv', () => {
    it('acepta .csv en cualquier capitalización y hasta exactamente 10 MiB', () => {
      expect(validarArchivoCsv(archivo('a.csv', 10))).toBeNull();
      expect(validarArchivoCsv(archivo('A.CSV', 10))).toBeNull();
      expect(validarArchivoCsv(archivo('a.csv', MAX_BYTES_ARCHIVO))).toBeNull();
    });
    it('rechaza 10 MiB + 1 byte y extensiones distintas', () => {
      expect(validarArchivoCsv(archivo('a.csv', MAX_BYTES_ARCHIVO + 1))).toMatch(/10 MiB/);
      for (const n of ['a.txt', 'a.xlsx', 'a.csv.txt', 'csv', 'a.csvx']) {
        expect(validarArchivoCsv(archivo(n, 10))).toMatch(/\.csv/);
      }
    });
  });
});

describe('validarCampana', () => {
  const ok = { ...CAMPANA_VACIA, nombre: 'Campaña', tipo: 'venta' as const };

  it('valores válidos en los límites', () => {
    expect(validarCampana(ok, false)).toEqual({});
    expect(validarCampana({ ...ok, nombre: 'abc', max_intentos: '1', intervalo_reintento_minutos: '5' }, false)).toEqual({});
    expect(validarCampana({ ...ok, nombre: 'x'.repeat(120), max_intentos: '10', intervalo_reintento_minutos: '10080' }, false)).toEqual({});
    expect(validarCampana({ ...ok, fecha_inicio: '2026-11-01', fecha_fin: '2026-11-01' }, false)).toEqual({});
  });

  it.each([
    [{ nombre: 'ab' }, 'nombre'],
    [{ nombre: '   ' }, 'nombre'],
    [{ nombre: 'x'.repeat(121) }, 'nombre'],
    [{ tipo: '' as const }, 'tipo'],
    [{ max_intentos: '0' }, 'max_intentos'],
    [{ max_intentos: '11' }, 'max_intentos'],
    [{ max_intentos: '2.5' }, 'max_intentos'],
    [{ max_intentos: '' }, 'max_intentos'],
    [{ intervalo_reintento_minutos: '4' }, 'intervalo_reintento_minutos'],
    [{ intervalo_reintento_minutos: '10081' }, 'intervalo_reintento_minutos'],
    [{ guion: 'x'.repeat(20001) }, 'guion'],
    [{ fecha_inicio: '2026-11-02', fecha_fin: '2026-11-01' }, 'fecha_fin'],
  ])('rechaza %j (campo %s)', (cambio, campo) => {
    expect(Object.keys(validarCampana({ ...ok, ...cambio }, false))).toContain(campo);
  });

  it('al editar no exige tipo', () => {
    expect(validarCampana({ ...ok, tipo: '' }, true)).toEqual({});
  });

  it('aCuerpoCampana recorta, convierte vacíos a null y números a number', () => {
    const c = aCuerpoCampana({ ...ok, nombre: '  Hola  ', descripcion: '  ', guion: '   ', max_intentos: '4' });
    expect(c).toMatchObject({ nombre: 'Hola', descripcion: null, fecha_inicio: null, fecha_fin: null, guion: null, max_intentos: 4, intervalo_reintento_minutos: 60 });
    expect('tipo' in c).toBe(false);
  });
});
