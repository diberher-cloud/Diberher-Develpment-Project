import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TokenTelefonia } from '../api/tipos';
import { crearSoftphone } from '../telefonia/crearSoftphone';
import { esSimulable, type EstadoSoftphone } from '../telefonia/softphone';
import { SoftphoneFalso } from '../telefonia/softphoneFalso';
import { SoftphoneTwilio } from '../telefonia/softphoneTwilio';
import { iniciarSesionComo, respuesta, simularFetch } from './utiles';

// --- Simulación de @twilio/voice-sdk -------------------------------------------------------------
type Oyentes = Record<string, ((...a: unknown[]) => void)[]>;
class LlamadaSim {
  oyentes: Oyentes = {};
  mute = vi.fn();
  disconnect = vi.fn(() => this.emitir('disconnect'));
  on(e: string, f: (...a: unknown[]) => void) {
    (this.oyentes[e] ??= []).push(f);
    return this;
  }
  emitir(e: string, ...a: unknown[]) {
    (this.oyentes[e] ?? []).forEach((f) => f(...a));
  }
}
const sdk = vi.hoisted(() => ({ dispositivos: [] as unknown[] }));
vi.mock('@twilio/voice-sdk', () => {
  class Device {
    oyentes: Record<string, ((...a: unknown[]) => void)[]> = {};
    llamada: unknown = null;
    updateToken = vi.fn();
    destroy = vi.fn();
    disconnectAll = vi.fn();
    register = vi.fn(async () => this.emitir('registered'));
    state = 'unregistered';
    connect = vi.fn(async () => {
      this.llamada = new (globalThis as unknown as { __LlamadaSim: new () => unknown }).__LlamadaSim();
      return this.llamada;
    });
    constructor(public token: string, public opciones: unknown) {
      sdk.dispositivos.push(this);
    }
    on(e: string, f: (...a: unknown[]) => void) {
      (this.oyentes[e] ??= []).push(f);
      return this;
    }
    emitir(e: string, ...a: unknown[]) {
      (this.oyentes[e] ?? []).forEach((f) => f(...a));
    }
  }
  return { Device };
});

interface DispositivoSim {
  token: string; opciones: unknown; llamada: LlamadaSim; updateToken: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>; register: ReturnType<typeof vi.fn>; connect: ReturnType<typeof vi.fn>; emitir: (e: string, ...a: unknown[]) => void;
}
const ultimoDispositivo = () => sdk.dispositivos[sdk.dispositivos.length - 1] as DispositivoSim;

const tokenTwilio: TokenTelefonia = { proveedor: 'twilio', token: 'jwt-1', identity: 'agente_5', expira_en: '2026-10-23T16:00:00Z' };
const tokenFalso: TokenTelefonia = { proveedor: 'falso', token: 'falso.agente_5.abc', identity: 'agente_5', expira_en: '2026-10-23T16:00:00Z' };

function estados(s: { onEstado: (cb: (e: EstadoSoftphone, d?: string) => void) => () => void }) {
  const lista: string[] = [];
  s.onEstado((e) => lista.push(e));
  return lista;
}

beforeEach(() => {
  sdk.dispositivos = [];
  (globalThis as unknown as { __LlamadaSim: unknown }).__LlamadaSim = LlamadaSim;
});

describe('crearSoftphone', () => {
  it('elige la implementación según el proveedor del token', async () => {
    expect(await crearSoftphone(async () => tokenFalso)).toBeInstanceOf(SoftphoneFalso);
    expect(await crearSoftphone(async () => tokenTwilio)).toBeInstanceOf(SoftphoneTwilio);
  });

  it('usa POST /telefonia/token por defecto', async () => {
    iniciarSesionComo('agente');
    const m = simularFetch((url, init) => (url === '/api/v1/telefonia/token' && init.method === 'POST' ? respuesta(200, tokenFalso) : undefined));
    expect(await crearSoftphone()).toBeInstanceOf(SoftphoneFalso);
    expect(m).toHaveBeenCalledTimes(1);
  });
});

describe('SoftphoneFalso', () => {
  function api(permitida: boolean) {
    iniciarSesionComo('agente');
    return simularFetch(
      (url, init) => {
        if (url === '/api/v1/telefonia/simulacion/llamadas' && init.method === 'POST') {
          return respuesta(200, permitida
            ? { llamada_id: 31, permitida: true, motivos: [] }
            : { llamada_id: 32, permitida: false, motivos: [{ codigo: 'FUERA_DE_FRANJA', mensaje: 'Fuera de franja.' }] });
        }
        if (/\/simulacion\/llamadas\/\d+\/eventos$/.test(url)) return respuesta(204);
        return undefined;
      },
    );
  }

  it('simula la llamada de punta a punta: llamar, contestar y colgar', async () => {
    const m = api(true);
    const sp = new SoftphoneFalso(tokenFalso);
    const lista = estados(sp);
    expect(esSimulable(sp)).toBe(true);
    await sp.iniciar();
    await sp.llamar({ campana_cliente_id: 15, telefono_id: 21 });
    await sp.simular({ evento: 'contestada' });
    sp.colgar();
    await vi.waitFor(() => expect(lista.at(-1)).toBe('finalizada'));
    expect(lista).toEqual(['registrando', 'listo', 'conectando', 'en_curso', 'finalizada']);

    const cuerpos = m.mock.calls.map(([u, i]) => [String(u), i?.method, i?.body ? JSON.parse(String(i.body)) : null]);
    expect(cuerpos[0]).toEqual(['/api/v1/telefonia/simulacion/llamadas', 'POST', { campana_cliente_id: 15, telefono_id: 21 }]);
    expect(cuerpos[1]).toEqual(['/api/v1/telefonia/simulacion/llamadas/31/eventos', 'POST', { evento: 'contestada' }]);
    expect(cuerpos[2][2]).toMatchObject({ evento: 'finalizada', resultado: 'completed' });
    expect(typeof (cuerpos[2][2] as { duracion_segundos: number }).duracion_segundos).toBe('number');
  });

  it('una llamada no permitida termina como finalizada con los motivos', async () => {
    api(false);
    const sp = new SoftphoneFalso(tokenFalso);
    const detalles: (string | undefined)[] = [];
    sp.onEstado((_e, d) => detalles.push(d));
    await sp.iniciar();
    await sp.llamar({ campana_cliente_id: 15, telefono_id: 21 });
    expect(detalles.at(-1)).toBe('Fuera de franja.');
    expect(sp.motivosBloqueo.map((m) => m.codigo)).toEqual(['FUERA_DE_FRANJA']);
  });

  it('un error de la API deja el softphone en error', async () => {
    iniciarSesionComo('agente');
    simularFetch(() => respuesta(409, { error: { codigo: 'AGENTE_EN_LLAMADA', mensaje: 'En llamada.', detalles: [] } }));
    const sp = new SoftphoneFalso(tokenFalso);
    const lista = estados(sp);
    await sp.llamar({ campana_cliente_id: 15, telefono_id: 21 });
    expect(lista.at(-1)).toBe('error');
  });
});

describe('SoftphoneTwilio', () => {
  it('crea el dispositivo con códecs y closeProtection, sin registrarlo, y queda listo', async () => {
    const sp = new SoftphoneTwilio(tokenTwilio, async () => tokenTwilio);
    const lista = estados(sp);
    await sp.iniciar();
    const d = ultimoDispositivo();
    expect(d.token).toBe('jwt-1');
    expect(d.opciones).toEqual({ codecPreferences: ['opus', 'pcmu'], closeProtection: true });
    expect(d.register).not.toHaveBeenCalled(); // solo hace falta para llamadas entrantes
    expect(lista).toEqual(['registrando', 'listo']);
  });

  it('envía los parámetros como strings y sigue el ciclo accept -> disconnect', async () => {
    const sp = new SoftphoneTwilio(tokenTwilio, async () => tokenTwilio);
    const lista = estados(sp);
    await sp.iniciar();
    await sp.llamar({ campana_cliente_id: 15, telefono_id: 21 });
    const d = ultimoDispositivo();
    expect(d.connect).toHaveBeenCalledWith({ params: { campana_cliente_id: '15', telefono_id: '21' } });
    d.llamada.emitir('accept');
    sp.silenciar(true);
    expect(d.llamada.mute).toHaveBeenCalledWith(true);
    sp.silenciar(false);
    expect(d.llamada.mute).toHaveBeenLastCalledWith(false);
    sp.colgar();
    expect(d.llamada.disconnect).toHaveBeenCalled();
    expect(lista).toEqual(['registrando', 'listo', 'conectando', 'en_curso', 'finalizada']);
  });

  it('una llamada cancelada o con error se refleja en el estado', async () => {
    const sp = new SoftphoneTwilio(tokenTwilio, async () => tokenTwilio);
    const lista = estados(sp);
    await sp.iniciar();
    await sp.llamar({ campana_cliente_id: 1, telefono_id: 2 });
    ultimoDispositivo().llamada.emitir('cancel');
    await sp.llamar({ campana_cliente_id: 1, telefono_id: 2 });
    ultimoDispositivo().llamada.emitir('error', { message: 'Sin micrófono' });
    expect(lista.slice(-3)).toEqual(['finalizada', 'conectando', 'error']);
  });

  it('renueva el token cuando el SDK avisa tokenWillExpire', async () => {
    const nuevo = { ...tokenTwilio, token: 'jwt-2' };
    const obtener = vi.fn(async () => nuevo);
    const sp = new SoftphoneTwilio(tokenTwilio, obtener);
    await sp.iniciar();
    ultimoDispositivo().emitir('tokenWillExpire');
    await vi.waitFor(() => expect(ultimoDispositivo().updateToken).toHaveBeenCalledWith('jwt-2'));
    expect(obtener).toHaveBeenCalledTimes(1);
  });

  it('un error del dispositivo deja el estado en error y destruir() libera el dispositivo', async () => {
    const sp = new SoftphoneTwilio(tokenTwilio, async () => tokenTwilio);
    const lista = estados(sp);
    await sp.iniciar();
    ultimoDispositivo().emitir('error', { message: 'Token inválido' });
    expect(lista.at(-1)).toBe('error');
    sp.destruir();
    expect(ultimoDispositivo().destroy).toHaveBeenCalled();
  });
});
