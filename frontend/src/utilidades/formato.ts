export const ZONA = 'America/Bogota';
export const OFFSET_BOGOTA = '-05:00';
export const MAX_BYTES_ARCHIVO = 10 * 1024 * 1024; // 10 MiB

const monedaCOP = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP' });
const fechaHora = new Intl.DateTimeFormat('es-CO', { timeZone: ZONA, dateStyle: 'medium', timeStyle: 'short' });

/** Formatea un monto (string decimal de la API o número) como COP. */
export function formatearCOP(valor: string | number | null | undefined): string {
  if (valor === null || valor === undefined || valor === '') return '—';
  const n = typeof valor === 'number' ? valor : Number(valor);
  return Number.isFinite(n) ? monedaCOP.format(n) : String(valor);
}

/** Fecha-hora ISO con zona -> texto en America/Bogota. */
export function formatearFechaHora(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : fechaHora.format(d);
}

/** 'YYYY-MM-DD' -> 'DD/MM/YYYY' sin pasar por Date (evita desfases de zona). */
export function formatearFecha(fecha: string | null | undefined): string {
  if (!fecha) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fecha);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : fecha;
}

/**
 * Valor de <input type="datetime-local"> (hora local de Bogotá) -> ISO con offset -05:00.
 * Independiente de la zona del navegador.
 */
export function momentoBogota(valorLocal: string): string {
  const v = valorLocal.trim();
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v)) return `${v}:00${OFFSET_BOGOTA}`;
  return `${v}${OFFSET_BOGOTA}`;
}

/** Año calendario actual en Bogotá. */
export function anioActualBogota(): number {
  return Number(new Intl.DateTimeFormat('en-CA', { timeZone: ZONA, year: 'numeric' }).format(new Date()));
}

export function formatearTamano(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${bytes} B`;
}

/** Valida un archivo CSV en cliente. Devuelve el mensaje de error o null. */
export function validarArchivoCsv(archivo: File): string | null {
  if (!archivo.name.toLowerCase().endsWith('.csv')) return 'El archivo debe tener extensión .csv.';
  if (archivo.size > MAX_BYTES_ARCHIVO) {
    return `El archivo pesa ${formatearTamano(archivo.size)} y supera el máximo de 10 MiB.`;
  }
  return null;
}
