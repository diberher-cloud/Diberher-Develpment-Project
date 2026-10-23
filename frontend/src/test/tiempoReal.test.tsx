import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../auth/AuthContext';
import { CLAVE_SESION } from '../api/sesion';
import type { EventoTiempoReal } from '../api/tipos';
import { conectar } from '../tiempo_real/conexion';
import { TiempoRealProvider, useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { iniciarSesionComo, instalarWebSocketFalso, WebSocketFalso } from './utiles';

const lista = { tipo: 'conexion.lista', datos: { usuario_id: 1, rol: 'agente' }, emitido_en: '2026-10-23T15:00:00Z' };

describe('conexion WebSocket (cliente)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    instalarWebSocketFalso();
  });
  afterEach(() => vi.useRealTimers());

  function abrir(extra: Partial<Parameters<typeof conectar>[0]> = {}) {
    const eventos: EventoTiempoReal[] = [];
    const sesionInvalida = vi.fn();
    const alReconectar = vi.fn();
    const estados: string[] = [];
    const c = conectar({
      token: 'tok/en', alEvento: (e) => eventos.push(e), alSesionInvalida: sesionInvalida, alReconectar,
      alEstado: (e) => estados.push(e), ...extra,
    });
    return { c, eventos, sesionInvalida, alReconectar, estados };
  }

  it('conecta a /api/v1/ws con el token en la query', () => {
    abrir();
    expect(WebSocketFalso.instancias).toHaveLength(1);
    expect(WebSocketFalso.ultima().url).toMatch(/^wss?:\/\/.+\/api\/v1\/ws\?token=tok%2Fen$/);
  });

  it('despacha los eventos por tipo, ignora pong y mensajes inválidos', () => {
    const { eventos, estados } = abrir();
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

  it('envía ping cada 30 s mientras está abierta', () => {
    abrir();
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    vi.advanceTimersByTime(29_999);
    expect(ws.enviados).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(ws.enviados).toEqual(['{"tipo":"ping"}']);
    vi.advanceTimersByTime(30_000);
    expect(ws.enviados).toHaveLength(2);
  });

  it('reconecta con backoff 1 s, 2 s, 4 s... hasta 30 s y reinicia el backoff al abrir', () => {
    const { alReconectar } = abrir();
    const esperas: number[] = [];
    for (let i = 0; i < 7; i++) {
      const n = WebSocketFalso.instancias.length;
      WebSocketFalso.ultima().caer();
      let t = 0;
      while (WebSocketFalso.instancias.length === n && t < 60_000) {
        vi.advanceTimersByTime(100);
        t += 100;
      }
      esperas.push(t);
    }
    expect(esperas).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);

    // Al abrir y recibir `conexion.lista` se reinicia el backoff y se avisa de la reconexión.
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    ws.recibir(lista);
    expect(alReconectar).not.toHaveBeenCalled(); // era la primera conexión lista
    const n = WebSocketFalso.instancias.length;
    ws.caer();
    vi.advanceTimersByTime(1000);
    expect(WebSocketFalso.instancias).toHaveLength(n + 1);
    const ws2 = WebSocketFalso.ultima();
    ws2.abrir();
    ws2.recibir(lista);
    expect(alReconectar).toHaveBeenCalledTimes(1);
  });

  it('el cierre 4401 avisa de sesión inválida y no reconecta', () => {
    const { sesionInvalida } = abrir();
    WebSocketFalso.ultima().caer(4401);
    vi.advanceTimersByTime(120_000);
    expect(sesionInvalida).toHaveBeenCalledTimes(1);
    expect(WebSocketFalso.instancias).toHaveLength(1);
  });

  it('cerrar() detiene ping y reconexión', () => {
    const { c } = abrir();
    const ws = WebSocketFalso.ultima();
    ws.abrir();
    c.cerrar();
    expect(ws.cerrado).toBe(true);
    vi.advanceTimersByTime(120_000);
    expect(ws.enviados).toHaveLength(0);
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

  it('entrega a cada suscriptor solo los eventos de su tipo y cuenta reconexiones', async () => {
    iniciarSesionComo('agente');
    const alEvento = vi.fn();
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={alEvento} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
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

  it('un cierre 4401 limpia la sesión', () => {
    iniciarSesionComo('agente');
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Sonda alEvento={() => {}} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    expect(sessionStorage.getItem(CLAVE_SESION)).not.toBeNull();
    act(() => WebSocketFalso.ultima().caer(4401));
    expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull();
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
