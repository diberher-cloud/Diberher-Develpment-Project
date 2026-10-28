import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Conversacion, ItemCola, Mensaje } from '../api/tipos';
import { hoyBogota, sumarDias } from '../utilidades/formato';
import {
  abrirSocket, campanaEjemplo, emitirEvento, errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta,
  simularFetch, WebSocketFalso, type Manejador,
} from './utiles';
import {
  configuracion, consulta, conversacion, itemCola, mensaje, pagina, plantilla, resumen,
} from './utilesWhatsApp';

const get = (ruta: string, cuerpo: () => unknown): Manejador => (url, i) =>
  (url.split('?')[0] === `/api/v1${ruta}` && (i.method ?? 'GET') === 'GET' ? respuesta(200, cuerpo()) : undefined);
const post = (ruta: string, f: (cuerpo: Record<string, unknown>) => Response | Promise<Response>): Manejador => (url, i) =>
  (url.split('?')[0] === `/api/v1${ruta}` && i.method === 'POST' ? f(i.body ? JSON.parse(String(i.body)) : {}) : undefined);

/** Servidor mínimo con estado para una conversación (id 12). */
function servidor(c: {
  conv?: Conversacion; mensajes?: Mensaje[]; cola?: ItemCola[]; extra?: Manejador[];
  mensajesPorPagina?: (antesDe: number | null) => { items: Mensaje[]; hay_mas: boolean };
} = {}) {
  const estado = { conv: c.conv ?? conversacion(), mensajes: c.mensajes ?? [mensaje()], cola: c.cola ?? [] };
  const m = simularFetch(
    ...(c.extra ?? []),
    get('/whatsapp/configuracion', () => configuracion()),
    get('/atencion/cola', () => estado.cola),
    get('/conversaciones', () => pagina([resumen({ ...estado.conv })])),
    get('/conversaciones/12', () => estado.conv),
    (url, i) => {
      if (url.split('?')[0] !== '/api/v1/conversaciones/12/mensajes' || (i.method ?? 'GET') !== 'GET') return undefined;
      const antes = consulta(url).get('antes_de');
      return respuesta(200, c.mensajesPorPagina ? c.mensajesPorPagina(antes ? Number(antes) : null) : { items: estado.mensajes, hay_mas: false });
    },
    post('/conversaciones/12/leida', () => respuesta(204)),
  );
  return { m, estado };
}

const llamadas = (m: ReturnType<typeof simularFetch>) => m.mock.calls.map(([u, i]) => `${(i as RequestInit | undefined)?.method ?? 'GET'} ${String(u)}`);

beforeEach(() => {
  instalarWebSocketFalso();
});

describe('Bandeja: flujo completo del agente', () => {
  it('entrante en cola -> tomar siguiente -> responder -> entregado por evento -> cerrar con promesa', async () => {
    iniciarSesionComo('agente');
    const { m, estado } = servidor({
      conv: conversacion({ atendida_por: 'sin_asignar', usuario_asignado: null, puede_responder: false, motivos_no_responder: [{ codigo: 'NO_ES_DUENO', mensaje: 'No es el dueño.' }] }),
      extra: [
        post('/atencion/tomar-siguiente', () => {
          estado.cola = [];
          estado.conv = conversacion();
          return respuesta(200, estado.conv);
        }),
        post('/conversaciones/12/mensajes', (cuerpo) => {
          const enviado = mensaje({ id: 102, direccion: 'saliente', autor: 'agente', usuario: { id: 1, nombre: 'Usuario agente' }, cuerpo: String(cuerpo.texto), estado: 'pendiente', creado_en: new Date().toISOString() });
          estado.mensajes = [...estado.mensajes, enviado];
          return respuesta(202, enviado);
        }),
        post('/conversaciones/12/cerrar', (cuerpo) => {
          estado.conv = conversacion({ estado: 'cerrada', cerrada_en: new Date().toISOString(), motivo_cierre: 'agente', puede_responder: false, tipificada: true });
          return respuesta(200, { conversacion: estado.conv, tipificacion: { id: 7, ...cuerpo } });
        }),
      ],
    });
    estado.cola = [];
    renderizarAppTiempoReal('/bandeja');
    const ws = await abrirSocket(1, 'agente');
    expect(await screen.findByText('La cola está vacía.')).toBeInTheDocument();

    // Llega un entrante: el evento hace recargar la cola.
    estado.cola = [itemCola()];
    emitirEvento(ws, { tipo: 'atencion.cola', datos: { cola_id: 40, conversacion_id: 12, campana_id: 1, motivo: 'entrante', accion: 'encolada' } });
    expect(await screen.findByText('1 conversación en espera.')).toBeInTheDocument();
    expect(screen.getByText(/Mensaje entrante/)).toBeInTheDocument();

    const u = userEvent.setup();
    await u.click(screen.getByRole('button', { name: 'Tomar siguiente' }));
    expect(await screen.findByRole('heading', { name: 'María Pérez' })).toBeInTheDocument();
    expect(screen.getByText('Hola, quiero pagar')).toBeInTheDocument();
    expect(screen.getByText(/Ventana de 24 h abierta: quedan 19:/)).toBeInTheDocument();

    // Marca leída solo si hay no leídos; responder con Enter.
    await u.type(screen.getByLabelText('Mensaje'), 'Buenos días, le ayudo{Enter}');
    expect(await screen.findByText('Buenos días, le ayudo')).toBeInTheDocument();
    expect(screen.getByText(/Pendiente de envío/)).toBeInTheDocument();
    const envio = m.mock.calls.find(([url, i]) => String(url).endsWith('/conversaciones/12/mensajes') && i?.method === 'POST')!;
    const cuerpoEnvio = JSON.parse(String(envio[1]!.body));
    expect(cuerpoEnvio.texto).toBe('Buenos días, le ayudo');
    expect(cuerpoEnvio.idempotencia_clave).toMatch(/^[0-9a-f-]{36}$/);

    // El estado "entregado" llega por WebSocket y se refleja sin recargar la página.
    estado.mensajes = estado.mensajes.map((x) => (x.id === 102 ? { ...x, estado: 'entregado' as const } : x));
    emitirEvento(ws, { tipo: 'conversacion.mensaje', datos: { conversacion_id: 12, mensaje_id: 102, campana_id: 1, usuario_asignado_id: 1, direccion: 'saliente', autor: 'agente', estado: 'entregado', accion: 'estado' } });
    expect(await screen.findByText(/Entregado/)).toBeInTheDocument();

    // Cierre con tipificación: promesa de pago.
    await u.click(screen.getByRole('button', { name: 'Cerrar conversación' }));
    const form = await screen.findByRole('form', { name: 'Formulario de tipificación' });
    const opciones = within(form).getAllByRole('option').map((o) => o.textContent);
    expect(opciones).not.toContain('No contesta'); // el cliente escribió
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'promesa_pago');
    await u.type(within(form).getByLabelText(/Monto prometido/), '250000.50');
    await u.type(within(form).getByLabelText('Fecha de pago'), sumarDias(hoyBogota(), 3));
    await u.click(within(form).getByRole('button', { name: 'Cerrar conversación' }));
    expect(await screen.findByText(/Conversación cerrada \(Cerrada por el agente\)/)).toBeInTheDocument();
    const cierre = m.mock.calls.find(([url]) => String(url).endsWith('/cerrar'))!;
    expect(JSON.parse(String(cierre[1]!.body))).toEqual({
      tipificacion: { resultado: 'promesa_pago', observacion: null, promesa: { monto: '250000.50', fecha_pago: sumarDias(hoyBogota(), 3) } },
    });
    expect(screen.queryByLabelText('Mensaje')).not.toBeInTheDocument();
  });

  it('un evento de otra conversación no altera la vista abierta', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    await screen.findByText('Hola, quiero pagar');
    const antes = llamadas(m).filter((x) => x.includes('/conversaciones/12')).length;
    emitirEvento(ws, { tipo: 'conversacion.mensaje', datos: { conversacion_id: 99, mensaje_id: 500, campana_id: 1, usuario_asignado_id: 1, direccion: 'entrante', autor: 'cliente', estado: 'recibido', accion: 'nuevo' } });
    emitirEvento(ws, { tipo: 'conversacion.estado', datos: { conversacion_id: 99, campana_id: 1, estado: 'cerrada', atendida_por: 'humano', usuario_asignado_id: 1, usuario_anterior_id: null, motivo_cierre: 'agente' } });
    await new Promise((r) => setTimeout(r, 50));
    expect(llamadas(m).filter((x) => x.includes('/conversaciones/12')).length).toBe(antes);
    expect(screen.getByRole('heading', { name: 'María Pérez' })).toBeInTheDocument();
  });

  it('un mensaje nuevo de la conversación abierta se anuncia en la región aria-live y se marca como leído', async () => {
    iniciarSesionComo('agente');
    const { m, estado } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    const log = await screen.findByRole('log', { name: 'Mensajes de la conversación' });
    expect(log).toHaveAttribute('aria-live', 'polite');
    estado.mensajes = [...estado.mensajes, mensaje({ id: 103, cuerpo: 'Ya hice la transferencia' })];
    estado.conv = conversacion({ mensajes_sin_leer: 1 });
    emitirEvento(ws, { tipo: 'conversacion.mensaje', datos: { conversacion_id: 12, mensaje_id: 103, campana_id: 1, usuario_asignado_id: 1, direccion: 'entrante', autor: 'cliente', estado: 'recibido', accion: 'nuevo' } });
    expect(await within(log).findByText('Ya hice la transferencia')).toBeInTheDocument();
    await waitFor(() => expect(llamadas(m)).toContain('POST /api/v1/conversaciones/12/leida'));
  });

  it('al reconectar el WebSocket se recarga la conversación abierta', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    await screen.findByText('Hola, quiero pagar');
    const antes = llamadas(m).filter((x) => x === 'GET /api/v1/conversaciones/12').length;
    act(() => ws.caer(1006));
    await waitFor(() => expect(WebSocketFalso.instancias.length).toBe(2), { timeout: 3000 });
    await abrirSocket(1, 'agente');
    await waitFor(() => expect(llamadas(m).filter((x) => x === 'GET /api/v1/conversaciones/12').length).toBeGreaterThan(antes));
  });

  it('el agente nunca ve un E.164 completo, ni aunque el servidor lo enviara', async () => {
    iniciarSesionComo('agente');
    servidor({ conv: conversacion({ numero_e164: '+573001234567', cliente_nombre: null, nombre_perfil: null }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await screen.findByRole('heading', { name: 'Cliente sin identificar' });
    expect(document.body.textContent).not.toContain('+573001234567');
    expect(screen.getAllByText(/\+57300\*\*\*\*567/).length).toBeGreaterThan(0);
  });

  it('el supervisor sí ve el número completo', async () => {
    iniciarSesionComo('supervisor');
    servidor({ conv: conversacion({ numero_e164: '+573001234567', atendida_por: 'sin_asignar', usuario_asignado: null }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await screen.findByRole('heading', { name: 'María Pérez' });
    expect(document.body.textContent).toContain('+573001234567');
  });
});

describe('Bandeja: compositor e idempotencia', () => {
  it('reintenta con la MISMA idempotencia_clave tras un fallo de red y usa otra en el siguiente mensaje', async () => {
    iniciarSesionComo('agente');
    let intentos = 0;
    const { m } = servidor({
      extra: [
        post('/conversaciones/12/mensajes', (cuerpo) => {
          intentos += 1;
          if (intentos === 1) return errorApi(503, 'SERVICIO_NO_DISPONIBLE', 'Servicio no disponible.');
          return respuesta(202, mensaje({ id: 200 + intentos, direccion: 'saliente', autor: 'agente', usuario: { id: 1, nombre: 'Usuario agente' }, cuerpo: String(cuerpo.texto), estado: 'pendiente' }));
        }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    const caja = await screen.findByLabelText('Mensaje');
    await u.type(caja, 'Le confirmo el pago');
    await u.click(screen.getByRole('button', { name: 'Enviar' }));
    expect(await screen.findByText('Servicio no disponible.')).toBeInTheDocument();
    expect(caja).toHaveValue('Le confirmo el pago'); // el texto se conserva para reintentar
    await u.click(screen.getByRole('button', { name: 'Enviar' }));
    await waitFor(() => expect(caja).toHaveValue(''));
    await u.type(caja, 'Otro mensaje');
    await u.click(screen.getByRole('button', { name: 'Enviar' }));
    await waitFor(() => expect(intentos).toBe(3));

    const claves = m.mock.calls
      .filter(([url, i]) => String(url).endsWith('/conversaciones/12/mensajes') && i?.method === 'POST')
      .map(([, i]) => JSON.parse(String(i!.body)).idempotencia_clave as string);
    expect(claves).toHaveLength(3);
    expect(claves[1]).toBe(claves[0]);
    expect(claves[2]).not.toBe(claves[0]);
  });

  it('muestra el contador de caracteres, no envía con Mayús+Enter y bloquea por encima del máximo', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    const caja = await screen.findByLabelText('Mensaje');
    expect(screen.getByText(/0 \/ 4096 caracteres/)).toBeInTheDocument();
    await u.type(caja, 'Hola{Shift>}{Enter}{/Shift}Adiós');
    expect(caja).toHaveValue('Hola\nAdiós');
    expect(screen.getByText(/10 \/ 4096 caracteres/)).toBeInTheDocument();
    expect(llamadas(m).some((x) => x.startsWith('POST') && x.endsWith('/mensajes'))).toBe(false);
    await u.clear(caja);
    await u.click(caja);
    await u.paste('x'.repeat(4100));
    expect(screen.getByText(/4100 \/ 4096 caracteres/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeDisabled();
  });

  it('deshabilitado con el motivo cuando no es el dueño', async () => {
    iniciarSesionComo('supervisor');
    servidor({ conv: conversacion({ atendida_por: 'humano', usuario_asignado: { id: 9, nombre: 'Otro agente' }, puede_responder: false, motivos_no_responder: [{ codigo: 'NO_ES_DUENO', mensaje: 'La conversación la atiende otro agente.' }] }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const caja = await screen.findByLabelText('Mensaje');
    expect(caja).toBeDisabled();
    expect(screen.getByText('La conversación la atiende otro agente.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeDisabled();
  });
});

describe('Bandeja: ventana cerrada y plantillas', () => {
  const cerrada = () => conversacion({
    ventana_abierta: false, ventana_expira_en: new Date(Date.now() - 3_600_000).toISOString(), puede_responder: false,
    motivos_no_responder: [{ codigo: 'VENTANA_CERRADA', mensaje: 'La ventana de 24 h está cerrada.' }],
  });

  it('con la ventana cerrada solo ofrece plantillas, con vista previa, y las envía', async () => {
    iniciarSesionComo('agente');
    let clave = '';
    const { m, estado } = servidor({
      conv: cerrada(),
      extra: [
        get('/whatsapp/plantillas', () => [plantilla(), plantilla({ id: 4, nombre: 'oferta_venta', cuerpo: 'Hola {{1}}, {{2}} le ofrece {{3}}.', variables: ['1', '2', '3'], mapeo_variables: { '1': 'primer_nombre', '2': 'empresa', '3': 'producto' } })]),
        post('/conversaciones/12/plantillas', (cuerpo) => {
          clave = String(cuerpo.idempotencia_clave);
          const enviado = mensaje({ id: 300, direccion: 'saliente', autor: 'agente', usuario: { id: 1, nombre: 'Usuario agente' }, tipo: 'plantilla', plantilla: { id: 3, nombre: 'recordatorio_cobranza' }, cuerpo: 'Hola María, le escribimos de Mi Empresa.', estado: 'pendiente' });
          estado.mensajes = [...estado.mensajes, enviado];
          return respuesta(200, { permitido: true, motivos: [], proxima_ventana_inicio: null, politica_version: 1, conversacion_id: 12, mensaje: enviado });
        }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    expect(await screen.findByText('Ventana de 24 h cerrada: solo plantillas.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Mensaje')).not.toBeInTheDocument();
    const u = userEvent.setup();
    const sel = await screen.findByLabelText('Plantilla');
    await u.selectOptions(sel, 'recordatorio_cobranza');
    expect(screen.getByLabelText('Vista previa de la plantilla')).toHaveTextContent('Hola [Primer nombre del cliente], le escribimos de [Nombre de la empresa].');
    const consultaPlantillas = llamadas(m).find((x) => x.includes('/whatsapp/plantillas'))!;
    expect(consultaPlantillas).toContain('campana_id=1');
    expect(consultaPlantillas).toContain('enviables=true');
    await u.click(screen.getByRole('button', { name: 'Enviar plantilla' }));
    expect(await screen.findByText('Hola María, le escribimos de Mi Empresa.')).toBeInTheDocument();
    expect(clave).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('un 409 VENTANA_CERRADA al enviar texto recarga la conversación y muestra el selector de plantillas', async () => {
    iniciarSesionComo('agente');
    const srv: ReturnType<typeof servidor> = servidor({
      extra: [
        get('/whatsapp/plantillas', () => [plantilla()]),
        post('/conversaciones/12/mensajes', () => {
          srv.estado.conv = cerrada(); // la ventana se cerró mientras escribía
          return errorApi(409, 'VENTANA_CERRADA', 'La ventana de 24 h está cerrada.');
        }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Mensaje'), 'Hola{Enter}');
    expect(await screen.findByText('La ventana de 24 h está cerrada.')).toBeInTheDocument();
    expect(await screen.findByLabelText('Plantilla')).toBeInTheDocument();
  });

  it('el resultado bloqueado por cumplimiento (permitido=false, HTTP 200) muestra motivos y próxima ventana, sin mensaje nuevo', async () => {
    iniciarSesionComo('agente');
    servidor({
      conv: cerrada(),
      extra: [
        get('/whatsapp/plantillas', () => [plantilla()]),
        post('/conversaciones/12/plantillas', () => respuesta(200, {
          permitido: false,
          motivos: [
            { codigo: 'SIN_AUTORIZACION', mensaje: 'El número no tiene autorización vigente para WhatsApp (cobranza).' },
            { codigo: 'FUERA_DE_FRANJA', mensaje: 'Fuera de la franja permitida.' },
          ],
          proxima_ventana_inicio: '2026-10-26T07:00:00-05:00', politica_version: 1, conversacion_id: null, mensaje: null,
        })),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.selectOptions(await screen.findByLabelText('Plantilla'), 'recordatorio_cobranza');
    await u.click(screen.getByRole('button', { name: 'Enviar plantilla' }));
    const alerta = await screen.findByText('La plantilla no se envió por cumplimiento.');
    const caja = alerta.closest('[role="alert"]') as HTMLElement;
    expect(within(caja).getByText(/SIN_AUTORIZACION/)).toBeInTheDocument();
    expect(within(caja).getByText(/Fuera de la franja permitida/)).toBeInTheDocument();
    expect(within(caja).getByText(/Próxima ventana: .*26/)).toBeInTheDocument();
    expect(screen.queryByText(/Hola María/)).not.toBeInTheDocument();
  });
});

describe('Bandeja: contenido no confiable y adjuntos', () => {
  it('un mensaje del cliente con HTML/script se muestra como texto, nunca como HTML', async () => {
    iniciarSesionComo('agente');
    const peligro = '<img src=x onerror="alert(1)"><script>window.hackeado = true</script><b>negrita</b>';
    servidor({ mensajes: [mensaje({ cuerpo: peligro })], conv: conversacion({ nombre_perfil: '<i>Perfil</i>', cliente_nombre: null }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const log = await screen.findByRole('log', { name: 'Mensajes de la conversación' });
    expect(within(log).getByText(peligro)).toBeInTheDocument();
    expect(log.querySelector('script')).toBeNull();
    expect(log.querySelector('img')).toBeNull();
    expect(log.querySelector('b')).toBeNull();
    expect(screen.getByRole('heading', { name: '<i>Perfil</i>' })).toBeInTheDocument();
    expect((window as unknown as { hackeado?: boolean }).hackeado).toBeUndefined();
  });

  it('el adjunto se descarga como blob con el Bearer desde el proxy, se muestra desde blob: y se revoca al desmontar', async () => {
    iniciarSesionComo('agente');
    const crear = vi.fn(() => 'blob:http://localhost/abc');
    const revocar = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: crear, revokeObjectURL: revocar }));
    servidor({
      mensajes: [mensaje({
        tipo: 'media', cuerpo: 'Le envío el comprobante',
        media: [
          { indice: 0, categoria: 'imagen', tipo_contenido: 'image/jpeg', disponible: true },
          { indice: 1, categoria: 'no_soportado', tipo_contenido: 'video/mp4', disponible: false },
        ],
      })],
      extra: [(url) => (url === '/api/v1/conversaciones/12/mensajes/101/media/0'
        ? new Response(new Blob(['binario'], { type: 'image/jpeg' }), { status: 200, headers: { 'Content-Type': 'image/jpeg' } })
        : undefined)],
    });
    const { unmount } = renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    expect(await screen.findByText('Adjunto no soportado (video/mp4)')).toBeInTheDocument();
    await u.click(await screen.findByRole('button', { name: /Ver imagen/ }));
    const img = await screen.findByRole('img', { name: /Adjunto 1 del mensaje 101/ });
    expect(img).toHaveAttribute('src', 'blob:http://localhost/abc');
    const peticion = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(([url]) => String(url).includes('/media/0'))!;
    expect((peticion[1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer token-de-prueba' });
    expect(document.body.innerHTML).not.toContain('twilio');
    unmount();
    expect(revocar).toHaveBeenCalledWith('blob:http://localhost/abc');
  });

  it('un error del proxy (413) se informa junto al adjunto', async () => {
    iniciarSesionComo('agente');
    servidor({
      mensajes: [mensaje({ tipo: 'media', cuerpo: null, media: [{ indice: 0, categoria: 'documento', tipo_contenido: 'application/pdf', disponible: true }] })],
      extra: [(url) => (url.includes('/media/0') ? errorApi(413, 'MEDIA_DEMASIADO_GRANDE', 'El archivo supera el tamaño máximo.') : undefined)],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await userEvent.setup().click(await screen.findByRole('button', { name: /Ver documento PDF/ }));
    expect(await screen.findByText('El archivo supera el tamaño máximo.')).toBeInTheDocument();
  });
});

describe('Bandeja: historial paginado hacia atrás', () => {
  it('carga mensajes anteriores con antes_de y conserva el orden ascendente', async () => {
    iniciarSesionComo('agente');
    const reciente = [mensaje({ id: 51, cuerpo: 'mensaje 51' }), mensaje({ id: 52, cuerpo: 'mensaje 52' })];
    const antiguos = [mensaje({ id: 49, cuerpo: 'mensaje 49' }), mensaje({ id: 50, cuerpo: 'mensaje 50' })];
    const { m } = servidor({ mensajesPorPagina: (antes) => (antes === null ? { items: reciente, hay_mas: true } : { items: antiguos, hay_mas: false }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await screen.findByText('mensaje 51');
    await u.click(screen.getByRole('button', { name: 'Cargar mensajes anteriores' }));
    await screen.findByText('mensaje 49');
    expect(llamadas(m).some((x) => x.includes('antes_de=51') && x.includes('limite=50'))).toBe(true);
    const textos = screen.getAllByText(/^mensaje \d+$/).map((e) => e.textContent);
    expect(textos).toEqual(['mensaje 49', 'mensaje 50', 'mensaje 51', 'mensaje 52']);
    expect(screen.queryByRole('button', { name: 'Cargar mensajes anteriores' })).not.toBeInTheDocument();
  });
});

describe('Bandeja: puntuación de fechas', () => {
  it('la conversación cerrada en la mañana termina en un solo punto ("a. m.")', async () => {
    iniciarSesionComo('agente');
    servidor({ conv: conversacion({ estado: 'cerrada', motivo_cierre: 'agente', cerrada_en: '2026-10-26T14:00:00Z', puede_responder: false }) });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const aviso = await screen.findByText(/Conversación cerrada \(Cerrada por el agente\) el/);
    expect(aviso.textContent).toMatch(/a\.\s?m\.$/);
    expect(aviso.textContent).not.toContain('..');
  });
});

describe('Bandeja: estado de los mensajes y retenidos', () => {
  it('muestra fallido con el mensaje del error y retenido con la hora programada', async () => {
    iniciarSesionComo('agente');
    const saliente = { direccion: 'saliente' as const, autor: 'agente' as const, usuario: { id: 1, nombre: 'Usuario agente' } };
    servidor({
      mensajes: [
        mensaje({ id: 1, ...saliente, cuerpo: 'falló', estado: 'fallido', error: { codigo: '63003', mensaje: 'El número no está disponible en WhatsApp.' } }),
        mensaje({ id: 2, ...saliente, cuerpo: 'espera', estado: 'retenido', programado_para: '2026-10-26T12:00:00Z' }),
        mensaje({ id: 3, direccion: 'saliente', autor: 'sistema', cuerpo: 'Aviso automático', estado: 'leido' }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    expect(await screen.findByText(/Fallido: El número no está disponible en WhatsApp\./)).toBeInTheDocument();
    expect(screen.getByText(/Retenido hasta .*26/)).toBeInTheDocument();
    expect(screen.getByText('1 mensaje retenido hasta la próxima franja permitida.')).toBeInTheDocument();
    expect(screen.getByText(/Leído/)).toBeInTheDocument();
    expect(screen.getByText('Sistema')).toBeInTheDocument();
  });
});

describe('Bandeja: acciones de la conversación', () => {
  it('supervisor: cola con Tomar y Asignar a…, y asignación a un agente de la campaña', async () => {
    iniciarSesionComo('supervisor');
    let cuerpoAsignar: Record<string, unknown> = {};
    const { m, estado } = servidor({
      cola: [itemCola()],
      conv: conversacion({ atendida_por: 'sin_asignar', usuario_asignado: null, puede_responder: false, motivos_no_responder: [{ codigo: 'NO_ES_DUENO', mensaje: 'No es el dueño.' }] }),
      extra: [
        get('/campanas/1/agentes', () => [{ usuario_id: 6, nombre: 'Pedro Agente', email: 'p@e.co', activo: true, asignado_en: '2026-10-01T00:00:00Z' }]),
        get('/campanas', () => pagina([])),
        post('/conversaciones/12/asignar', (cuerpo) => {
          cuerpoAsignar = cuerpo;
          estado.conv = conversacion({ usuario_asignado: { id: 6, nombre: 'Pedro Agente' }, puede_responder: false });
          return respuesta(200, estado.conv);
        }),
      ],
    });
    renderizarAppTiempoReal('/bandeja');
    const u = userEvent.setup();
    expect(await screen.findByRole('button', { name: /Tomar conversación con/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tomar siguiente' })).not.toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Asignar a… conversación con/ }));
    await u.selectOptions(await screen.findByLabelText('Asignar a'), 'Pedro Agente');
    await u.click(screen.getByRole('button', { name: 'Confirmar asignación' }));
    await waitFor(() => expect(cuerpoAsignar).toEqual({ usuario_id: 6 }));
    expect(llamadas(m)).toContain('GET /api/v1/campanas/1/agentes');
  });

  it('vincula un registro candidato a una conversación sin registro', async () => {
    iniciarSesionComo('agente');
    let cuerpo: Record<string, unknown> = {};
    const { estado } = servidor({
      conv: conversacion({ campana: null, cliente_nombre: null, campana_cliente_id: null, cliente_id: null, telefono_id: null, alertas: [{ codigo: 'SIN_CAMPANA', mensaje: 'La conversación no está vinculada a ninguna campaña.' }] }),
      extra: [
        get('/conversaciones/12/registros-candidatos', () => [{ campana_cliente_id: 15, campana: { id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza' }, cliente_nombre: 'María Pérez', estado: 'pendiente' }]),
        (url, i) => {
          if (url !== '/api/v1/conversaciones/12/registro' || i.method !== 'PUT') return undefined;
          cuerpo = JSON.parse(String(i.body));
          estado.conv = conversacion();
          return respuesta(200, estado.conv);
        },
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    expect(await screen.findByText('La conversación no está vinculada a ninguna campaña.')).toBeInTheDocument();
    await u.click(await screen.findByRole('button', { name: 'Vincular registro' }));
    await u.click(await screen.findByRole('radio', { name: /María Pérez — Cobranza cartera octubre/ }));
    const panel = screen.getByRole('heading', { name: 'Vincular a un registro de campaña' }).closest('section') as HTMLElement;
    await u.click(within(panel).getByRole('button', { name: 'Vincular registro' }));
    await waitFor(() => expect(cuerpo).toEqual({ campana_cliente_id: 15 }));
    expect(await screen.findByText('Registro vinculado.')).toBeInTheDocument();
  });

  it('opt-out manual con alcance, y cierre sin tipificación cuando no hay registro', async () => {
    iniciarSesionComo('agente');
    const cuerpos: Record<string, unknown>[] = [];
    servidor({
      conv: conversacion({ campana: null, cliente_nombre: null, campana_cliente_id: null }),
      extra: [
        post('/conversaciones/12/opt-out', (c) => { cuerpos.push(c); return respuesta(200, conversacion({ estado: 'cerrada', motivo_cierre: 'opt_out', cerrada_en: new Date().toISOString(), puede_responder: false })); }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Registrar baja (opt-out)' }));
    await u.selectOptions(screen.getByLabelText('Alcance de la baja'), 'todos');
    await u.click(screen.getByRole('button', { name: 'Confirmar baja' }));
    await waitFor(() => expect(cuerpos).toEqual([{ alcance: 'todos' }]));
    expect(await screen.findByText(/Conversación cerrada \(Cerrada por solicitud de baja\)/)).toBeInTheDocument();
  });

  it('cierra sin tipificación una conversación sin registro y muestra el error del servidor si lo hay', async () => {
    iniciarSesionComo('agente');
    let n = 0;
    servidor({
      conv: conversacion({ campana: null, cliente_nombre: null, campana_cliente_id: null }),
      extra: [
        post('/conversaciones/12/cerrar', (c) => {
          n += 1;
          expect(c).toEqual({ tipificacion: null });
          return n === 1 ? errorApi(409, 'CONVERSACION_CERRADA', 'La conversación ya está cerrada.') : respuesta(200, { conversacion: conversacion({ estado: 'cerrada', cerrada_en: new Date().toISOString(), motivo_cierre: 'agente', puede_responder: false }), tipificacion: null });
        }),
      ],
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Cerrar conversación' }));
    const panel = (await screen.findByRole('heading', { name: 'Cerrar la conversación' })).closest('section') as HTMLElement;
    await u.click(within(panel).getByRole('button', { name: 'Cerrar conversación' }));
    expect(await within(panel).findByText('La conversación ya está cerrada.')).toBeInTheDocument();
    await u.click(within(panel).getByRole('button', { name: 'Cerrar conversación' }));
    expect(await screen.findByText(/Conversación cerrada \(Cerrada por el agente\)/)).toBeInTheDocument();
  });

  it('registra una autorización del cliente validando la evidencia', async () => {
    iniciarSesionComo('agente');
    let cuerpo: Record<string, unknown> | null = null;
    servidor({ extra: [post('/conversaciones/12/autorizacion', (c) => { cuerpo = c; return respuesta(201, { id: 7 }); })] });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Registrar autorización' }));
    const formulario = await screen.findByRole('form', { name: 'Registrar autorización del cliente' });
    await u.click(within(formulario).getByRole('button', { name: 'Registrar autorización' }));
    expect(await screen.findByText('La evidencia debe tener entre 5 y 500 caracteres.')).toBeInTheDocument();
    expect(cuerpo).toBeNull();
    await u.type(screen.getByLabelText('Evidencia'), 'Cliente acepta en el chat');
    await u.click(within(formulario).getByRole('button', { name: 'Registrar autorización' }));
    await waitFor(() => expect(cuerpo).toEqual({ finalidad: 'cobranza', evidencia: 'Cliente acepta en el chat' }));
  });
});

describe('Bandeja: cola y errores', () => {
  it('tomar siguiente sin conversaciones (204) lo informa; CAPACIDAD_MAXIMA se muestra como error', async () => {
    iniciarSesionComo('agente');
    let n = 0;
    servidor({
      cola: [itemCola()],
      extra: [post('/atencion/tomar-siguiente', () => (++n === 1 ? respuesta(204) : errorApi(409, 'CAPACIDAD_MAXIMA', 'Ya atiende el máximo de conversaciones.')))],
    });
    renderizarAppTiempoReal('/bandeja');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Tomar siguiente' }));
    expect(await screen.findByText('No hay conversaciones en la cola.')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Tomar siguiente' }));
    expect(await screen.findByText('Ya atiende el máximo de conversaciones.')).toBeInTheDocument();
  });

  it('el tiempo de espera de la cola corre en vivo', async () => {
    iniciarSesionComo('agente');
    servidor({ cola: [itemCola({ espera_segundos: 59 })] });
    renderizarAppTiempoReal('/bandeja');
    expect(await screen.findByText('00:00:59')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('00:01:00')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('el menú muestra el contador de no leídos de mis conversaciones y se actualiza por eventos', async () => {
    iniciarSesionComo('agente');
    const { estado } = servidor({ conv: conversacion({ mensajes_sin_leer: 3 }) });
    renderizarAppTiempoReal('/campanas');
    const ws = await abrirSocket(1, 'agente');
    const menu = await screen.findByRole('navigation', { name: 'Principal' });
    expect(await within(menu).findByRole('link', { name: 'Bandeja (3)' })).toBeInTheDocument();
    estado.conv = conversacion({ mensajes_sin_leer: 5 });
    emitirEvento(ws, { tipo: 'conversacion.mensaje', datos: { conversacion_id: 12, mensaje_id: 9, campana_id: 1, usuario_asignado_id: 1, direccion: 'entrante', autor: 'cliente', estado: 'recibido', accion: 'nuevo' } });
    expect(await within(menu).findByRole('link', { name: 'Bandeja (5)' })).toBeInTheDocument();
  });

  it('un error al cargar la conversación se informa con Reintentar', async () => {
    iniciarSesionComo('agente');
    simularFetch((url) => (url.startsWith('/api/v1/conversaciones/12') ? errorApi(403, 'CONVERSACION_NO_ASIGNADA', 'No puede ver esta conversación.') : undefined));
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    expect(await screen.findByText('No puede ver esta conversación.')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Reintentar' }).length).toBeGreaterThan(0);
  });
});

describe('Bandeja: apertura auditada y recargas agrupadas', () => {
  const evMsg = (id: number, accion: 'nuevo' | 'estado', mensajeId: number) => ({
    tipo: 'conversacion.mensaje' as const,
    datos: { conversacion_id: id, mensaje_id: mensajeId, campana_id: 1, usuario_asignado_id: 1, direccion: 'saliente' as const, autor: 'agente' as const, estado: 'entregado' as const, accion },
  });
  const urlsGet = (m: ReturnType<typeof simularFetch>, ruta: string) =>
    llamadas(m).filter((x) => x.startsWith('GET ') && x.replace('GET ', '').split('&')[0] === ruta);

  it('envía apertura=true una sola vez al abrir y sin el parámetro en recargas por eventos y reconexión', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    await screen.findByText('Hola, quiero pagar');
    expect(urlsGet(m, '/api/v1/conversaciones/12?apertura=true')).toHaveLength(1);
    emitirEvento(ws, { tipo: 'conversacion.estado', datos: { conversacion_id: 12, campana_id: 1, estado: 'abierta', atendida_por: 'humano', usuario_asignado_id: 1, usuario_anterior_id: null, motivo_cierre: null } });
    await waitFor(() => expect(urlsGet(m, '/api/v1/conversaciones/12')).toHaveLength(1), { timeout: 3000 });
    act(() => ws.caer(1006));
    await waitFor(() => expect(WebSocketFalso.instancias.length).toBe(2), { timeout: 3000 });
    await abrirSocket(1, 'agente');
    await waitFor(() => expect(urlsGet(m, '/api/v1/conversaciones/12')).toHaveLength(2), { timeout: 3000 });
    expect(llamadas(m).filter((x) => x.includes('apertura=true'))).toHaveLength(1);
  });

  it('una ráfaga de eventos de estado de mensajes ya cargados recarga solo los mensajes, una vez', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor({ mensajes: [mensaje({ id: 101 })] });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    await screen.findByText('Hola, quiero pagar');
    const msgs = () => urlsGet(m, '/api/v1/conversaciones/12/mensajes?limite=50').length;
    const antesMsgs = msgs();
    const antesConv = urlsGet(m, '/api/v1/conversaciones/12').length;
    for (let i = 0; i < 5; i++) emitirEvento(ws, evMsg(12, 'estado', 101));
    await waitFor(() => expect(msgs()).toBe(antesMsgs + 1), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 900));
    expect(msgs()).toBe(antesMsgs + 1);
    expect(urlsGet(m, '/api/v1/conversaciones/12').length).toBe(antesConv);
  });

  it('una ráfaga de mensajes nuevos produce una recarga de conversación y una de mensajes', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    const ws = await abrirSocket(1, 'agente');
    await screen.findByText('Hola, quiero pagar');
    const antesMsgs = urlsGet(m, '/api/v1/conversaciones/12/mensajes?limite=50').length;
    for (let i = 0; i < 4; i++) emitirEvento(ws, { ...evMsg(12, 'nuevo', 500 + i), datos: { ...evMsg(12, 'nuevo', 500 + i).datos, direccion: 'entrante', autor: 'cliente', estado: 'recibido' } });
    await waitFor(() => expect(urlsGet(m, '/api/v1/conversaciones/12').length).toBe(1), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 900));
    expect(urlsGet(m, '/api/v1/conversaciones/12').length).toBe(1);
    expect(urlsGet(m, '/api/v1/conversaciones/12/mensajes?limite=50').length).toBe(antesMsgs + 1);
  });

  it('la lista del supervisor agrupa los eventos y no recarga por estados de entrega ni por otra campaña filtrada', async () => {
    iniciarSesionComo('supervisor');
    const { m } = servidor({ extra: [get('/campanas', () => pagina([campanaEjemplo({ id: 1 }), campanaEjemplo({ id: 2, nombre: 'Venta' })]))] });
    renderizarAppTiempoReal('/bandeja');
    const ws = await abrirSocket(1, 'supervisor');
    await screen.findByText(/Cobranza cartera octubre/);
    const lista = () => llamadas(m).filter((x) => x.startsWith('GET /api/v1/conversaciones?') && x.includes('page_size=20')).length;
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Campaña'), '2');
    await waitFor(() => expect(llamadas(m).some((x) => x.includes('campana_id=2'))).toBe(true));
    const base = lista();
    // Estado de entrega y campaña distinta (conversación fuera de la lista): sin recarga.
    emitirEvento(ws, evMsg(77, 'estado', 1));
    emitirEvento(ws, { ...evMsg(77, 'nuevo', 2), datos: { ...evMsg(77, 'nuevo', 2).datos, campana_id: 1 } });
    await new Promise((r) => setTimeout(r, 1300));
    expect(lista()).toBe(base);
    // Ráfaga de mensajes nuevos de la campaña filtrada: una sola recarga.
    for (let i = 0; i < 5; i++) emitirEvento(ws, { ...evMsg(78, 'nuevo', 10 + i), datos: { ...evMsg(78, 'nuevo', 10 + i).datos, campana_id: 2 } });
    await waitFor(() => expect(lista()).toBe(base + 1), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 1300));
    expect(lista()).toBe(base + 1);
  });
});
