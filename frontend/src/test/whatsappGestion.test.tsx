import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Autorizacion, Exclusion } from '../api/tipos';
import { campanaEjemplo, errorApi, iniciarSesionComo, renderizarApp, renderizarAppTiempoReal, respuesta, simularFetch, type Manejador } from './utiles';
import { configuracion, pagina, plantilla } from './utilesWhatsApp';

const metodo = (m: string, ruta: string, f: (cuerpo: Record<string, unknown>, url: string) => Response): Manejador => (url, i) =>
  (url.split('?')[0] === `/api/v1${ruta}` && i.method === m ? f(i.body && typeof i.body === 'string' ? JSON.parse(i.body) : {}, url) : undefined);
const lista = (ruta: string, cuerpo: () => unknown): Manejador => (url, i) =>
  (url.split('?')[0] === `/api/v1${ruta}` && (i.method ?? 'GET') === 'GET' ? respuesta(200, cuerpo()) : undefined);

describe('Plantillas de WhatsApp', () => {
  it('lista con estado de aprobación; solo el administrador ve Sincronizar y muestra el resultado', async () => {
    iniciarSesionComo('administrador');
    let sincronizado = false;
    const m = simularFetch(
      metodo('POST', '/whatsapp/plantillas/sincronizar', () => { sincronizado = true; return respuesta(200, { creadas: 2, actualizadas: 1, desactivadas: 0 }); }),
      lista('/whatsapp/plantillas', () => [plantilla(), plantilla({ id: 4, nombre: 'seguimiento', estado_aprobacion: 'pendiente', activa: false, enviable: false, finalidad: null })]),
    );
    renderizarApp('/whatsapp/plantillas');
    const fila = (await screen.findByRole('rowheader', { name: /recordatorio_cobranza/ })).closest('tr')!;
    expect(within(fila).getByText('Aprobada')).toBeInTheDocument();
    expect(within(fila).getByText('Activa')).toBeInTheDocument();
    const pendiente = screen.getByRole('rowheader', { name: /seguimiento/ }).closest('tr')!;
    expect(within(pendiente).getByText('Pendiente')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sincronizar' }));
    expect(await screen.findByText('Sincronización completa: 2 creadas, 1 actualizadas, 0 desactivadas.')).toBeInTheDocument();
    expect(sincronizado).toBe(true);
    expect(m.mock.calls.filter(([u, i]) => String(u).includes('/whatsapp/plantillas') && (i?.method ?? 'GET') === 'GET').length).toBeGreaterThan(1);
  });

  it('el supervisor no ve el botón Sincronizar', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(lista('/whatsapp/plantillas', () => [plantilla()]));
    renderizarApp('/whatsapp/plantillas');
    await screen.findByRole('rowheader', { name: /recordatorio_cobranza/ });
    expect(screen.queryByRole('button', { name: 'Sincronizar' })).not.toBeInTheDocument();
  });

  it('el agente no accede a la página', async () => {
    iniciarSesionComo('agente');
    simularFetch(lista('/whatsapp/plantillas', () => [plantilla()]));
    renderizarApp('/whatsapp/plantillas');
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Plantillas de WhatsApp' })).not.toBeInTheDocument());
  });

  it('edita finalidad y mapeo con la lista blanca y muestra el 422 junto a la variable', async () => {
    iniciarSesionComo('supervisor');
    const cuerpos: Record<string, unknown>[] = [];
    let n = 0;
    simularFetch(
      metodo('PUT', '/whatsapp/plantillas/4', (c) => {
        cuerpos.push(c);
        return ++n === 1
          ? errorApi(422, 'PLANTILLA_MAPEO_INVALIDO', 'El mapeo no es válido.', [{ campo: 'mapeo_variables.2', mensaje: 'Campo no permitido.' }])
          : respuesta(200, plantilla({ id: 4 }));
      }),
      lista('/whatsapp/plantillas', () => [plantilla({ id: 4, nombre: 'oferta_venta', cuerpo: 'Hola {{1}}, {{2}} ofrece.', variables: ['1', '2'], mapeo_variables: {}, finalidad: null, activa: false, enviable: false })]),
    );
    renderizarApp('/whatsapp/plantillas');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: /Editar oferta_venta/ }));
    const form = await screen.findByRole('form', { name: 'Editar la plantilla oferta_venta' });
    // Solo la lista blanca (4 campos) más la opción vacía.
    expect(within(within(form).getByLabelText('Variable {{1}}')).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Seleccione un campo…', 'Primer nombre del cliente', 'Nombre de la empresa', 'Primer nombre del agente', 'Producto del registro',
    ]);
    await u.selectOptions(within(form).getByLabelText('Finalidad'), 'venta');
    await u.selectOptions(within(form).getByLabelText('Variable {{1}}'), 'primer_nombre');
    await u.selectOptions(within(form).getByLabelText('Variable {{2}}'), 'empresa');
    await u.click(within(form).getByLabelText(/Plantilla activa/));
    await u.click(within(form).getByRole('button', { name: 'Guardar' }));
    expect(await within(form).findByText('Campo no permitido.')).toBeInTheDocument();
    expect(cuerpos[0]).toEqual({ activa: true, finalidad: 'venta', mapeo_variables: { '1': 'primer_nombre', '2': 'empresa' } });
    await u.click(within(form).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Editar la plantilla oferta_venta' })).not.toBeInTheDocument());
  });

  it('PLANTILLA_SIN_BAJA se muestra como error general', async () => {
    iniciarSesionComo('administrador');
    simularFetch(
      metodo('PUT', '/whatsapp/plantillas/3', () => errorApi(422, 'PLANTILLA_SIN_BAJA', 'Una plantilla de marketing necesita un botón de baja.')),
      lista('/whatsapp/plantillas', () => [plantilla({ categoria: 'marketing' })]),
    );
    renderizarApp('/whatsapp/plantillas');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: /Editar recordatorio_cobranza/ }));
    await u.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByText('Una plantilla de marketing necesita un botón de baja.')).toBeInTheDocument();
  });
});

const aut = (o: Partial<Autorizacion> = {}): Autorizacion => ({
  id: 7, numero_mascara: '+57300****567', numero_e164: '+573001234567', canal: 'whatsapp', finalidad: 'cobranza', origen: 'agente',
  evidencia: 'Formulario firmado F-123', otorgada_en: '2026-10-24T15:00:00Z', vigente: true, revocada_en: null, motivo_revocacion: null,
  registrada_por: { id: 2, nombre: 'Sara Supervisora' }, ...o,
});

describe('Autorizaciones (opt-in)', () => {
  it('lista, busca por número y revoca con confirmación', async () => {
    iniciarSesionComo('supervisor');
    const confirmar = vi.spyOn(window, 'confirm').mockReturnValue(true);
    let revocada = false;
    const m = simularFetch(
      metodo('DELETE', '/autorizaciones/7', () => { revocada = true; return respuesta(204); }),
      lista('/autorizaciones', () => pagina([aut(), aut({ id: 8, vigente: false, motivo_revocacion: 'opt_out', revocada_en: '2026-10-25T00:00:00Z', evidencia: 'Otra' })])),
    );
    renderizarApp('/autorizaciones');
    const u = userEvent.setup();
    const fila = (await screen.findAllByRole('rowheader', { name: '+573001234567' }))[0].closest('tr')!;
    expect(within(fila).getByText('Vigente')).toBeInTheDocument();
    expect(screen.getByText('Revocada (Baja del cliente)')).toBeInTheDocument();
    expect(m.mock.calls.some(([x]) => String(x).includes('vigentes=true'))).toBe(true);
    await u.type(screen.getByLabelText('Buscar por teléfono'), '300 123');
    await u.click(screen.getByRole('button', { name: 'Buscar' }));
    await waitFor(() => expect(String(m.mock.calls.at(-1)![0])).toContain('numero=300+123'));
    await u.click(screen.getAllByRole('button', { name: /Revocar/ })[0]);
    await waitFor(() => expect(revocada).toBe(true));
    expect(confirmar).toHaveBeenCalled();
  });

  it('alta manual: valida la evidencia, envía el cuerpo y muestra AUTORIZACION_DUPLICADA', async () => {
    iniciarSesionComo('administrador');
    const cuerpos: Record<string, unknown>[] = [];
    let n = 0;
    simularFetch(
      metodo('POST', '/autorizaciones', (c) => { cuerpos.push(c); return ++n === 1 ? errorApi(409, 'AUTORIZACION_DUPLICADA', 'Ya hay una autorización vigente igual.') : respuesta(201, aut()); }),
      lista('/autorizaciones', () => pagina([])),
    );
    renderizarApp('/autorizaciones');
    const u = userEvent.setup();
    await screen.findByText(/No hay autorizaciones/);
    await u.type(screen.getByLabelText('Teléfono'), '300 123 4567');
    await u.click(screen.getByRole('button', { name: 'Registrar' }));
    expect(await screen.findByText('La evidencia debe tener entre 5 y 500 caracteres.')).toBeInTheDocument();
    expect(cuerpos).toHaveLength(0);
    await u.type(screen.getByLabelText('Evidencia'), 'Formulario firmado F-123');
    await u.click(screen.getByRole('button', { name: 'Registrar' }));
    expect(await screen.findByText('Ya hay una autorización vigente igual.')).toBeInTheDocument();
    expect(cuerpos[0]).toEqual({ telefono: '300 123 4567', finalidad: 'cobranza', evidencia: 'Formulario firmado F-123' });
    await u.click(screen.getByRole('button', { name: 'Registrar' }));
    expect(await screen.findByText('Autorización registrada para +573001234567.')).toBeInTheDocument();
  });
});

const excl = (o: Partial<Exclusion> = {}): Exclusion => ({
  id: 3, numero_e164: '+573001234567', motivo: 'solicitud_titular', aplica_a: 'todas', observacion: null, creado_por: null,
  creado_en: '2026-10-23T15:20:00Z', canal: 'whatsapp', origen: 'sistema', conversacion_id: 12, ...o,
});

describe('Exclusiones por canal', () => {
  it('muestra la columna canal, filtra por canal y da de alta con canal', async () => {
    iniciarSesionComo('supervisor');
    const cuerpos: Record<string, unknown>[] = [];
    const m = simularFetch(
      metodo('POST', '/exclusiones', (c) => { cuerpos.push(c); return respuesta(201, excl()); }),
      (url, i) => (url.startsWith('/api/v1/exclusiones?') && (i.method ?? 'GET') === 'GET' ? respuesta(200, pagina([excl(), excl({ id: 4, canal: 'todos', numero_e164: '+573009999999', creado_por: 2, origen: 'usuario' })])) : undefined),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    const fila = (await screen.findByRole('rowheader', { name: '+573001234567' })).closest('tr')!;
    expect(within(fila).getByText('Solo WhatsApp')).toBeInTheDocument();
    expect(screen.getByText('Todos los canales', { selector: 'td' })).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText('Filtrar por canal'), 'whatsapp');
    await waitFor(() => expect(String(m.mock.calls.at(-1)![0])).toContain('canal=whatsapp'));
    await u.type(screen.getByLabelText('Teléfono'), '300 123 4567');
    await u.selectOptions(screen.getByLabelText('Canal'), 'voz');
    await u.click(screen.getByRole('button', { name: 'Agregar' }));
    await waitFor(() => expect(cuerpos).toHaveLength(1));
    expect(cuerpos[0]).toMatchObject({ telefono: '300 123 4567', canal: 'voz' });
  });

  it('la carga masiva envía el canal elegido', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      metodo('POST', '/exclusiones/importar', () => respuesta(200, { total_filas: 1, creadas: 1, duplicadas: 0, invalidas: 0, errores: [], errores_truncados: false })),
      (url) => (url.startsWith('/api/v1/exclusiones?') ? respuesta(200, pagina([])) : undefined),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await u.upload(await screen.findByLabelText('Archivo CSV de exclusiones (columna telefono)'), new File(['telefono\n3001234567'], 'x.csv', { type: 'text/csv' }));
    await u.selectOptions(screen.getByLabelText('Canal (carga)'), 'whatsapp');
    await u.click(screen.getByRole('button', { name: 'Cargar' }));
    await screen.findByText('Resultado de la carga');
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect((post[1]!.body as FormData).get('canal')).toBe('whatsapp');
  });
});

describe('Formulario de campaña con WhatsApp', () => {
  it('habilitar WhatsApp permite elegir la plantilla inicial compatible y la envía', async () => {
    iniciarSesionComo('supervisor');
    const cuerpos: Record<string, unknown>[] = [];
    simularFetch(
      metodo('POST', '/campanas', (c) => { cuerpos.push(c); return respuesta(201, campanaEjemplo()); }),
      lista('/whatsapp/plantillas', () => [plantilla(), plantilla({ id: 9, nombre: 'solo_venta', finalidad: 'venta' })]),
    );
    renderizarApp('/campanas/nueva');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Nombre'), 'Campaña con chat');
    await u.selectOptions(screen.getByLabelText('Tipo'), 'cobranza');
    expect(screen.queryByLabelText('Plantilla inicial (opcional)')).not.toBeInTheDocument();
    await u.click(screen.getByLabelText('Habilitar WhatsApp en esta campaña'));
    const sel = await screen.findByLabelText('Plantilla inicial (opcional)');
    await waitFor(() => expect(within(sel).getAllByRole('option').map((o) => o.textContent)).toEqual(['Ninguna', 'recordatorio_cobranza']));
    await u.selectOptions(sel, 'recordatorio_cobranza');
    await u.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(cuerpos).toHaveLength(1));
    expect(cuerpos[0]).toMatchObject({ whatsapp_habilitado: true, plantilla_inicial_id: 3, tipo: 'cobranza' });
  });

  it('la campaña sin WhatsApp envía whatsapp_habilitado=false y plantilla nula', async () => {
    iniciarSesionComo('supervisor');
    const cuerpos: Record<string, unknown>[] = [];
    simularFetch(metodo('POST', '/campanas', (c) => { cuerpos.push(c); return respuesta(201, campanaEjemplo()); }));
    renderizarApp('/campanas/nueva');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Nombre'), 'Sin chat');
    await u.selectOptions(screen.getByLabelText('Tipo'), 'venta');
    await u.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(cuerpos).toHaveLength(1));
    expect(cuerpos[0]).toMatchObject({ whatsapp_habilitado: false, plantilla_inicial_id: null });
  });
});

describe('Simulador y estado del worker', () => {
  it('con simulación habilitada: aparece en el menú, envía un entrante y cambia el estado de un saliente', async () => {
    iniciarSesionComo('supervisor');
    const entrantes: Record<string, unknown>[] = [];
    const estados: Record<string, unknown>[] = [];
    simularFetch(
      lista('/whatsapp/configuracion', () => configuracion({ simulacion: true })),
      metodo('POST', '/whatsapp/simulacion/entrante', (c) => { entrantes.push(c); return respuesta(200, { mensaje_id: 101, proveedor_id: 'SMsim1' }); }),
      metodo('POST', '/whatsapp/simulacion/mensajes/55/estado', (c) => { estados.push(c); return respuesta(204); }),
      lista('/conversaciones/12/mensajes', () => ({
        items: [
          { id: 54, conversacion_id: 12, direccion: 'entrante', autor: 'cliente', usuario: null, tipo: 'texto', cuerpo: 'Hola', plantilla: null, media: [], boton: null, estado: 'recibido', error: null, programado_para: null, creado_en: '2026-10-24T15:00:00Z', enviado_en: null, entregado_en: null, leido_en: null },
          { id: 55, conversacion_id: 12, direccion: 'saliente', autor: 'agente', usuario: { id: 1, nombre: 'A' }, tipo: 'texto', cuerpo: 'Buenos días', plantilla: null, media: [], boton: null, estado: 'enviado', error: null, programado_para: null, creado_en: '2026-10-24T15:01:00Z', enviado_en: null, entregado_en: null, leido_en: null },
        ], hay_mas: false,
      })),
    );
    renderizarAppTiempoReal('/campanas');
    const menu = await screen.findByRole('navigation', { name: 'Principal' });
    const u = userEvent.setup();
    await u.click(await within(menu).findByRole('link', { name: 'Simulador WhatsApp' }));
    await u.type(await screen.findByLabelText('Número del cliente'), '300 123 4567');
    await u.type(screen.getByLabelText('Texto del mensaje'), 'STOP');
    await u.selectOptions(screen.getByLabelText('Adjunto simulado'), 'image/png');
    await u.click(screen.getByLabelText(/Pulsar el botón/));
    await u.click(screen.getByRole('button', { name: 'Enviar mensaje del cliente' }));
    expect(await screen.findByText(/Mensaje simulado recibido \(id 101\)/)).toBeInTheDocument();
    expect(entrantes[0]).toEqual({
      numero: '300 123 4567', texto: 'STOP', nombre_perfil: null, media: [{ tipo_contenido: 'image/png' }],
      boton_payload: 'BAJA', boton_texto: 'Darme de baja',
    });

    await u.type(screen.getByLabelText('Número de la conversación'), '12');
    await u.click(screen.getByRole('button', { name: 'Cargar salientes' }));
    expect(await screen.findByText(/Buenos días/)).toBeInTheDocument();
    expect(screen.queryByText(/Mensaje 54/)).not.toBeInTheDocument(); // los entrantes no se listan
    await u.selectOptions(screen.getByLabelText('Nuevo estado del mensaje 55'), 'failed');
    await u.click(screen.getByRole('button', { name: /Aplicar estado/ }));
    await waitFor(() => expect(estados).toEqual([{ estado: 'failed', error_codigo: '63016' }]));
  });

  it('sin simulación no hay enlace en el menú y la página lo explica', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(lista('/whatsapp/configuracion', () => configuracion({ simulacion: false, proveedor: 'twilio' })));
    renderizarAppTiempoReal('/whatsapp/simulador');
    expect(await screen.findByText(/La simulación no está habilitada/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Simulador WhatsApp' })).not.toBeInTheDocument();
  });

  it('supervisión: tarjeta del worker con aviso si no hay trabajador activo', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      lista('/supervision/agentes', () => []),
      lista('/supervision/trabajos', () => ({
        trabajadores: [{ trabajador: 'worker-1', ultimo_latido: '2026-10-24T15:00:05Z', activo: false }],
        por_estado: [{ tipo: 'whatsapp.enviar_mensaje', estado: 'pendiente', total: 3 }],
        fallidos_recientes: [{ id: 88, tipo: 'whatsapp.enviar_mensaje', ultimo_error: 'ErrorTrabajo:63003', intentos: 1, actualizado_en: '2026-10-24T14:58:00Z' }],
      })),
    );
    renderizarAppTiempoReal('/supervision/agentes');
    const alerta = await screen.findByText(/No hay un trabajador activo/);
    expect(alerta).toHaveTextContent('Hay 3 trabajos pendientes.');
    expect(screen.getByText('ErrorTrabajo:63003')).toBeInTheDocument();
    expect(screen.getAllByRole('rowheader', { name: 'whatsapp.enviar_mensaje' })).toHaveLength(2);
  });

  it('supervisión: con un trabajador activo no hay aviso', async () => {
    iniciarSesionComo('administrador');
    simularFetch(
      lista('/supervision/agentes', () => []),
      lista('/supervision/trabajos', () => ({
        trabajadores: [{ trabajador: 'worker-1', ultimo_latido: '2026-10-24T15:00:05Z', activo: true }], por_estado: [], fallidos_recientes: [],
      })),
    );
    renderizarAppTiempoReal('/supervision/agentes');
    expect(await screen.findByText(/1 trabajador activo/)).toBeInTheDocument();
    expect(screen.queryByText(/No hay un trabajador activo/)).not.toBeInTheDocument();
  });
});
