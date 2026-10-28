import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch, type Manejador,
} from './utiles';
import { configuracion, conversacion, itemCola, mensaje, pagina, resumen } from './utilesWhatsApp';

const get = (ruta: string, cuerpo: () => unknown): Manejador => (url, i) =>
  (url.split('?')[0] === `/api/v1${ruta}` && (i.method ?? 'GET') === 'GET' ? respuesta(200, cuerpo()) : undefined);

const PELIGRO = '<img src=x onerror="window.hackeado = 1"><script>window.hackeado = 2</script><a href="javascript:alert(1)">pulse</a>';

beforeEach(() => {
  instalarWebSocketFalso();
  (window as unknown as { hackeado?: number }).hackeado = undefined;
});

describe('QA 2B: contenido no confiable y datos personales en la bandeja', () => {
  it('la cola pinta el resumen, la campaña y el motivo como texto, nunca como HTML', async () => {
    iniciarSesionComo('agente');
    simularFetch(
      get('/whatsapp/configuracion', () => configuracion()),
      get('/atencion/cola', () => [itemCola({ resumen: PELIGRO, campana: { id: 1, nombre: '<b>Campaña</b>' } })]),
      get('/conversaciones', () => pagina([])),
    );
    renderizarAppTiempoReal('/bandeja');
    const cola = await screen.findByRole('region', { name: 'Cola de atención' });
    expect(await within(cola).findByText(/<b>Campaña<\/b>/)).toBeInTheDocument();
    expect(cola.querySelector('script, img, b, a[href^="javascript"]')).toBeNull();
    expect((window as unknown as { hackeado?: number }).hackeado).toBeUndefined();
  });

  it('el botón del cliente y el nombre de perfil con HTML se muestran como texto', async () => {
    iniciarSesionComo('agente');
    simularFetch(
      get('/whatsapp/configuracion', () => configuracion()),
      get('/atencion/cola', () => []),
      get('/conversaciones', () => pagina([resumen({ nombre_perfil: PELIGRO, cliente_nombre: null })])),
      get('/conversaciones/12', () => conversacion({ nombre_perfil: PELIGRO, cliente_nombre: null })),
      get('/conversaciones/12/mensajes', () => ({
        items: [mensaje({ tipo: 'boton', cuerpo: null, boton: { payload: 'X', texto: PELIGRO } })],
        hay_mas: false,
      })),
      (url, i) => (url.endsWith('/leida') && i.method === 'POST' ? respuesta(204) : undefined),
    );
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const log = await screen.findByRole('log', { name: 'Mensajes de la conversación' });
    expect(await within(log).findByText(PELIGRO)).toBeInTheDocument();
    expect(document.body.querySelector('script, img[src="x"], a[href^="javascript"]')).toBeNull();
    expect((window as unknown as { hackeado?: number }).hackeado).toBeUndefined();
  });

  it('un error del servidor con HTML se muestra como texto al enviar un mensaje', async () => {
    iniciarSesionComo('agente');
    simularFetch(
      get('/whatsapp/configuracion', () => configuracion()),
      get('/atencion/cola', () => []),
      get('/conversaciones', () => pagina([resumen()])),
      get('/conversaciones/12', () => conversacion()),
      get('/conversaciones/12/mensajes', () => ({ items: [mensaje()], hay_mas: false })),
      (url, i) => (url.endsWith('/leida') && i.method === 'POST' ? respuesta(204) : undefined),
      (url, i) =>
        url.endsWith('/conversaciones/12/mensajes') && i.method === 'POST'
          ? errorApi(409, 'VENTANA_CERRADA', PELIGRO)
          : undefined,
    );
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Mensaje'), 'Hola{Enter}');
    expect(await screen.findByText(PELIGRO)).toBeInTheDocument();
    expect(document.body.querySelector('script, img[src="x"], a[href^="javascript"]')).toBeNull();
  });

  it('el agente nunca ve el número completo: solo la máscara de la API', async () => {
    iniciarSesionComo('agente');
    simularFetch(
      get('/whatsapp/configuracion', () => configuracion()),
      get('/atencion/cola', () => [itemCola()]),
      get('/conversaciones', () => pagina([resumen()])),
      get('/conversaciones/12', () => conversacion()),
      get('/conversaciones/12/mensajes', () => ({ items: [mensaje()], hay_mas: false })),
      (url, i) => (url.endsWith('/leida') && i.method === 'POST' ? respuesta(204) : undefined),
    );
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await screen.findByRole('heading', { name: 'María Pérez' });
    expect(document.body.textContent).toContain('+57300****567');
    expect(document.body.textContent).not.toMatch(/\+?573\d{9}\b/);
    expect(document.body.textContent).not.toMatch(/\b3\d{9}\b/);
  });
});
