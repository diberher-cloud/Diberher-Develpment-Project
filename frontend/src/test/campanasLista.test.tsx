import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Campana } from '../api/tipos';
import { campanaEjemplo, errorApi, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

const urlsLlamadas = (m: ReturnType<typeof simularFetch>) => m.mock.calls.map(([u]) => String(u));

function pagina(items: Campana[], extra: Partial<{ total: number; page: number }> = {}) {
  return { items, total: extra.total ?? items.length, page: extra.page ?? 1, page_size: 20 };
}

describe('Listado de campañas', () => {
  it('muestra la tabla con tipo, estado, fechas en DD/MM/YYYY y clientes', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() =>
      respuesta(200, pagina([campanaEjemplo({ id: 1, nombre: 'Uno', estado: 'activa', fecha_inicio: '2026-11-01', total_clientes: 7 })])),
    );
    renderizarApp('/campanas');
    const fila = (await screen.findByRole('link', { name: 'Uno' })).closest('tr')!;
    expect(within(fila).getByText('Cobranza')).toBeInTheDocument();
    expect(within(fila).getByText('Activa')).toBeInTheDocument();
    expect(within(fila).getByText('01/11/2026')).toBeInTheDocument();
    expect(within(fila).getByText('7')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Nueva campaña' })).toBeInTheDocument();
  });

  it('estado vacío', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/campanas');
    expect(await screen.findByText(/No hay campañas que coincidan/)).toBeInTheDocument();
  });

  it('estado de carga y luego de error con Reintentar que vuelve a llamar', async () => {
    iniciarSesionComo('supervisor');
    let n = 0;
    const m = simularFetch(() => (++n === 1 ? errorApi(500, 'ERROR_INTERNO', 'Error interno del servidor.') : respuesta(200, pagina([campanaEjemplo({ nombre: 'Recuperada' })]))));
    renderizarApp('/campanas');
    expect(await screen.findByRole('alert')).toHaveTextContent('Error interno del servidor.');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByRole('link', { name: 'Recuperada' })).toBeInTheDocument();
    expect(m).toHaveBeenCalledTimes(2);
  });

  it('error de red muestra un mensaje en español', async () => {
    iniciarSesionComo('supervisor');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    renderizarApp('/campanas');
    expect(await screen.findByRole('alert')).toHaveTextContent(/No se pudo conectar con el servidor/);
  });

  it('los filtros de estado, tipo y búsqueda viajan como parámetros y reinician la página', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(() => respuesta(200, pagina([campanaEjemplo()], { total: 45 })));
    renderizarApp('/campanas');
    await screen.findByRole('link', { name: 'Cobranza octubre' });
    const u = userEvent.setup();
    await u.click(screen.getByRole('button', { name: 'Siguiente' }));
    await waitFor(() => expect(urlsLlamadas(m).some((x) => x.includes('page=2'))).toBe(true));

    await u.selectOptions(screen.getByLabelText('Estado'), 'activa');
    await u.selectOptions(screen.getByLabelText('Tipo'), 'venta');
    await u.type(screen.getByLabelText('Buscar por nombre'), '  oct  ');
    await u.click(screen.getByRole('button', { name: 'Buscar' }));
    await waitFor(() => {
      const ultima = urlsLlamadas(m).at(-1)!;
      expect(ultima).toContain('estado=activa');
      expect(ultima).toContain('tipo=venta');
      expect(ultima).toContain('q=oct');
      expect(ultima).toContain('page=1');
      expect(ultima).toContain('page_size=20');
    });
  });

  it('la paginación deshabilita Anterior en la primera página y Siguiente en la última', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch((url) => respuesta(200, pagina([campanaEjemplo()], { total: 21, page: url.includes('page=2') ? 2 : 1 })));
    renderizarApp('/campanas');
    await screen.findByText(/Página 1 de 2 \(21 registros\)/);
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Siguiente' }));
    await screen.findByText(/Página 2 de 2/);
    expect(urlsLlamadas(m).at(-1)).toContain('page=2');
    expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeEnabled();
  });

  it('el agente solo pide campañas activas, no ve filtro de estado ni "Nueva campaña"', async () => {
    iniciarSesionComo('agente');
    const m = simularFetch(() => respuesta(200, pagina([campanaEjemplo({ estado: 'activa' })])));
    renderizarApp('/campanas');
    await screen.findByRole('link', { name: 'Cobranza octubre' });
    expect(urlsLlamadas(m)[0]).toContain('estado=activa');
    expect(screen.queryByLabelText('Estado')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Nueva campaña' })).not.toBeInTheDocument();
    expect(screen.getByText(/únicamente las campañas activas/)).toBeInTheDocument();
  });

  it('un 401 en el listado cierra la sesión y lleva a /login', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => errorApi(401, 'NO_AUTENTICADO', 'No autenticado.'));
    renderizarApp('/campanas');
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(sessionStorage.length).toBe(0);
  });
});

describe('Navegación por rol', () => {
  it.each([
    ['administrador', ['Campañas', 'Bandeja', 'Supervisión', 'Supervisión IA', 'Evaluaciones IA', 'Exclusiones', 'Plantillas', 'Autorizaciones', 'Cumplimiento', 'Usuarios']],
    ['supervisor', ['Campañas', 'Bandeja', 'Supervisión', 'Supervisión IA', 'Evaluaciones IA', 'Exclusiones', 'Plantillas', 'Autorizaciones', 'Cumplimiento']],
    ['agente', ['Campañas', 'Consola', 'Bandeja', 'Cumplimiento']],
  ] as const)('%s ve el menú %j', async (rol, esperado) => {
    iniciarSesionComo(rol);
    simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/campanas');
    const menu = await screen.findByRole('navigation', { name: 'Principal' });
    const enlaces = within(menu).getAllByRole('link').map((a) => a.textContent);
    expect(enlaces).toEqual(esperado);
  });

  it('supervisor en /usuarios ve "No autorizado" y no se llama a la API de usuarios', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/usuarios');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
    expect(urlsLlamadas(m).some((u) => u.includes('/usuarios'))).toBe(false);
  });

  it('agente en /exclusiones ve "No autorizado" y no se llama a la API', async () => {
    iniciarSesionComo('agente');
    const m = simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/exclusiones');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
    expect(urlsLlamadas(m).some((u) => u.includes('/exclusiones'))).toBe(false);
  });

  it('Cerrar sesión limpia sessionStorage y vuelve a /login', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/campanas');
    await screen.findByRole('heading', { name: 'Campañas' });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cerrar sesión' }));
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(sessionStorage.length).toBe(0);
  });

  it('sin sesión cualquier ruta interna redirige a /login sin llamar a la API', async () => {
    const m = simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/cumplimiento');
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(m).not.toHaveBeenCalled();
  });

  it('tras iniciar sesión vuelve a la ruta que se intentó abrir', async () => {
    simularFetch(
      (url, init) => (url === '/api/v1/auth/login' && init.method === 'POST'
        ? respuesta(200, { access_token: 't', token_type: 'bearer', expires_in: 1, usuario: { id: 1, email: 'a@b.co', nombre: 'A', rol: 'supervisor', activo: true } })
        : undefined),
      () => respuesta(200, []),
    );
    renderizarApp('/cumplimiento');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Correo electrónico'), 'a@b.co');
    await u.type(screen.getByLabelText('Contraseña'), 'ClaveSegura123');
    await u.click(screen.getByRole('button', { name: 'Ingresar' }));
    expect(await screen.findByRole('heading', { name: 'Cumplimiento' })).toBeInTheDocument();
  });

  it('una sesión corrupta en sessionStorage se ignora', async () => {
    sessionStorage.setItem('outbound.sesion', '{no es json');
    const primera = renderizarApp('/campanas');
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    primera.unmount();
    sessionStorage.setItem('outbound.sesion', JSON.stringify({ token: 5 }));
    renderizarApp('/campanas');
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
  });
});
