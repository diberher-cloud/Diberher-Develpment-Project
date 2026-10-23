import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { AgenteAsignado, AgenteSupervision, Tipificacion } from '../api/tipos';
import { campanaEjemplo, errorApi, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch, type Manejador } from './utiles';

const asignado = (id: number, nombre: string): AgenteAsignado => ({ usuario_id: id, nombre, email: `${nombre}@empresa.co`, activo: true, asignado_en: '2026-10-23T15:00:00Z' });
const sup = (id: number, nombre: string): AgenteSupervision => ({
  usuario_id: id, nombre, estado: 'disponible', desde: '2026-10-23T15:00:00Z', motivo_pausa: null, campanas: [], llamada: null,
});

function api(extra: Manejador[] = [], asignados: AgenteAsignado[] = [asignado(5, 'Ana')], estado: 'borrador' | 'finalizada' = 'borrador') {
  return simularFetch(
    ...extra,
    (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo({ estado })) : undefined),
    (url, i) => (url === '/api/v1/campanas/5/agentes' && i.method === 'GET' ? respuesta(200, asignados) : undefined),
    (url) => (url === '/api/v1/supervision/agentes' ? respuesta(200, [sup(5, 'Ana'), sup(6, 'Pedro'), sup(7, 'Zoe')]) : undefined),
    (url) => (/^\/api\/v1\/campanas\/5\/(importaciones|clientes|tipificaciones)/.test(url) ? respuesta(200, paginaVacia) : undefined),
  );
}

async function abrirPestana(nombre: string) {
  const u = userEvent.setup();
  await u.click(await screen.findByRole('tab', { name: nombre }));
  return u;
}

describe('Pestañas del detalle de campaña', () => {
  it('administrador y supervisor ven tres pestañas; la de clientes es la inicial', async () => {
    iniciarSesionComo('supervisor');
    api();
    renderizarApp('/campanas/5');
    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Clientes', 'Agentes', 'Tipificaciones']);
    expect(screen.getByRole('tab', { name: 'Clientes' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('heading', { name: 'Clientes de la campaña' })).toBeInTheDocument();
  });

  it('el agente no ve pestañas', async () => {
    iniciarSesionComo('agente');
    api();
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  it('se navega con las flechas del teclado', async () => {
    iniciarSesionComo('supervisor');
    api();
    renderizarApp('/campanas/5');
    const u = userEvent.setup();
    const primera = await screen.findByRole('tab', { name: 'Clientes' });
    primera.focus();
    await u.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Agentes' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Agentes' })).toHaveFocus();
  });
});

describe('Agentes de campaña', () => {
  it('muestra los agentes activos con los asignados marcados', async () => {
    iniciarSesionComo('supervisor');
    api();
    renderizarApp('/campanas/5');
    await abrirPestana('Agentes');
    expect(await screen.findByRole('checkbox', { name: 'Ana' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Pedro' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Zoe' })).not.toBeChecked();
  });

  it('guarda el conjunto seleccionado con PUT', async () => {
    iniciarSesionComo('administrador');
    const m = api([
      (url, i) => (url === '/api/v1/campanas/5/agentes' && i.method === 'PUT'
        ? respuesta(200, [asignado(5, 'Ana'), asignado(7, 'Zoe')]) : undefined),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Agentes');
    await u.click(await screen.findByRole('checkbox', { name: 'Zoe' }));
    await u.click(screen.getByRole('button', { name: 'Guardar agentes' }));
    expect(await screen.findByText('Agentes guardados.')).toBeInTheDocument();
    const put = m.mock.calls.find(([, i]) => i?.method === 'PUT')!;
    expect(JSON.parse(String(put[1]!.body))).toEqual({ usuario_ids: [5, 7] });
  });

  it('muestra el 422 por índice junto al agente correspondiente', async () => {
    iniciarSesionComo('supervisor');
    api([
      (url, i) => (url === '/api/v1/campanas/5/agentes' && i.method === 'PUT'
        ? errorApi(422, 'VALIDACION', 'Datos inválidos.', [{ campo: 'usuario_ids.1', mensaje: 'El usuario no es un agente activo.' }]) : undefined),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Agentes');
    await u.click(await screen.findByRole('checkbox', { name: 'Pedro' }));
    await u.click(screen.getByRole('checkbox', { name: 'Zoe' }));
    await u.click(screen.getByRole('button', { name: 'Guardar agentes' }));
    // ids enviados: [Ana, Pedro, Zoe] -> índice 1 = Pedro
    const alerta = await screen.findByText('El usuario no es un agente activo.');
    expect(alerta.closest('li')).toHaveTextContent('Pedro');
    expect(alerta.closest('li')).not.toHaveTextContent('Zoe');
    expect(screen.getByRole('checkbox', { name: 'Pedro' })).toHaveAttribute('aria-invalid', 'true');
  });

  it('muestra el 409 CAMPANA_FINALIZADA', async () => {
    iniciarSesionComo('supervisor');
    api([
      (url, i) => (url === '/api/v1/campanas/5/agentes' && i.method === 'PUT'
        ? errorApi(409, 'CAMPANA_FINALIZADA', 'La campaña está finalizada.') : undefined),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Agentes');
    await u.click(await screen.findByRole('checkbox', { name: 'Zoe' }));
    await u.click(screen.getByRole('button', { name: 'Guardar agentes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La campaña está finalizada.');
  });

  it('en una campaña finalizada el formulario está deshabilitado', async () => {
    iniciarSesionComo('supervisor');
    api([], [asignado(5, 'Ana')], 'finalizada');
    renderizarApp('/campanas/5');
    await abrirPestana('Agentes');
    expect(await screen.findByRole('checkbox', { name: 'Ana' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Guardar agentes' })).toBeDisabled();
  });
});

describe('Tipificaciones de campaña', () => {
  const tip = (o: Partial<Tipificacion> = {}): Tipificacion => ({
    id: 41, campana_cliente_id: 15, llamada_id: 31, canal: 'voz', origen: 'agente', usuario_id: 5, resultado: 'promesa_pago',
    contacto_directo: true, observacion: 'Paga el viernes', venta: null, volver_a_llamar_en: null, creado_en: '2026-10-23T15:13:00Z',
    promesa: { id: 7, monto: '250000.50', fecha_pago: '2026-10-30', numero_cuotas: 1, descuento_porcentaje: '0.00', estado: 'vigente' },
    cliente_nombre: 'María Pérez', agente_nombre: 'Pedro Agente', ...o,
  });

  function apiTip(items: Tipificacion[]) {
    return simularFetch(
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
      (url) => (url.startsWith('/api/v1/campanas/5/tipificaciones')
        ? respuesta(200, { items, total: 45, page: Number(new URL(url, 'http://x').searchParams.get('page') ?? 1), page_size: 20 }) : undefined),
      (url) => (/^\/api\/v1\/campanas\/5\/(importaciones|clientes)/.test(url) ? respuesta(200, paginaVacia) : undefined),
    );
  }

  it('lista tipificaciones con detalle y pagina', async () => {
    iniciarSesionComo('supervisor');
    const m = apiTip([tip(), tip({ id: 42, resultado: 'venta', promesa: null, venta: { id: 1, producto: 'Seguro hogar', valor: '89900.00', unidades: 1 }, origen: 'agente_ia', agente_nombre: null })]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Tipificaciones');
    const fila = (await screen.findAllByRole('rowheader'))[0].closest('tr')!;
    expect(fila).toHaveTextContent('María Pérez');
    expect(fila).toHaveTextContent('Pedro Agente');
    expect(fila).toHaveTextContent('Promesa de pago');
    expect(fila).toHaveTextContent('30/10/2026');
    expect(screen.getByText(/Seguro hogar/)).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Siguiente' }));
    await waitFor(() => expect(m.mock.calls.some(([url]) => String(url).includes('tipificaciones') && String(url).includes('page=2'))).toBe(true));
  });

  it('aplica los filtros en la consulta', async () => {
    iniciarSesionComo('supervisor');
    const m = apiTip([tip()]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Tipificaciones');
    await screen.findAllByRole('rowheader');
    await u.selectOptions(screen.getByLabelText('Resultado'), 'promesa_pago');
    await u.selectOptions(screen.getByLabelText('Origen'), 'agente');
    await u.type(screen.getByLabelText('Desde'), '2026-10-01');
    await u.type(screen.getByLabelText('Hasta'), '2026-10-23');
    await u.click(screen.getByRole('button', { name: 'Filtrar' }));
    await waitFor(() => {
      const url = m.mock.calls.map(([x]) => String(x)).filter((x) => x.includes('/tipificaciones')).at(-1)!;
      expect(url).toContain('resultado=promesa_pago');
      expect(url).toContain('origen=agente');
      expect(url).toContain('desde=2026-10-01');
      expect(url).toContain('hasta=2026-10-23');
      expect(url).toContain('page=1');
    });
  });

  it('valida que hasta no sea anterior a desde', async () => {
    iniciarSesionComo('supervisor');
    const m = apiTip([tip()]);
    renderizarApp('/campanas/5');
    const u = await abrirPestana('Tipificaciones');
    await screen.findAllByRole('rowheader');
    const antes = m.mock.calls.length;
    await u.type(screen.getByLabelText('Desde'), '2026-10-23');
    await u.type(screen.getByLabelText('Hasta'), '2026-10-01');
    await u.click(screen.getByRole('button', { name: 'Filtrar' }));
    expect(await screen.findByText('La fecha final no puede ser anterior a la inicial.')).toBeInTheDocument();
    expect(m.mock.calls.length).toBe(antes);
  });
});
