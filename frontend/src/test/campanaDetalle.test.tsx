import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { CampanaCliente, Campana } from '../api/tipos';
import { campanaEjemplo, errorApi, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

function cliente(sobrescribir: Partial<CampanaCliente> = {}): CampanaCliente {
  return {
    id: 15, estado: 'pendiente', intentos: 0,
    cliente: { id: 9, tipo_documento: 'CC', numero_documento: '1020304050', nombre: 'María Pérez', email: null, ciudad: 'Bogotá' },
    telefonos: [
      { id: 21, numero_e164: '+573001234567', tipo_linea: 'movil', prioridad: 1, excluido: true },
      { id: 22, numero_e164: '+576012345678', tipo_linea: 'fijo', prioridad: 2, excluido: false },
    ],
    numero_obligacion: 'OB-001', saldo_total: '1500000.00', saldo_mora: '250000.50', dias_mora: 45,
    fecha_vencimiento: '2026-09-15', producto: null, oferta: null, datos_adicionales: {}, importacion_id: 7,
    creado_en: '2026-10-23T15:10:00Z', ...sobrescribir,
  };
}

function api(campana: Campana, clientes = [cliente()]) {
  return simularFetch(
    (url, init) => (url === '/api/v1/campanas/5' && init.method === 'PATCH' ? respuesta(200, { ...campana, estado: JSON.parse(init.body as string).estado ?? campana.estado }) : undefined),
    (url, init) => (url === '/api/v1/campanas/5' && init.method === 'DELETE' ? respuesta(204) : undefined),
    (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campana) : undefined),
    (url) => (url.startsWith('/api/v1/campanas/5/clientes') ? respuesta(200, { items: clientes, total: clientes.length, page: 1, page_size: 20 }) : undefined),
    (url) => (url.startsWith('/api/v1/campanas/5/importaciones') ? respuesta(200, paginaVacia) : undefined),
    (url) => (url === '/api/v1/campanas?page=1&page_size=20' ? respuesta(200, paginaVacia) : undefined),
    (url) => (url.startsWith('/api/v1/campanas') ? respuesta(200, paginaVacia) : undefined),
  );
}

describe('Detalle de campaña', () => {
  it('la tabla de clientes de cobranza muestra montos en COP, marca teléfonos excluidos y fecha DD/MM/YYYY', async () => {
    iniciarSesionComo('supervisor');
    api(campanaEjemplo({ estado: 'activa', total_clientes: 1 }));
    renderizarApp('/campanas/5');
    const fila = (await screen.findByRole('rowheader', { name: 'María Pérez' })).closest('tr')!;
    const texto = fila.textContent!.replace(/\s/g, ' ');
    expect(texto).toMatch(/1\.500\.000/);
    expect(texto).toMatch(/250\.000,50/);
    expect(texto).toContain('$');
    expect(texto).toContain('15/09/2026');
    expect(texto).toContain('OB-001');
    expect(texto).toContain('CC 1020304050');
    const excluido = within(fila).getByText('+573001234567', { exact: false }).closest('li')!;
    expect(excluido).toHaveTextContent('Excluido');
    const libre = within(fila).getByText('+576012345678', { exact: false }).closest('li')!;
    expect(libre).not.toHaveTextContent('Excluido');
    expect(libre).toHaveTextContent('fijo');
  });

  it('en una campaña de venta muestra producto y oferta y no columnas de cobranza', async () => {
    iniciarSesionComo('supervisor');
    api(campanaEjemplo({ tipo: 'venta', estado: 'activa' }), [cliente({ producto: 'Plan A', oferta: '10% dto', numero_obligacion: null, saldo_total: null, saldo_mora: null, dias_mora: null, fecha_vencimiento: null })]);
    renderizarApp('/campanas/5');
    await screen.findByRole('rowheader', { name: 'María Pérez' });
    expect(screen.getByRole('columnheader', { name: 'Producto' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Oferta' })).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Saldo total' })).not.toBeInTheDocument();
    expect(screen.getByText('Plan A')).toBeInTheDocument();
  });

  it('montos nulos se muestran como guion largo', async () => {
    iniciarSesionComo('supervisor');
    api(campanaEjemplo({ estado: 'activa' }), [cliente({ saldo_total: null, saldo_mora: null, dias_mora: null, fecha_vencimiento: null, numero_obligacion: null })]);
    renderizarApp('/campanas/5');
    const fila = (await screen.findByRole('rowheader', { name: 'María Pérez' })).closest('tr')!;
    expect(within(fila).getAllByText('—').length).toBeGreaterThanOrEqual(5);
  });

  it('la búsqueda de clientes envía q recortada y reinicia la página', async () => {
    iniciarSesionComo('supervisor');
    const m = api(campanaEjemplo({ estado: 'activa' }));
    renderizarApp('/campanas/5');
    await screen.findByRole('rowheader', { name: 'María Pérez' });
    const u = userEvent.setup();
    await u.type(screen.getByLabelText('Buscar por nombre, documento o teléfono'), '  300 123  ');
    await u.click(screen.getByRole('button', { name: 'Buscar' }));
    await waitFor(() => {
      const urls = m.mock.calls.map(([x]) => String(x));
      expect(urls.some((x) => x.startsWith('/api/v1/campanas/5/clientes') && x.includes('q=300+123') && x.includes('page=1'))).toBe(true);
    });
  });

  it('cambiar de estado envía PATCH {estado} y recarga la campaña', async () => {
    iniciarSesionComo('supervisor');
    const m = api(campanaEjemplo({ estado: 'borrador', total_clientes: 3 }));
    renderizarApp('/campanas/5');
    const boton = await screen.findByRole('button', { name: 'Activar' });
    const getsCampana = () => m.mock.calls.filter(([u, i]) => u === '/api/v1/campanas/5' && (i?.method ?? 'GET') === 'GET').length;
    const antes = getsCampana();
    await userEvent.setup().click(boton);
    await waitFor(() => {
      const patch = m.mock.calls.find(([, init]) => init?.method === 'PATCH')!;
      expect(patch[0]).toBe('/api/v1/campanas/5');
      expect(JSON.parse(patch[1]!.body as string)).toEqual({ estado: 'activa' });
    });
    await waitFor(() => expect(getsCampana()).toBeGreaterThan(antes));
  });

  it('activar sin clientes muestra el error del servidor y la campaña sigue en borrador', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (url, init) => (url === '/api/v1/campanas/5' && init.method === 'PATCH'
        ? errorApi(409, 'CAMPANA_SIN_CLIENTES', 'No se puede activar una campaña sin clientes.') : undefined),
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
      () => respuesta(200, paginaVacia),
    );
    renderizarApp('/campanas/5');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Activar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se puede activar una campaña sin clientes.');
    expect(screen.getByText('Borrador')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Activar' })).toBeEnabled();
  });

  it('eliminar pide confirmación: cancelar no llama a DELETE', async () => {
    iniciarSesionComo('supervisor');
    const m = api(campanaEjemplo());
    const confirmar = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderizarApp('/campanas/5');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Eliminar' }));
    expect(confirmar).toHaveBeenCalledTimes(1);
    expect(confirmar.mock.calls[0][0]).toContain('Cobranza octubre');
    expect(m.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false);
    expect(screen.getByRole('heading', { name: 'Cobranza octubre' })).toBeInTheDocument();
  });

  it('eliminar confirmado llama a DELETE y vuelve al listado', async () => {
    iniciarSesionComo('supervisor');
    const m = api(campanaEjemplo());
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderizarApp('/campanas/5');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Eliminar' }));
    expect(await screen.findByRole('heading', { name: 'Campañas' })).toBeInTheDocument();
    expect(m.mock.calls.some(([u, init]) => u === '/api/v1/campanas/5' && init?.method === 'DELETE')).toBe(true);
  });

  it('error al eliminar (409) se muestra y se permanece en el detalle', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (url, init) => (url === '/api/v1/campanas/5' && init.method === 'DELETE'
        ? errorApi(409, 'CAMPANA_NO_ELIMINABLE', 'Solo se pueden eliminar campañas en borrador.') : undefined),
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
      () => respuesta(200, paginaVacia),
    );
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderizarApp('/campanas/5');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Eliminar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Solo se pueden eliminar campañas en borrador.');
    expect(screen.getByRole('heading', { name: 'Cobranza octubre' })).toBeInTheDocument();
  });

  it('una campaña finalizada no ofrece Editar ni importar', async () => {
    iniciarSesionComo('administrador');
    api(campanaEjemplo({ estado: 'finalizada' }));
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    expect(screen.queryByRole('link', { name: 'Editar' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Archivo CSV de clientes')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Eliminar' })).not.toBeInTheDocument();
  });

  it('un 404 de la campaña muestra el error con Reintentar', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => errorApi(404, 'NO_ENCONTRADO', 'Campaña no encontrada.'));
    renderizarApp('/campanas/5');
    expect(await screen.findByRole('alert')).toHaveTextContent('Campaña no encontrada.');
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument();
  });

  it('el agente no llama a importaciones ni clientes (403 para su rol)', async () => {
    iniciarSesionComo('agente');
    const m = api(campanaEjemplo({ estado: 'activa' }));
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    const urls = m.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes('/clientes') || u.includes('/importaciones'))).toBe(false);
  });
});
