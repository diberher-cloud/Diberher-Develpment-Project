import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { EstadoCampana } from '../api/tipos';
import { campanaEjemplo, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

describe('Campañas', () => {
  it.each<[EstadoCampana, string[], boolean]>([
    ['borrador', ['Activar'], true],
    ['activa', ['Pausar', 'Finalizar'], false],
    ['pausada', ['Activar', 'Finalizar'], false],
    ['finalizada', [], false],
  ])('estado %s: botones de transición %j (eliminar: %s)', async (estado, esperados, eliminar) => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo({ estado })) : undefined),
      () => respuesta(200, paginaVacia),
    );
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    const grupo = screen.getByRole('group', { name: 'Acciones de la campaña' });
    const nombres = Array.from(grupo.querySelectorAll('button')).map((b) => b.textContent).filter((t) => t !== 'Eliminar');
    expect(nombres).toEqual(esperados);
    expect(!!screen.queryByRole('button', { name: 'Eliminar' })).toBe(eliminar);
  });

  it('el agente ve el detalle sin acciones ni importación', async () => {
    iniciarSesionComo('agente');
    simularFetch((url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo({ estado: 'activa' })) : undefined));
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    expect(screen.queryByRole('group', { name: 'Acciones de la campaña' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Archivo CSV de clientes')).not.toBeInTheDocument();
  });

  it('el formulario valida fecha_fin >= fecha_inicio sin llamar a la API', async () => {
    iniciarSesionComo('supervisor');
    const fetchMock = simularFetch(() => respuesta(201, campanaEjemplo()));
    renderizarApp('/campanas/nueva');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Nombre'), 'Campaña nueva');
    await u.selectOptions(screen.getByLabelText('Tipo'), 'venta');
    await u.type(screen.getByLabelText('Fecha de inicio'), '2026-11-10');
    await u.type(screen.getByLabelText('Fecha de fin'), '2026-11-01');
    await u.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByText('La fecha de fin no puede ser anterior a la fecha de inicio.')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('muestra el error 409 del servidor junto al campo nombre', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() =>
      new Response(JSON.stringify({ error: { codigo: 'NOMBRE_DUPLICADO', mensaje: 'Ya existe una campaña con ese nombre.', detalles: [{ campo: 'nombre', mensaje: 'Nombre en uso.' }] } }), { status: 409 }),
    );
    renderizarApp('/campanas/nueva');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Nombre'), 'Repetida');
    await u.selectOptions(screen.getByLabelText('Tipo'), 'venta');
    await u.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByText('Nombre en uso.')).toBeInTheDocument();
    expect(screen.getByLabelText('Nombre')).toHaveAccessibleDescription('Nombre en uso.');
  });
});
