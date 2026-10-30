import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { EvaluacionIA } from '../api/tipos';
import {
  abrirSocket, campanaEjemplo, emitirEvento, errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch,
  type Manejador,
} from './utiles';
import { evaluacion, ruta, rutaJson } from './utilesIA';
import { consulta, pagina } from './utilesWhatsApp';

function servidor(inicial: EvaluacionIA[], extra: Manejador[] = []) {
  const e = { lista: inicial };
  const m = simularFetch(
    ...extra,
    rutaJson('GET', '/campanas', () => pagina([campanaEjemplo({ id: 1, nombre: 'Cobranza cartera octubre' })])),
    rutaJson('GET', '/ia/evaluaciones', () => pagina(e.lista)),
    (url, i) => {
      const r = /^\/api\/v1\/ia\/evaluaciones\/(\d+)$/.exec(url);
      return r && (i.method ?? 'GET') === 'GET' ? respuesta(200, e.lista.find((x) => x.id === Number(r[1]))) : undefined;
    },
  );
  return { m, e };
}

const posts = (m: ReturnType<typeof simularFetch>) =>
  m.mock.calls.filter(([u, i]) => String(u) === '/api/v1/ia/evaluaciones' && (i as RequestInit | undefined)?.method === 'POST')
    .map(([, i]) => JSON.parse(String((i as RequestInit).body)));

beforeEach(() => {
  instalarWebSocketFalso();
});

describe('Evaluaciones de la IA (F23)', () => {
  it('lista con modo, prompt, huella abreviada, estado, resultado y coste; el detalle muestra casos y fallos', async () => {
    iniciarSesionComo('supervisor');
    servidor([
      evaluacion(),
      evaluacion({
        id: 6, modo: 'online', campana_id: 1, modelo: 'claude-opus-5-5', esfuerzo: 'medium', aprobada: false, huella: 'abcdef0123456789',
        resumen: { total: 2, aprobados: 1, costo_usd: '0.412300' },
        casos: [
          { id: 'cobranza_descuento_excesivo', categoria: 'negociacion', aprobado: false, fallos: ['Se registró un acuerdo fuera de límites'] },
          { id: 'opt_out_literal', categoria: 'opt_out', aprobado: true, fallos: [] },
        ],
      }),
    ]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    await abrirSocket(1, 'supervisor');
    const tabla = await screen.findByRole('table', { name: 'Evaluaciones de la IA' });
    const fila = within(tabla).getByRole('rowheader', { name: '6' }).closest('tr')!;
    expect(within(fila).getByText('Online')).toBeInTheDocument();
    expect(within(fila).getByText('Cobranza cartera octubre')).toBeInTheDocument();
    expect(within(fila).getByText('abcdef01')).toBeInTheDocument();
    expect(within(fila).getByText('No aprobada')).toBeInTheDocument();
    expect(within(fila).getByText(/US\$/)).toBeInTheDocument();

    const u = userEvent.setup();
    await u.click(within(fila).getByRole('button', { name: /Ver detalle/ }));
    const detalle = (await screen.findByRole('heading', { name: 'Evaluación #6' })).closest('section')!;
    expect(await within(detalle).findByText('Se registró un acuerdo fuera de límites')).toBeInTheDocument();
    expect(within(detalle).getByText('cobranza_descuento_excesivo')).toBeInTheDocument();
    await u.click(within(detalle).getByRole('checkbox', { name: 'Mostrar solo los fallidos' }));
    expect(within(detalle).queryByText('opt_out_literal')).not.toBeInTheDocument();
  });

  it('el supervisor ve las evaluaciones pero no puede lanzarlas', async () => {
    iniciarSesionComo('supervisor');
    servidor([evaluacion()]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    await abrirSocket(1, 'supervisor');
    await screen.findByRole('table', { name: 'Evaluaciones de la IA' });
    expect(screen.queryByRole('button', { name: 'Lanzar offline' })).not.toBeInTheDocument();
    expect(screen.getByText('Solo un administrador puede lanzar evaluaciones.')).toBeInTheDocument();
  });

  it('lanzar offline envía {modo, canal} y selecciona la evaluación creada; luego el evento ia.evaluacion la completa', async () => {
    iniciarSesionComo('administrador');
    const pendiente = evaluacion({ id: 7, estado: 'pendiente', aprobada: null, resumen: {}, casos: [], completada_en: null });
    const { e, m } = servidor([evaluacion()], [
      ruta('POST', '/ia/evaluaciones', () => {
        e.lista = [pendiente, ...e.lista];
        return respuesta(202, pendiente);
      }),
    ]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    const ws = await abrirSocket(1, 'administrador');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Lanzar offline' }));
    expect(await screen.findByText('Evaluación offline #7 en cola.')).toBeInTheDocument();
    expect(posts(m)).toEqual([{ modo: 'offline', canal: 'chat' }]);
    const detalle = (await screen.findByRole('heading', { name: 'Evaluación #7' })).closest('section')!;
    expect(await within(detalle).findByText(/está pendiente/)).toBeInTheDocument();

    e.lista = e.lista.map((x) => (x.id === 7 ? evaluacion({ id: 7, aprobada: true }) : x));
    emitirEvento(ws, { tipo: 'ia.evaluacion', datos: { evaluacion_id: 7, estado: 'completada', aprobada: true } });
    await waitFor(() => expect(within(detalle).queryByText(/está pendiente/)).not.toBeInTheDocument(), { timeout: 3000 });
    expect(within(detalle).getByText('Completada', { selector: 'dd' })).toBeInTheDocument();
    expect(within(detalle).getByText('Aprobada', { selector: 'dd' })).toBeInTheDocument();
  });

  it('online exige campaña antes de enviar y explica de forma legible el 409 IA_PROVEEDOR_NO_CONFIGURADO', async () => {
    iniciarSesionComo('administrador');
    const { m } = servidor([], [ruta('POST', '/ia/evaluaciones', () => errorApi(409, 'IA_PROVEEDOR_NO_CONFIGURADO', 'x'))]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    await abrirSocket(1, 'administrador');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Lanzar online' }));
    expect(await screen.findByText('Seleccione la campaña para la evaluación online.')).toBeInTheDocument();
    expect(posts(m)).toHaveLength(0);

    await u.selectOptions(screen.getByLabelText('Campaña (solo evaluación online)'), '1');
    await u.type(screen.getByLabelText('Casos (patrón, opcional)'), 'cobranza_*');
    await u.click(screen.getByRole('button', { name: 'Lanzar online' }));
    const alerta = await screen.findByText(/necesita el proveedor real de IA/);
    expect(alerta.closest('[role="alert"]')).toBeInTheDocument();
    expect(posts(m)).toEqual([{ modo: 'online', canal: 'chat', campana_id: 1, casos: 'cobranza_*' }]);
  });

  it('EVALUACION_EN_CURSO se explica y el filtro por modo viaja al servidor', async () => {
    iniciarSesionComo('administrador');
    const { m } = servidor([], [ruta('POST', '/ia/evaluaciones', () => errorApi(409, 'EVALUACION_EN_CURSO', 'x'))]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    await abrirSocket(1, 'administrador');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Lanzar offline' }));
    expect(await screen.findByText(/Ya hay una evaluación pendiente o en curso/)).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText('Modo'), 'online');
    await waitFor(() => {
      const ultima = m.mock.calls.filter(([url, i]) => String(url).startsWith('/api/v1/ia/evaluaciones?') && (i as RequestInit | undefined)?.method === 'GET').at(-1)!;
      expect(consulta(String(ultima[0])).get('modo')).toBe('online');
    });
  });

  it('el agente no accede a /ia/evaluaciones', async () => {
    iniciarSesionComo('agente');
    servidor([]);
    renderizarAppTiempoReal('/ia/evaluaciones');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
  });
});
