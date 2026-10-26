import type {
  AtendidaPor, AutorMensaje, CampoPlantilla, Conversacion, EstadoMensaje, Finalidad, Mensaje, MotivoCola, MotivoCierre,
  Plantilla, Rol,
} from '../api/tipos';
import { formatearFechaHora } from './formato';

/** UUID v4 por intento de envío. `randomUUID` solo existe en contextos seguros; hay alternativa con getRandomValues. */
export function nuevoUuid(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const b = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(b);
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export const ETIQUETA_ATENDIDA_POR: Record<AtendidaPor, string> = {
  sin_asignar: 'Sin asignar', humano: 'Agente humano', ia: 'Agente IA',
};
export const ETIQUETA_MOTIVO_COLA: Record<MotivoCola, string> = {
  entrante: 'Mensaje entrante', sin_campana: 'Sin campaña', liberada: 'Liberada', agente_desconectado: 'Agente desconectado',
  supervisor: 'Supervisor', solicitud_cliente: 'Solicitud del cliente', queja: 'Queja', ia_no_resuelve: 'La IA no resuelve',
  identidad_bloqueada: 'Identidad bloqueada', ia_rechazo: 'Rechazo de la IA', ia_max_tokens: 'Límite de la IA',
  ia_iteraciones: 'Límite de la IA', ia_stop_inesperado: 'Error de la IA', ia_monto_no_respaldado: 'Monto no respaldado',
  ia_error: 'Error de la IA', presupuesto_excedido: 'Presupuesto excedido', ia_desactivada: 'IA desactivada',
};
export const ETIQUETA_MOTIVO_CIERRE: Record<MotivoCierre, string> = {
  agente: 'Cerrada por el agente', supervisor: 'Cerrada por un supervisor', inactividad: 'Cerrada por inactividad',
  opt_out: 'Cerrada por solicitud de baja', sistema: 'Cerrada por el sistema',
};
export const ETIQUETA_FINALIDAD: Record<Finalidad, string> = { venta: 'Venta', cobranza: 'Cobranza', todas: 'Todas' };
export const ETIQUETA_AUTOR: Record<AutorMensaje, string> = { cliente: 'Cliente', agente: 'Agente', ia: 'IA', sistema: 'Sistema' };
export const ETIQUETA_CAMPO_PLANTILLA: Record<CampoPlantilla, string> = {
  primer_nombre: 'Primer nombre del cliente', empresa: 'Nombre de la empresa', agente: 'Primer nombre del agente', producto: 'Producto del registro',
};
export const CAMPOS_PLANTILLA = Object.keys(ETIQUETA_CAMPO_PLANTILLA) as CampoPlantilla[];

/** Texto accesible del estado de un mensaje (no depende solo del color o de un icono). */
export function textoEstadoMensaje(m: Pick<Mensaje, 'estado' | 'error' | 'programado_para' | 'direccion'>): string {
  const e: EstadoMensaje = m.estado;
  switch (e) {
    case 'recibido': return 'Recibido';
    case 'pendiente': return 'Pendiente de envío';
    case 'retenido': return `Retenido hasta ${formatearFechaHora(m.programado_para)}`;
    case 'enviando': return 'Enviando…';
    case 'enviado': return 'Enviado';
    case 'entregado': return 'Entregado';
    case 'leido': return 'Leído';
    case 'cancelado': return 'Cancelado';
    case 'fallido': return `Fallido${m.error ? `: ${m.error.mensaje}` : ''}`;
  }
}

/** Símbolo corto, aria-hidden: el texto de `textoEstadoMensaje` es el accesible. */
export const ICONO_ESTADO: Record<EstadoMensaje, string> = {
  recibido: '', pendiente: '…', retenido: '…', enviando: '…', enviado: '✓', entregado: '✓✓', leido: '✓✓', fallido: '!', cancelado: 'x',
};

/** Segundos -> "HH:MM:SS" para la cuenta atrás de la ventana. */
export function formatearRestante(segundos: number): string {
  const s = Math.max(0, Math.floor(segundos));
  const dos = (n: number) => String(n).padStart(2, '0');
  return `${dos(Math.floor(s / 3600))}:${dos(Math.floor((s % 3600) / 60))}:${dos(s % 60)}`;
}

/** Número a mostrar: el E.164 completo solo lo ven administrador y supervisor; el agente, la máscara. */
export function numeroVisible(c: { numero_mascara: string; numero_e164: string | null }, rol: Rol | undefined): string {
  return rol !== undefined && rol !== 'agente' && c.numero_e164 ? c.numero_e164 : c.numero_mascara;
}

/**
 * Vista previa de una plantilla: sustituye `{{n}}` por el campo mapeado entre corchetes. El valor real lo calcula el
 * servidor; aquí no se conocen datos del cliente.
 */
export function previaPlantilla(p: Pick<Plantilla, 'cuerpo' | 'mapeo_variables'>): string {
  return p.cuerpo.replace(/\{\{\s*(\w+)\s*\}\}/g, (todo, clave: string) => {
    const campo = p.mapeo_variables[clave];
    return campo ? `[${ETIQUETA_CAMPO_PLANTILLA[campo]}]` : todo;
  });
}

/** Elige si el cliente escribió alguna vez (para el cierre): nueva `ventana_expira_en` o conversación iniciada por él. */
export function huboEntrantes(c: Pick<Conversacion, 'iniciada_por' | 'ventana_expira_en'>): boolean {
  return c.iniciada_por === 'cliente' || c.ventana_expira_en !== null;
}

/** Combina mensajes por `id` (los nuevos reemplazan a los existentes) y ordena de forma ascendente. */
export function fusionarMensajes(actuales: Mensaje[], nuevos: Mensaje[]): Mensaje[] {
  const mapa = new Map<number, Mensaje>();
  for (const m of actuales) mapa.set(m.id, m);
  for (const m of nuevos) mapa.set(m.id, m);
  return [...mapa.values()].sort((a, b) => a.id - b.id);
}

export const MAX_TEXTO_POR_DEFECTO = 4096;
