import type { CampanaCrear, EstadoCampana, TipoCampana } from '../api/tipos';

export const ETIQUETA_ESTADO: Record<EstadoCampana, string> = {
  borrador: 'Borrador', activa: 'Activa', pausada: 'Pausada', finalizada: 'Finalizada',
};
export const ETIQUETA_TIPO: Record<TipoCampana, string> = { venta: 'Venta', cobranza: 'Cobranza' };

/** Transiciones de estado válidas (fase-1.md §4.5). */
export const TRANSICIONES: Record<EstadoCampana, EstadoCampana[]> = {
  borrador: ['activa'],
  activa: ['pausada', 'finalizada'],
  pausada: ['activa', 'finalizada'],
  finalizada: [],
};

export const ETIQUETA_ACCION: Record<EstadoCampana, string> = {
  borrador: 'Volver a borrador', activa: 'Activar', pausada: 'Pausar', finalizada: 'Finalizar',
};

export interface ValoresCampana {
  nombre: string; tipo: TipoCampana | ''; descripcion: string; fecha_inicio: string; fecha_fin: string;
  guion: string; max_intentos: string; intervalo_reintento_minutos: string;
  whatsapp_habilitado: boolean; plantilla_inicial_id: string;
}

export const CAMPANA_VACIA: ValoresCampana = {
  nombre: '', tipo: '', descripcion: '', fecha_inicio: '', fecha_fin: '', guion: '',
  max_intentos: '3', intervalo_reintento_minutos: '60', whatsapp_habilitado: false, plantilla_inicial_id: '',
};

/** Validación en cliente equivalente a fase-1.md §4.5. */
export function validarCampana(v: ValoresCampana, editando: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  const nombre = v.nombre.trim();
  if (nombre.length < 3 || nombre.length > 120) e.nombre = 'Debe tener entre 3 y 120 caracteres.';
  if (!editando && !v.tipo) e.tipo = 'Seleccione el tipo de campaña.';
  if (v.guion.length > 20000) e.guion = 'No puede superar 20000 caracteres.';
  const intentos = Number(v.max_intentos);
  if (!Number.isInteger(intentos) || intentos < 1 || intentos > 10) e.max_intentos = 'Debe ser un entero entre 1 y 10.';
  const intervalo = Number(v.intervalo_reintento_minutos);
  if (!Number.isInteger(intervalo) || intervalo < 5 || intervalo > 10080) {
    e.intervalo_reintento_minutos = 'Debe ser un entero entre 5 y 10080 minutos.';
  }
  if (v.fecha_inicio && v.fecha_fin && v.fecha_fin < v.fecha_inicio) {
    e.fecha_fin = 'La fecha de fin no puede ser anterior a la fecha de inicio.';
  }
  return e;
}

export function aCuerpoCampana(v: ValoresCampana): Omit<CampanaCrear, 'tipo'> & { nombre: string } {
  return {
    nombre: v.nombre.trim(),
    descripcion: v.descripcion.trim() || null,
    fecha_inicio: v.fecha_inicio || null,
    fecha_fin: v.fecha_fin || null,
    guion: v.guion.trim() ? v.guion : null,
    max_intentos: Number(v.max_intentos),
    intervalo_reintento_minutos: Number(v.intervalo_reintento_minutos),
    whatsapp_habilitado: v.whatsapp_habilitado,
    plantilla_inicial_id: v.whatsapp_habilitado && v.plantilla_inicial_id ? Number(v.plantilla_inicial_id) : null,
  };
}
