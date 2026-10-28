export const ZONA = 'America/Bogota';
export const OFFSET_BOGOTA = '-05:00';
export const MAX_BYTES_ARCHIVO = 10 * 1024 * 1024; // 10 MiB

const monedaCOP = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', minimumFractionDigits: 0, maximumFractionDigits: 0 });
const monedaCOPCentavos = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fechaHora = new Intl.DateTimeFormat('es-CO', { timeZone: ZONA, dateStyle: 'medium', timeStyle: 'short' });

/** Formatea un monto (string decimal de la API o número) como COP. */
export function formatearCOP(valor: string | number | null | undefined): string {
  if (valor === null || valor === undefined || valor === '') return '—';
  const n = typeof valor === 'number' ? valor : Number(valor);
  if (!Number.isFinite(n)) return String(valor);
  // Igual que el guion del servidor: sin decimales si son ",00"; con 2 decimales en otro caso.
  return Math.round(n * 100) % 100 === 0 ? monedaCOP.format(Math.round(n)) : monedaCOPCentavos.format(n);
}

/** Fecha-hora ISO con zona -> texto en America/Bogota. */
export function formatearFechaHora(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : fechaHora.format(d);
}

/** Añade el punto final solo si el texto no termina ya en punto ("a. m."). */
export const conPunto = (t: string) => (t.endsWith('.') ? t : `${t}.`);

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

/** Valida un archivo de importación (.csv o .xlsx) en cliente. Devuelve el mensaje de error o null. */
export function validarArchivoTabla(archivo: File): string | null {
  const nombre = archivo.name.toLowerCase();
  if (!nombre.endsWith('.csv') && !nombre.endsWith('.xlsx')) return 'El archivo debe tener extensión .csv o .xlsx.';
  if (archivo.size > MAX_BYTES_ARCHIVO) {
    return `El archivo pesa ${formatearTamano(archivo.size)} y supera el máximo de 10 MiB.`;
  }
  return null;
}

/** Fecha de hoy en Bogotá como 'YYYY-MM-DD'. */
export function hoyBogota(ahora: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: ZONA, year: 'numeric', month: '2-digit', day: '2-digit' }).format(ahora);
}

/** Suma días a una fecha 'YYYY-MM-DD' (aritmética de calendario, sin zona). */
export function sumarDias(fecha: string, dias: number): string {
  const [a, m, d] = fecha.split('-').map(Number);
  const r = new Date(Date.UTC(a, m - 1, d + dias));
  return r.toISOString().slice(0, 10);
}

/** Segundos -> 'HH:MM:SS'. */
export function formatearDuracion(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos));
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${dos(Math.floor(s / 3600))}:${dos(Math.floor((s % 3600) / 60))}:${dos(s % 60)}`;
}
