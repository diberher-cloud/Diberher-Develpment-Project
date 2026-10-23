import type { Usuario } from './tipos';

export interface Sesion { token: string; usuario: Usuario }

export const CLAVE_SESION = 'outbound.sesion';

type Oyente = () => void;
const oyentes = new Set<Oyente>();

export function leerSesion(): Sesion | null {
  try {
    const crudo = sessionStorage.getItem(CLAVE_SESION);
    if (!crudo) return null;
    const s = JSON.parse(crudo) as Sesion;
    return s && typeof s.token === 'string' && s.usuario ? s : null;
  } catch {
    return null;
  }
}

export function guardarSesion(sesion: Sesion): void {
  sessionStorage.setItem(CLAVE_SESION, JSON.stringify(sesion));
}

export function limpiarSesion(): void {
  sessionStorage.removeItem(CLAVE_SESION);
  oyentes.forEach((o) => o());
}

/** Suscripción a cierres de sesión (401 o cierre manual). Devuelve la función de baja. */
export function alLimpiarSesion(oyente: Oyente): () => void {
  oyentes.add(oyente);
  return () => {
    oyentes.delete(oyente);
  };
}
