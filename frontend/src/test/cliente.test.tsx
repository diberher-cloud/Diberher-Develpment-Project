import { screen } from '@testing-library/react';
import { ErrorApi, solicitar } from '../api/cliente';
import { CLAVE_SESION } from '../api/sesion';
import { errorApi, iniciarSesionComo, renderizarApp, respuesta, simularFetch } from './utiles';

describe('cliente API', () => {
  it('envía el token Bearer y arma la query sin valores vacíos', async () => {
    iniciarSesionComo('administrador');
    const fetchMock = simularFetch(() => respuesta(200, { ok: true }));
    await solicitar('GET', '/campanas', { params: { q: '', page: 2, estado: undefined } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/campanas?page=2');
    expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer token-de-prueba');
  });

  it('un 401 limpia sessionStorage y lanza ErrorApi', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => errorApi(401, 'NO_AUTENTICADO', 'Sesión expirada.'));
    await expect(solicitar('GET', '/auth/me')).rejects.toBeInstanceOf(ErrorApi);
    expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull();
  });

  it('otros errores conservan la sesión y exponen código y detalles', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => errorApi(409, 'NOMBRE_DUPLICADO', 'Ya existe.', [{ campo: 'nombre', mensaje: 'Duplicado.' }]));
    const e = await solicitar('POST', '/campanas', { cuerpo: {} }).catch((x: ErrorApi) => x);
    expect(e).toBeInstanceOf(ErrorApi);
    expect((e as ErrorApi).codigo).toBe('NOMBRE_DUPLICADO');
    expect((e as ErrorApi).detalleDe('nombre')).toBe('Duplicado.');
    expect(sessionStorage.getItem(CLAVE_SESION)).not.toBeNull();
  });

  it('en la app, un 401 de cualquier llamada cierra la sesión y lleva a /login', async () => {
    iniciarSesionComo('administrador');
    simularFetch(() => errorApi(401, 'NO_AUTENTICADO', 'Token expirado.'));
    renderizarApp('/campanas');
    expect(await screen.findByRole('heading', { name: 'Iniciar sesión' })).toBeInTheDocument();
    expect(sessionStorage.getItem(CLAVE_SESION)).toBeNull();
  });
});
