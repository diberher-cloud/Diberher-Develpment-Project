import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../auth/AuthContext';
import { CLAVE_SESION } from '../api/sesion';
import type { EventoTiempoReal } from '../api/tipos';
import { ErrorApi } from '../api/cliente';
import { conectar } from '../tiempo_real/conexion';
import { TiempoRealProvider, useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { errorApi, iniciarSesionComo, instalarWebSocketFalso, simularFetch, WebSocketFalso } from './utiles';

const lista = { tipo: 'conexion.lista', datos: { usuario_id: 1, rol: 'agente' }, emitido_en: '2026-10-23T15:00:00Z' };

describe('conexion WebSocket (cliente)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    instalarWebSocketFalso();
  });
  afterEach(() => vi.useRealTimers());

  let n = 0;
  async function abrir(extra: Partial<Parameters<typeof conectar>[0]> = {}) {
    const eventos: EventoTiempoReal[] = [];
    const sesionInvalida = vi.fn();
    const alReconectar = vi.fn();
    const estados: string[] = [];
    const obtenerTicket = vi.fn(async () => ({ ticket: `tk/${++n}` }));
    const c = conectar({
      obtenerTicket, alEvento: (e) => eventos.push(e), alSesionInvalida: sesionInvalida, alReconectar,
      alEstado: (e) => estados.push(e), ...extra,
    });
    await vi.advanceTimersByTimeAsync(0);
    return { c, eventos, sesionInvalida, alReconectar, estados, obtenerTicket };
  }

  /** Avanza el reloj hasta que aparece un socket nuevo; devuelve los ms esperados. */
  async function esperarSocketNuevo(): Promise<number> {
    const antes = WebSocketFalso.instancias.length;
    let t = 0;
    while (WebSocketFalso.instancias.length === antes && t < 60_000) {
      await vi.advanceTimersByTimeAsync(100);
      t += 100;
    }
    return t;
  }

  it('conecta con ?ticket= (URL codificada) y nunca envía token=', async () => {
    const { obtenerTicket } = await abrir();
    expect(obtenerTicket).toHaveBeenCalledTimes(1);
    expect(WebSocketFalso.instancias).toHaveLength(1);
    expect(WebSocketFalso.ultima().url).toMatch(/^wss?:\/\/.+\/api\/v1\/ws\?ticket=tk%2F\d+$/);
    expect(WebSocketFalso.instancias.every((w) => !w.url.includes('token='))).toBe(true);
  });

  it('despacha los eventos por tipo, ignora pong y mensajes inválidos', async () => {
    const { eventos, estados } = await abrir();
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    ws.recibir(lista);
    ws.recibir({ tipo: 'pong', datos: {}, emitido_en: 'x' });
    ws.recibir('no es json');
    ws.recibir({ sin: 'tipo' });
    ws.recibir({ tipo: 'agente.estado', datos: { usuario_id: 1, estado: 'disponible' }, emitido_en: 'x' });
    expect(eventos.map((e) => e.tipo)).toEqual(['conexion.lista', 'agente.estado']);
    expect(estados).toContain('conectada');
  });

  it('envía ping cada 30 s mientras está abierta', async () => {
    await abrir();
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    await vi.advanceTimersByTimeAsync(29_999);
    expect(ws.enviados).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(ws.enviados).toEqual(['{"tipo":"ping"}']);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(ws.enviados).toHaveLength(2);
  });

  it('reconecta con backoff 1 s, 2 s, 4 s... hasta 30 s, con un ticket nuevo en cada intento', async () => {
    const { alReconectar, obtenerTicket } = await abrir();
    const esperas: number[] = [];
    for (let i = 0; i < 7; i++) {
      WebSocketFalso.ultima().caer();
      esperas.push(await esperarSocketNuevo());
    }
    expect(esperas).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);
    expect(obtenerTicket).toHaveBeenCalledTimes(8);
    const tickets = WebSocketFalso.instancias.map((w) => new URL(w.url).searchParams.get('ticket'));
    expect(new Set(tickets).size).toBe(8); // nunca se reutiliza un ticket

    // Al abrir y recibir `conexion.lista` se reinicia el backoff y se avisa de la reconexión.
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    ws.recibir(lista);
    expect(alReconectar).not.toHaveBeenCalled(); // era la primera conexión lista
    ws.caer();
    expect(await esperarSocketNuevo()).toBe(1000);
    const ws2 = WebSocketFalso.ultima();
    ws2.abrir();
    ws2.recibir(lista);
    expect(alReconectar).toHaveBeenCalledTimes(1);
  });

  it('si el ticket falla por red, reintenta con backoff sin abrir socket', async () => {
    let fallos = 2;
    const obtenerTicket = vi.fn(async () => {
      if (fallos-- > 0) throw new ErrorApi(0, 'RED', 'sin red');
      return { ticket: 'ok' };
    });
    await abrir({ obtenerTicket });
    expect(WebSocketFalso.instancias).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(obtenerTicket).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2000);
    expect(WebSocketFalso.instancias).toHaveLength(1);
  });

  it('un 401 al pedir el ticket avisa de sesión inválida y no reintenta', async () => {
    const obtenerTicket = vi.fn(async () => {
      throw new ErrorApi(401, 'NO_AUTENTICADO', 'Sesión vencida');
    });
    const { sesionInvalida } = await abrir({ obtenerTicket });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(sesionInvalida).toHaveBeenCalledTimes(1);
    expect(obtenerTicket).toHaveBeenCalledTimes(1);
    expect(WebSocketFalso.instancias).toHaveLength(0);
  });

  it('un cierre 4401 pide un ticket nuevo una vez; un segundo 4401 avisa de sesión inválida', async () => {
    const { sesionInvalida, obtenerTicket } = await abrir();
    WebSocketFalso.ultima().caer(4401);
    await vi.advanceTimersByTimeAsync(0);
    expect(sesionInvalida).not.toHaveBeenCalled();
    expect(obtenerTicket).toHaveBeenCalledTimes(2);
    expect(WebSocketFalso.instancias).toHaveLength(2);
    WebSocketFalso.ultima().caer(4401);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(sesionInvalida).toHaveBeenCalledTimes(1);
    expect(obtenerTicket).toHaveBeenCalledTimes(2);
    expect(WebSocketFalso.instancias).toHaveLength(2);
  });

  it('tras un 4401 seguido de una conexión correcta, un 4401 posterior vuelve a reintentar una vez', async () => {
    const { sesionInvalida } = await abrir();
    WebSocketFalso.ultima().caer(4401);
    await vi.advanceTimersByTimeAsync(0);
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    ws.recibir(lista);
    ws.caer(4401);
    await vi.advanceTimersByTimeAsync(0);
    expect(sesionInvalida).not.toHaveBeenCalled();
    expect(WebSocketFalso.instancias).toHaveLength(3);
  });

  it('cerrar() detiene ping y reconexión, y evita abrir un socket si el ticket llega tarde', async () => {
    const { c } = await abrir();
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    c.cerrar();
    expect(ws.cerrado).toBe(true);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(ws.enviados).toHaveLength(0);
    expect(WebSocketFalso.instancias).toHaveLength(1);

    let liberar: (t: { ticket: string }) => void = () => {};
    const lento = conectar({
      obtenerTicket: () => new Promise((r) => { liberar = r; }), alEvento: () => {}, alSesionInvalida: () => {},
    });
    lento.cerrar();
    liberar({ ticket: 'tarde' });
    await vi.advanceTimersByTimeAsync(0);
    expect(WebSocketFalso.instancias).toHaveLength(1);
  });
});

function Sonda({ alEvento }: { alEvento: (e: EventoTiempoReal) => void }) {
  useEventoTiempoReal('consola.registro', alEvento);
  const { estado, reconexiones } = useConexionTiempoReal();
  return <p>estado:{estado} reconexiones:{reconexiones}</p>;
}

describe('TiempoRealProvider', () => {
  beforeEach(() => instalarWebSocketFalso());
  const esperarSocket = () => waitFor(() => expect(WebSocketFalso.instancias.length).toBeGreaterThan(0));

  it('entrega a cada suscriptor solo los eventos de su tipo y cuenta reconexiones', async () => {
    iniciarSesionComo('agente');
    simularFetch();
    const alEvento = vi.fn();
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={alEvento} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    await esperarSocket();
    const ws = WebSocketFalso.ultima();
    act(() => {
      ws.abrir();
      ws.recibir(lista);
      ws.recibir({ tipo: 'agente.estado', datos: {}, emitido_en: 'x' });
      ws.recibir({ tipo: 'consola.registro', datos: { campana_id: 1, campana_cliente_id: 15, accion: 'reservado' }, emitido_en: 'x' });
    });
    expect(alEvento).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('estado:conectada reconexiones:0')).toBeInTheDocument();
  });

  it('dos cierres 4401 seguidos limpian la sesión', async () => {
    iniciarSesionComo('agente');
    simularFetch();
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={() => {}} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    await esperarSocket();
    expect(sessionStorage.getItem(CLAVE_SESION)).not.toBeNull();
    act(() => WebSocketFalso.ultima().caer(4401));
    await waitFor(() => expect(WebSocketFalso.instancias).toHaveLength(2));
    expect(sessionStorage.getItem(CLAVE_SESION)).not.toBeNull();
    act(() => WebSocketFalso.ultima().caer(4401));
    await waitFor(() => expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull());
  });

  it('un 401 al pedir el ticket limpia la sesión sin abrir socket', async () => {
    iniciarSesionComo('agente');
    simularFetch((url) => (url === '/api/v1/ws/ticket' ? errorApi(401, 'NO_AUTENTICADO', 'Sesión vencida') : undefined));
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={() => {}} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    await waitFor(() => expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull());
    expect(WebSocketFalso.instancias).toHaveLength(0);
  });

  it('el ticket se pide por POST /ws/ticket con Bearer y la URL no contiene token=', async () => {
    iniciarSesionComo('agente');
    const m = simularFetch();
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={() => {}} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    await esperarSocket();
    const [url, init] = m.mock.calls[0];
    expect(String(url)).toBe('/api/v1/ws/ticket');
    expect(init?.method).toBe('POST');
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer token-de-prueba');
    expect(WebSocketFalso.ultima().url).toMatch(/\?ticket=ticket-\d+$/);
    expect(WebSocketFalso.ultima().url).not.toContain('token');
  });

  it('sin sesión no abre el socket', () => {
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={() => {}} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    expect(WebSocketFalso.instancias).toHaveLength(0);
  });
});
