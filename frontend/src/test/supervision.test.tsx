import { screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgenteSupervision } from '../api/tipos';
import {
  abrirSocket, emitirEvento, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch,
  WebSocketFalso,
} from './utiles';
import { act } from '@testing-library/react';

const agentes: AgenteSupervision[] = [
  { usuario_id: 5, nombre: 'Pedro Agente', estado: 'en_llamada', desde: '2026-10-23T14:58:00Z', motivo_pausa: null, campanas: [1, 3],
    llamada: { id: 31, estado: 'en_curso', campana_id: 1, campana_nombre: 'Cobranza cartera octubre' } },
  { usuario_id: 6, nombre: 'Sara Agente', estado: 'pausa', desde: '2026-10-23T14:50:00Z', motivo_pausa: 'almuerzo', campanas: [1], llamada: null },
  { usuario_id: 7, nombre: 'Zoe Agente', estado: 'desconectado', desde: '2026-10-23T10:00:00Z', motivo_pausa: null, campanas: [], llamada: null },
];

function fila(nombre: string) {
  return screen.getByRole('rowheader', { name: nombre }).closest('tr') as HTMLElement;
}

beforeEach(() => {
  instalarWebSocketFalso();
  simularFetch((url) => (url === '/api/v1/supervision/agentes' ? respuesta(200, agentes) : undefined));
});
afterEach(() => vi.useRealTimers());

describe('Supervisión de agentes', () => {
  it('lista agentes con estado, motivo de pausa, llamada actual y conteos', async () => {
    iniciarSesionComo('supervisor');
    renderizarAppTiempoReal('/supervision/agentes');
    await screen.findByRole('rowheader', { name: 'Pedro Agente' });
    expect(within(fila('Pedro Agente')).getByText('En llamada')).toBeInTheDocument();
    expect(within(fila('Pedro Agente')).getByText('Cobranza cartera octubre: En curso')).toBeInTheDocument();
    expect(fila('Sara Agente')).toHaveTextContent('En pausa (Almuerzo)');
    expect(within(fila('Zoe Agente')).getByText('Desconectado')).toBeInTheDocument();
    const conteos = screen.getByLabelText('Agentes por estado');
    for (const [estado, n] of [['En llamada', '1'], ['En pausa', '1'], ['Desconectado', '1'], ['Disponible', '0']]) {
      expect(within(conteos).getByText(estado).nextElementSibling).toHaveTextContent(n);
    }
  });

  it('el agente no accede a la supervisión', async () => {
    iniciarSesionComo('agente');
    renderizarAppTiempoReal('/supervision/agentes');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
  });

  it('el contador de tiempo en estado avanza en vivo', async () => {
    iniciarSesionComo('administrador');
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-23T15:00:00Z'));
    renderizarAppTiempoReal('/supervision/agentes');
    const f = await screen.findByRole('rowheader', { name: 'Pedro Agente' });
    expect(within(f.closest('tr')!).getByText('00:02:00')).toBeInTheDocument();
    vi.setSystemTime(new Date('2026-10-23T15:00:05Z'));
    await waitFor(() => expect(within(fila('Pedro Agente')).getByText('00:02:05')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('se actualiza por agente.estado y llamada.estado', async () => {
    iniciarSesionComo('supervisor');
    renderizarAppTiempoReal('/supervision/agentes');
    await screen.findByRole('rowheader', { name: 'Pedro Agente' });
    const ws = await abrirSocket(2, 'supervisor');

    emitirEvento(ws, { tipo: 'agente.estado', datos: { usuario_id: 7, estado: 'disponible', desde: '2026-10-23T15:00:00Z', motivo_pausa: null, llamada_id: null } });
    expect(within(fila('Zoe Agente')).getByText('Disponible')).toBeInTheDocument();

    emitirEvento(ws, { tipo: 'agente.estado', datos: { usuario_id: 6, estado: 'pausa', desde: '2026-10-23T15:01:00Z', motivo_pausa: 'reunion', llamada_id: null } });
    expect(fila('Sara Agente')).toHaveTextContent('En pausa (Reunión)');

    emitirEvento(ws, { tipo: 'llamada.estado', datos: { llamada_id: 31, usuario_id: 5, campana_id: 1, campana_cliente_id: 15, estado: 'completada', motivos: [] } });
    expect(within(fila('Pedro Agente')).queryByText(/Cobranza cartera octubre/)).not.toBeInTheDocument();
    emitirEvento(ws, { tipo: 'agente.estado', datos: { usuario_id: 5, estado: 'tipificando', desde: '2026-10-23T15:02:00Z', motivo_pausa: null, llamada_id: 31 } });
    expect(within(fila('Pedro Agente')).getByText('Tipificando')).toBeInTheDocument();

    emitirEvento(ws, { tipo: 'llamada.estado', datos: { llamada_id: 50, usuario_id: 6, campana_id: 1, campana_cliente_id: 16, estado: 'sonando', motivos: [] } });
    expect(fila('Sara Agente')).toHaveTextContent('Sonando');
  });

  it('al reconectar recarga el estado por REST', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch((url) => (url === '/api/v1/supervision/agentes' ? respuesta(200, agentes) : undefined));
    renderizarAppTiempoReal('/supervision/agentes');
    await screen.findByRole('rowheader', { name: 'Pedro Agente' });
    const ws = await abrirSocket(2, 'supervisor');
    act(() => ws.caer(1006));
    await waitFor(() => expect(WebSocketFalso.instancias.length).toBe(2), { timeout: 3000 });
    const antes = m.mock.calls.length;
    await abrirSocket(2, 'supervisor');
    await waitFor(() => expect(m.mock.calls.length).toBeGreaterThan(antes));
  });
});
