import { act, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { App } from '../App';
import { AuthProvider } from '../auth/AuthContext';
import { guardarSesion } from '../api/sesion';
import { TiempoRealProvider } from '../tiempo_real/TiempoRealContext';
import type { Campana, EventoTiempoReal, Rol, Usuario } from '../api/tipos';

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

/** Como `renderizarApp`, pero con el proveedor de tiempo real (requiere `instalarWebSocketFalso()`). */
export function renderizarAppTiempoReal(ruta: string) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <TiempoRealProvider>
          <App />
        </TiempoRealProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

/** WebSocket simulado: el test decide cuándo se abre, qué recibe y cómo se cierra. */
export class WebSocketFalso {
  static instancias: WebSocketFalso[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  enviados: string[] = [];
  cerrado = false;

  constructor(public url: string) {
    WebSocketFalso.instancias.push(this);
  }

  send(datos: string) {
    this.enviados.push(datos);
  }

  close() {
    this.cerrado = true;
  }

  abrir() {
    this.onopen?.({});
  }

  recibir(mensaje: unknown) {
    this.onmessage?.({ data: typeof mensaje === 'string' ? mensaje : JSON.stringify(mensaje) });
  }

  caer(codigo = 1006) {
    this.onclose?.({ code: codigo });
  }

  static ultima(): WebSocketFalso {
    return WebSocketFalso.instancias[WebSocketFalso.instancias.length - 1];
  }
}

export function instalarWebSocketFalso() {
  WebSocketFalso.instancias = [];
  vi.stubGlobal('WebSocket', WebSocketFalso);
}

/** Abre el último socket y envía `conexion.lista`, dentro de `act`. */
export function abrirSocket(usuarioId = 1, rol: Rol = 'agente') {
  const ws = WebSocketFalso.ultima();
  act(() => {
    ws.abrir();
    ws.recibir({ tipo: 'conexion.lista', datos: { usuario_id: usuarioId, rol }, emitido_en: '2026-10-23T15:00:00Z' });
  });
  return ws;
}

export function emitirEvento(ws: WebSocketFalso, evento: Omit<EventoTiempoReal, 'emitido_en'>) {
  act(() => ws.recibir({ ...evento, emitido_en: '2026-10-23T15:00:01Z' }));
}
