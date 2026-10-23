import type { EstadoAgenteValor, EstadoLlamada, MotivoPausa } from '../api/tipos';
import type { EstadoSoftphone } from '../telefonia/softphone';

export const ETIQUETA_ESTADO_AGENTE: Record<EstadoAgenteValor, string> = {
  desconectado: 'Desconectado', disponible: 'Disponible', pausa: 'En pausa', en_llamada: 'En llamada', tipificando: 'Tipificando',
};
export const ETIQUETA_MOTIVO_PAUSA: Record<MotivoPausa, string> = {
  descanso: 'Descanso', almuerzo: 'Almuerzo', capacitacion: 'Capacitación', reunion: 'Reunión', otro: 'Otro',
};
export const ETIQUETA_ESTADO_LLAMADA: Record<EstadoLlamada, string> = {
  iniciando: 'Iniciando', sonando: 'Sonando', en_curso: 'En curso', completada: 'Completada', ocupado: 'Ocupado',
  no_contesta: 'No contesta', fallida: 'Fallida', cancelada: 'Cancelada', bloqueada: 'Bloqueada',
};
export const TEXTO_SOFTPHONE: Record<EstadoSoftphone, string> = {
  inactivo: 'Softphone inactivo.',
  registrando: 'Preparando el softphone…',
  listo: 'Listo para llamar.',
  conectando: 'Llamando…',
  en_curso: 'Llamada en curso.',
  finalizada: 'Llamada finalizada.',
  error: 'Error en el softphone.',
};
