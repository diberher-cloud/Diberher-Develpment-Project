import { BASE_API, ErrorApi } from '../api/cliente';
import type { EventoTiempoReal } from '../api/tipos';

export type EstadoConexion = 'conectando' | 'conectada' | 'reconectando' | 'cerrada';

export const CODIGO_TOKEN_INVALIDO = 4401;

/** Subconjunto de WebSocket que usa el cliente (facilita la simulación en tests). */
export interface SocketMinimo {
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(datos: string): void;
  close(codigo?: number): void;
}

export interface OpcionesConexion {
  /** Pide un ticket de un solo uso (`POST /ws/ticket`). Se invoca antes de CADA intento de conexión. */
  obtenerTicket: () => Promise<{ ticket: string }>;
  alEvento: (evento: EventoTiempoReal) => void;
  alEstado?: (estado: EstadoConexion) => void;
  /** Se invoca al recibir `conexion.lista` en una reconexión (hay que recargar el estado por REST). */
  alReconectar?: () => void;
  /** Cierre 4401: token inválido o vencido. */
  alSesionInvalida: () => void;
  crearSocket?: (url: string) => SocketMinimo;
  intervaloPingMs?: number;
  esperaInicialMs?: number;
  esperaMaximaMs?: number;
}

export interface Conexion { cerrar: () => void }

export function urlTiempoReal(ticket: string): string {
  const esquema = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${esquema}://${window.location.host}${BASE_API}/ws?ticket=${encodeURIComponent(ticket)}`;
}

function esEvento(x: unknown): x is EventoTiempoReal {
  return typeof x === 'object' && x !== null && typeof (x as { tipo?: unknown }).tipo === 'string';
}

/**
 * Conexión WebSocket con reconexión (backoff exponencial 1 s -> 30 s), latido `ping` cada 30 s y cierre de
 * sesión ante el código 4401 (fase-2.md §4.10, ADR-0004).
 */
export function conectar(opciones: OpcionesConexion): Conexion {
  const {
    obtenerTicket, alEvento, alEstado, alReconectar, alSesionInvalida,
    crearSocket = (url: string) => new WebSocket(url) as unknown as SocketMinimo,
    intervaloPingMs = 30_000, esperaInicialMs = 1_000, esperaMaximaMs = 30_000,
  } = opciones;

  let socket: SocketMinimo | null = null;
  let cerrada = false;
  let espera = esperaInicialMs;
  let temporizadorReconexion: ReturnType<typeof setTimeout> | undefined;
  let temporizadorPing: ReturnType<typeof setInterval> | undefined;
  let hubo = false; // ya hubo una conexión lista antes
  let reintentoPor4401 = false; // tras un 4401 se pide un ticket nuevo una sola vez

  const pararPing = () => {
    if (temporizadorPing !== undefined) clearInterval(temporizadorPing);
    temporizadorPing = undefined;
  };

  function sesionInvalida() {
    cerrada = true;
    alEstado?.('cerrada');
    alSesionInvalida();
  }

  async function abrir() {
    alEstado?.(hubo ? 'reconectando' : 'conectando');
    let ticket: string;
    try {
      ticket = (await obtenerTicket()).ticket;
    } catch (e) {
      if (cerrada) return;
      if (e instanceof ErrorApi && e.status === 401) sesionInvalida();
      else programarReconexion();
      return;
    }
    if (cerrada) return;
    let s: SocketMinimo;
    try {
      s = crearSocket(urlTiempoReal(ticket));
    } catch {
      programarReconexion();
      return;
    }
    socket = s;
    s.onopen = () => {
      espera = esperaInicialMs;
      pararPing();
      temporizadorPing = setInterval(() => {
        try {
          s.send(JSON.stringify({ tipo: 'ping' }));
        } catch {
          /* el cierre disparará la reconexión */
        }
      }, intervaloPingMs);
    };
    s.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!esEvento(msg)) return;
      if (msg.tipo === 'pong') return;
      if (msg.tipo === 'conexion.lista') {
        alEstado?.('conectada');
        const reconexion = hubo;
        hubo = true;
        reintentoPor4401 = false;
        alEvento(msg);
        if (reconexion) alReconectar?.();
        return;
      }
      alEvento(msg);
    };
    s.onclose = (ev) => {
      pararPing();
      if (socket === s) socket = null;
      if (cerrada) return;
      if (ev.code === CODIGO_TOKEN_INVALIDO) {
        if (reintentoPor4401) {
          sesionInvalida();
        } else {
          reintentoPor4401 = true;
          void abrir(); // un ticket nuevo, una sola vez
        }
        return;
      }
      programarReconexion();
    };
    s.onerror = () => {
      /* el evento close posterior gestiona la reconexión */
    };
  }

  function programarReconexion() {
    if (cerrada) return;
    alEstado?.('reconectando');
    const retraso = espera;
    espera = Math.min(espera * 2, esperaMaximaMs);
    temporizadorReconexion = setTimeout(() => void abrir(), retraso);
  }

  void abrir();

  return {
    cerrar() {
      cerrada = true;
      pararPing();
      if (temporizadorReconexion !== undefined) clearTimeout(temporizadorReconexion);
      const s = socket;
      socket = null;
      if (s) {
        s.onclose = null;
        s.onmessage = null;
        s.onerror = null;
        try {
          s.close(1000);
        } catch {
          /* nada */
        }
      }
      alEstado?.('cerrada');
    },
  };
}
