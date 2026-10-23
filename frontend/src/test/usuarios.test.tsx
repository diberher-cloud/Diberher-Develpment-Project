import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Usuario } from '../api/tipos';
import { errorApi, iniciarSesionComo, renderizarApp, respuesta, simularFetch } from './utiles';

const u = (o: Partial<Usuario>): Usuario => ({ id: 2, email: 'sup@empresa.co', nombre: 'Sara Supervisora', rol: 'supervisor', activo: true, ...o });
const pag = (items: Usuario[]) => ({ items, total: items.length, page: 1, page_size: 20 });

describe('Usuarios (solo administrador)', () => {
  it('el administrador no puede cambiarse el rol ni desactivarse a sí mismo desde la UI', async () => {
    iniciarSesionComo('administrador'); // id 1
    simularFetch(() => respuesta(200, pag([u({ id: 1, nombre: 'Usuario administrador', rol: 'administrador', email: 'administrador@empresa.co' }), u({})])));
    renderizarApp('/usuarios');
    const propia = (await screen.findByRole('rowheader', { name: 'Usuario administrador' })).closest('tr')!;
    expect(within(propia).getByRole('combobox')).toBeDisabled();
    expect(within(propia).getByRole('button', { name: /Desactivar/ })).toBeDisabled();
    const otra = screen.getByRole('rowheader', { name: 'Sara Supervisora' }).closest('tr')!;
    expect(within(otra).getByRole('combobox')).toBeEnabled();
    expect(within(otra).getByRole('button', { name: /Desactivar/ })).toBeEnabled();
  });

  it('crear usuario valida en cliente (correo, nombre, contraseña 10..128) sin llamar a la API', async () => {
    iniciarSesionComo('administrador');
    const m = simularFetch(() => respuesta(200, pag([])));
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    await screen.findByText(/No hay usuarios/);
    const antes = m.mock.calls.length;
    await user.type(screen.getByLabelText('Correo electrónico'), 'no-correo');
    await user.type(screen.getByLabelText('Nombre'), 'A');
    await user.type(screen.getByLabelText('Contraseña inicial'), 'corta');
    await user.click(screen.getByRole('button', { name: 'Crear usuario' }));
    expect(await screen.findByText('Ingrese un correo válido.')).toBeInTheDocument();
    expect(screen.getByText('Debe tener entre 2 y 120 caracteres.')).toBeInTheDocument();
    expect(screen.getByText('Debe tener entre 10 y 128 caracteres.')).toBeInTheDocument();
    expect(m.mock.calls.length).toBe(antes);
  });

  it('crear usuario envía el cuerpo del contrato y confirma', async () => {
    iniciarSesionComo('administrador');
    const m = simularFetch(
      (url, init) => (url === '/api/v1/usuarios' && init.method === 'POST' ? respuesta(201, u({ id: 9, email: 'agente1@empresa.co', nombre: 'Pedro Agente', rol: 'agente' })) : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Correo electrónico'), ' agente1@empresa.co ');
    await user.type(screen.getByLabelText('Nombre'), 'Pedro Agente');
    await user.selectOptions(screen.getByLabelText('Rol'), 'agente');
    await user.type(screen.getByLabelText('Contraseña inicial'), 'ClaveSegura123');
    await user.click(screen.getByRole('button', { name: 'Crear usuario' }));
    expect(await screen.findByText('Usuario agente1@empresa.co creado.')).toBeInTheDocument();
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ email: 'agente1@empresa.co', nombre: 'Pedro Agente', rol: 'agente', password: 'ClaveSegura123' });
    expect(screen.getByLabelText('Contraseña inicial')).toHaveValue('');
  });

  it('409 EMAIL_DUPLICADO se muestra al crear', async () => {
    iniciarSesionComo('administrador');
    simularFetch(
      (_url, init) => (init.method === 'POST' ? errorApi(409, 'EMAIL_DUPLICADO', 'Ya existe un usuario con ese correo.') : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Correo electrónico'), 'a@empresa.co');
    await user.type(screen.getByLabelText('Nombre'), 'Ana Gómez');
    await user.type(screen.getByLabelText('Contraseña inicial'), 'ClaveSegura123');
    await user.click(screen.getByRole('button', { name: 'Crear usuario' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ya existe un usuario con ese correo.');
  });

  it('cambiar rol y activar/desactivar envían PATCH con solo el campo modificado', async () => {
    iniciarSesionComo('administrador');
    const m = simularFetch(
      (url, init) => (/^\/api\/v1\/usuarios\/2$/.test(url) && init.method === 'PATCH' ? respuesta(200, u({})) : undefined),
      () => respuesta(200, pag([u({})])),
    );
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    const fila = (await screen.findByRole('rowheader', { name: 'Sara Supervisora' })).closest('tr')!;
    await user.selectOptions(within(fila).getByRole('combobox'), 'agente');
    await user.click(within(fila).getByRole('button', { name: /Desactivar/ }));
    await waitFor(() => expect(m.mock.calls.filter(([, i]) => i?.method === 'PATCH')).toHaveLength(2));
    const cuerpos = m.mock.calls.filter(([, i]) => i?.method === 'PATCH').map(([, i]) => JSON.parse(i!.body as string));
    expect(cuerpos).toEqual([{ rol: 'agente' }, { activo: false }]);
  });

  it('409 NO_PUEDE_DESACTIVARSE se muestra y no rompe la tabla', async () => {
    iniciarSesionComo('administrador');
    simularFetch(
      (_url, init) => (init.method === 'PATCH' ? errorApi(409, 'NO_PUEDE_DESACTIVARSE', 'Un administrador no puede desactivarse a sí mismo.') : undefined),
      () => respuesta(200, pag([u({})])),
    );
    renderizarApp('/usuarios');
    await userEvent.setup().click(await screen.findByRole('button', { name: /Desactivar/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('no puede desactivarse');
    expect(screen.getByRole('rowheader', { name: 'Sara Supervisora' })).toBeInTheDocument();
  });

  it('restablecer contraseña valida longitud y envía {password}', async () => {
    iniciarSesionComo('administrador');
    const m = simularFetch(
      (_url, init) => (init.method === 'PATCH' ? respuesta(200, u({})) : undefined),
      () => respuesta(200, pag([u({})])),
    );
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Restablecer contraseña/ }));
    await user.type(screen.getByLabelText('Nueva contraseña'), 'corta');
    await user.click(screen.getByRole('button', { name: 'Guardar contraseña' }));
    expect(await screen.findByText('Debe tener entre 10 y 128 caracteres.')).toBeInTheDocument();
    expect(m.mock.calls.some(([, i]) => i?.method === 'PATCH')).toBe(false);
    await user.clear(screen.getByLabelText('Nueva contraseña'));
    await user.type(screen.getByLabelText('Nueva contraseña'), 'NuevaClave12345');
    await user.click(screen.getByRole('button', { name: 'Guardar contraseña' }));
    expect(await screen.findByText('Contraseña actualizada.')).toBeInTheDocument();
    const patch = m.mock.calls.find(([, i]) => i?.method === 'PATCH')!;
    expect(JSON.parse(patch[1]!.body as string)).toEqual({ password: 'NuevaClave12345' });
  });

  it('los filtros de rol y estado viajan como parámetros (activo=false como booleano)', async () => {
    iniciarSesionComo('administrador');
    const m = simularFetch(() => respuesta(200, pag([])));
    renderizarApp('/usuarios');
    const user = userEvent.setup();
    await screen.findByText(/No hay usuarios/);
    await user.selectOptions(screen.getByLabelText('Filtrar por rol'), 'agente');
    await user.selectOptions(screen.getByLabelText('Filtrar por estado'), 'false');
    await waitFor(() => {
      const ultima = String(m.mock.calls.at(-1)![0]);
      expect(ultima).toContain('rol=agente');
      expect(ultima).toContain('activo=false');
    });
  });
});
