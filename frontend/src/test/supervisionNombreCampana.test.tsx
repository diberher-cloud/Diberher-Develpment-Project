import { act, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgenteSupervision } from '../api/tipos';
import {
  abrirSocket, emitirEvento, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch,
} from './utiles';

// Regresión de integración (E2E con Chromium real): al iniciar una llamada, el supervisor veía
// "Campaña #1: En curso" en lugar del nombre porque el indicador `nombreDesconocido` se evalúa antes
// de que React ejecute la función de actualización de estado, y la recarga por REST nunca ocurría.
const antes: AgenteSupervision[] = [
  { usuario_id: 5, nombre: 'Pedro Agente', estado: 'disponible', desde: '2026-10-23T14:58:00Z', motivo_pausa: null, campanas: [1], llamada: null },
];
const durante: AgenteSupervision[] = [
  { ...antes[0], estado: 'en_llamada', llamada: { id: 31, estado: 'iniciando', campana_id: 1, campana_nombre: 'Cobranza cartera octubre' } },
];

beforeEach(() => instalarWebSocketFalso());
afterEach(() => vi.useRealTimers());

describe('Supervisión: nombre de la campaña en la llamada actual', () => {
  it('muestra el nombre de la campaña (no "Campaña #id") cuando la llamada empieza estando en vivo', async () => {
    iniciarSesionComo('supervisor');
    let respuestaActual = antes;
    const m = simularFetch((url) => (url === '/api/v1/supervision/agentes' ? respuesta(200, respuestaActual) : undefined));
    renderizarAppTiempoReal('/supervision/agentes');
    await screen.findByRole('rowheader', { name: 'Pedro Agente' });
    const ws = abrirSocket(2, 'supervisor');

    respuestaActual = durante; // lo que devolvería el servidor ahora
    const llamadasAntes = m.mock.calls.length;
    act(() => {
      emitirEvento(ws, { tipo: 'agente.estado', datos: { usuario_id: 5, estado: 'en_llamada', desde: '2026-10-23T15:00:00Z', motivo_pausa: null, llamada_id: 31 } });
      emitirEvento(ws, { tipo: 'llamada.estado', datos: { llamada_id: 31, usuario_id: 5, campana_id: 1, campana_cliente_id: 15, estado: 'iniciando', motivos: [] } });
    });
    const fila = screen.getByRole('rowheader', { name: 'Pedro Agente' }).closest('tr') as HTMLElement;
    await waitFor(() => expect(within(fila).getByText(/Cobranza cartera octubre/)).toBeInTheDocument(), { timeout: 3000 });
    expect(m.mock.calls.length).toBeGreaterThan(llamadasAntes);
    expect(within(fila).queryByText(/Campaña #1/)).not.toBeInTheDocument();
  });
});
