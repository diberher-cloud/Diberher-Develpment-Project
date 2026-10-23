import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CLAVE_SESION } from '../api/sesion';
import { errorApi, paginaVacia, renderizarApp, respuesta, simularFetch, usuarioDe } from './utiles';

async function completarYEnviar(email = 'admin@empresa.co', clave = 'ClaveSegura123') {
  const u = userEvent.setup();
  await u.type(screen.getByLabelText('Correo electrónico'), email);
  await u.type(screen.getByLabelText('Contraseña'), clave);
  await u.click(screen.getByRole('button', { name: 'Ingresar' }));
}

describe('Login', () => {
  it('con credenciales válidas guarda la sesión y redirige a campañas', async () => {
    const fetchMock = simularFetch(
      (url, init) =>
        url === '/api/v1/auth/login' && init.method === 'POST'
          ? respuesta(200, { access_token: 'jwt-123', token_type: 'bearer', expires_in: 28800, usuario: usuarioDe('administrador') })
          : undefined,
      (url) => (url.startsWith('/api/v1/campanas') ? respuesta(200, paginaVacia) : undefined),
    );
    renderizarApp('/login');
    await completarYEnviar();

    expect(await screen.findByRole('heading', { name: 'Campañas' })).toBeInTheDocument();
    const guardada = JSON.parse(sessionStorage.getItem(CLAVE_SESION)!);
    expect(guardada.token).toBe('jwt-123');
    expect(guardada.usuario.rol).toBe('administrador');
    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ email: 'admin@empresa.co', password: 'ClaveSegura123' });
  });

  it('con 401 muestra el mensaje del servidor y no guarda sesión', async () => {
    simularFetch(() => errorApi(401, 'CREDENCIALES_INVALIDAS', 'Correo o contraseña incorrectos.'));
    renderizarApp('/login');
    await completarYEnviar();

    expect(await screen.findByRole('alert')).toHaveTextContent('Correo o contraseña incorrectos.');
    expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull();
  });

  it('con 422 muestra el detalle junto a cada campo', async () => {
    simularFetch(() =>
      errorApi(422, 'VALIDACION', 'Los datos enviados no son válidos.', [
        { campo: 'email', mensaje: 'Correo electrónico no válido.' },
        { campo: 'password', mensaje: 'La contraseña es obligatoria.' },
      ]),
    );
    renderizarApp('/login');
    await completarYEnviar('no-es-correo', 'x');

    const email = screen.getByLabelText('Correo electrónico');
    await waitFor(() => expect(email).toHaveAccessibleDescription('Correo electrónico no válido.'));
    expect(screen.getByLabelText('Contraseña')).toHaveAccessibleDescription('La contraseña es obligatoria.');
    expect(email).toHaveAttribute('aria-invalid', 'true');
  });
});
