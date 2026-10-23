import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { App } from '../App';
import { AuthProvider } from '../auth/AuthContext';
import { guardarSesion } from '../api/sesion';
import type { Campana, Rol, Usuario } from '../api/tipos';

export function respuesta(status: number, cuerpo?: unknown): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function errorApi(status: number, codigo: string, mensaje: string, detalles: { campo: string | null; mensaje: string }[] = []) {
  return respuesta(status, { error: { codigo, mensaje, detalles } });
}

export function usuarioDe(rol: Rol): Usuario {
  return { id: 1, email: `${rol}@empresa.co`, nombre: `Usuario ${rol}`, rol, activo: true };
}

export function iniciarSesionComo(rol: Rol): Usuario {
  const usuario = usuarioDe(rol);
  guardarSesion({ token: 'token-de-prueba', usuario });
  return usuario;
}

export type Manejador = (url: string, init: RequestInit) => Response | Promise<Response> | undefined;

/** Simula fetch: el primer manejador que devuelva respuesta gana; si ninguno, 404. */
export function simularFetch(...manejadores: Manejador[]) {
  const mock = vi.fn(async (entrada: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(entrada);
    for (const m of manejadores) {
      const r = await m(url, init);
      if (r) return r;
    }
    return errorApi(404, 'NO_ENCONTRADO', `Sin simulación para ${url}`);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

export function renderizarApp(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

export function campanaEjemplo(sobrescribir: Partial<Campana> = {}): Campana {
  return {
    id: 5, nombre: 'Cobranza octubre', tipo: 'cobranza', descripcion: null, estado: 'borrador',
    fecha_inicio: null, fecha_fin: null, guion: null, max_intentos: 3, intervalo_reintento_minutos: 60,
    total_clientes: 0, creado_por: 1, creado_en: '2026-10-23T15:00:00Z', actualizado_en: '2026-10-23T15:00:00Z',
    ...sobrescribir,
  };
}

export const paginaVacia = { items: [], total: 0, page: 1, page_size: 20 };
