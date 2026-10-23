import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { momentoBogota } from '../utilidades/formato';
import { iniciarSesionComo, renderizarApp, respuesta, simularFetch } from './utiles';

describe('Evaluador de cumplimiento', () => {
  it('envía el momento con offset -05:00 y muestra motivos y próxima ventana', async () => {
    iniciarSesionComo('agente');
    const fetchMock = simularFetch(
      (url, init) =>
        url === '/api/v1/cumplimiento/evaluar' && init.method === 'POST'
          ? respuesta(200, {
              permitido: false,
              motivos: [{ codigo: 'FESTIVO', mensaje: '2026-11-02 es festivo (Todos los Santos).' }],
              momento_local: '2026-11-02T10:00:00-05:00',
              proxima_ventana_inicio: '2026-11-03T07:00:00-05:00',
              politica_version: 1,
            })
          : undefined,
      (url) => (url.startsWith('/api/v1/cumplimiento/politicas') || url.startsWith('/api/v1/festivos') ? respuesta(200, []) : undefined),
    );
    renderizarApp('/cumplimiento');
    const u = userEvent.setup();
    const campoMomento = await screen.findByLabelText(/Fecha y hora \(hora de Bogotá\)/);
    await u.type(campoMomento, '2026-11-02T10:00');
    await u.click(screen.getByRole('button', { name: 'Evaluar' }));

    expect(await screen.findByText('Llamada no permitida')).toBeInTheDocument();
    expect(screen.getByText(/es festivo \(Todos los Santos\)/)).toBeInTheDocument();
    expect(screen.getByText(/Próxima ventana:/)).toHaveTextContent('7:00');

    const llamada = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/evaluar'))!;
    const cuerpo = JSON.parse(llamada[1]!.body as string);
    expect(cuerpo).toEqual({ tipo_campana: 'cobranza', momento: '2026-11-02T10:00:00-05:00' });
    expect(cuerpo.momento.endsWith('-05:00')).toBe(true);
  });

  it('sin momento no envía el campo (el servidor usa "ahora")', async () => {
    iniciarSesionComo('supervisor');
    const fetchMock = simularFetch(
      (url, init) => (url.endsWith('/evaluar') && init.method === 'POST'
        ? respuesta(200, { permitido: true, motivos: [], momento_local: '2026-10-23T10:00:00-05:00', proxima_ventana_inicio: null, politica_version: 1 })
        : undefined),
      () => respuesta(200, []),
    );
    renderizarApp('/cumplimiento');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluar' }));
    expect(await screen.findByText('Llamada permitida')).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/evaluar'))).toBe(true));
    const llamada = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/evaluar'))!;
    expect(JSON.parse(llamada[1]!.body as string)).toEqual({ tipo_campana: 'cobranza' });
  });

  it('momentoBogota añade segundos y offset sin depender de la zona del navegador', () => {
    expect(momentoBogota('2026-11-02T10:00')).toBe('2026-11-02T10:00:00-05:00');
    expect(momentoBogota('2026-11-02T10:00:30')).toBe('2026-11-02T10:00:30-05:00');
  });
});
