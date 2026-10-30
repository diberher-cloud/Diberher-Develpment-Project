import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { Conversacion, ItemCola, Mensaje } from '../api/tipos';
import {
  abrirSocket, errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch, type Manejador,
} from './utiles';
import { accion, estadoIA, ruta, rutaJson } from './utilesIA';
import { configuracion, conversacion, haceMin, itemCola, mensaje, pagina, resumen } from './utilesWhatsApp';

interface Estado { conv: Conversacion; mensajes: Mensaje[]; cola: ItemCola[] }

function servidor(parcial: Partial<Estado> = {}, extra: Manejador[] = []) {
  const e: Estado = { conv: conversacion(), mensajes: [mensaje()], cola: [], ...parcial };
  const m = simularFetch(
    ...extra,
    rutaJson('GET', '/whatsapp/configuracion', () => configuracion()),
    rutaJson('GET', '/atencion/cola', () => e.cola),
    rutaJson('GET', '/conversaciones', () => pagina([resumen({ ...e.conv })])),
    rutaJson('GET', '/conversaciones/12', () => e.conv),
    rutaJson('GET', '/conversaciones/12/mensajes', () => ({ items: e.mensajes, hay_mas: false })),
    rutaJson('GET', '/conversaciones/12/acciones-ia', () => [accion(), accion({ id: 78, herramienta: 'derivar_a_humano', efecto: 'derivacion', entrada: { motivo: 'solicitud_cliente' }, resultado: { derivada: true } })]),
    ruta('POST', '/conversaciones/12/leida', () => respuesta(204)),
    rutaJson('GET', '/campanas', () => pagina([])),
  );
  return { m, e };
}

const llamadas = (m: ReturnType<typeof simularFetch>, metodo: string, fin: string) =>
  m.mock.calls.filter(([u, i]) => String(u).split('?')[0].endsWith(fin) && ((i as RequestInit | undefined)?.method ?? 'GET') === metodo);

const traspaso = estadoIA({
  ultimo_traspaso: { motivo: 'solicitud_cliente', resumen: 'El cliente pidió hablar con un asesor por una duda de intereses.', creado_en: haceMin(2) },
});

beforeEach(() => {
  instalarWebSocketFalso();
});

describe('Bandeja con IA (F22)', () => {
  it('traspaso IA -> cola con resumen destacado -> tomar siguiente -> ver acciones -> devolver a la IA', async () => {
    iniciarSesionComo('agente');
    const { e, m } = servidor(
      {
        cola: [itemCola({ motivo: 'solicitud_cliente', resumen: 'El cliente pidió hablar con un asesor por una duda de intereses.', prioridad: 1 })],
        conv: conversacion({ atendida_por: 'sin_asignar', usuario_asignado: null, puede_responder: false, ia: traspaso }),
        mensajes: [
          mensaje({ id: 101, cuerpo: 'Quiero hablar con alguien' }),
          mensaje({ id: 102, direccion: 'saliente', autor: 'ia', cuerpo: '<b>Con gusto</b>, le comunico con un asesor.', estado: 'entregado' }),
        ],
      },
      [
        ruta('POST', '/atencion/tomar-siguiente', () => {
          e.cola = [];
          e.conv = conversacion({ atendida_por: 'humano', ia: traspaso });
          return respuesta(200, e.conv);
        }),
        ruta('POST', '/conversaciones/12/devolver-ia', () => {
          e.conv = conversacion({ atendida_por: 'ia', usuario_asignado: null, puede_responder: false, ia: estadoIA() });
          return respuesta(200, e.conv);
        }),
      ],
    );
    renderizarAppTiempoReal('/bandeja');
    await abrirSocket(1, 'agente');
    const u = userEvent.setup();

    // La cola muestra el resumen de la IA destacado.
    const resumenCola = await screen.findByText(/El cliente pidió hablar con un asesor/, { selector: '.item-cola p' });
    expect(resumenCola).toHaveClass('resumen-traspaso');
    expect(resumenCola).toHaveTextContent('Resumen de la IA:');

    await u.click(screen.getByRole('button', { name: 'Tomar siguiente' }));
    // Conversación abierta: mensaje de la IA diferenciado, como texto (no HTML) y estado de IA con el resumen del traspaso.
    const burbuja = (await screen.findByText('<b>Con gusto</b>, le comunico con un asesor.')).closest('li')!;
    expect(burbuja).toHaveClass('burbuja-ia');
    expect(within(burbuja).getByText('Asistente IA')).toBeInTheDocument();
    expect(burbuja.querySelector('b')).toBeNull();
    const estado = screen.getByRole('region', { name: 'Atención con IA' });
    expect(within(estado).getByText('Agente humano: Usuario agente')).toBeInTheDocument();
    expect(within(estado).getByText(/Solicitud del cliente/)).toBeInTheDocument();
    expect(within(estado).getByText('El cliente pidió hablar con un asesor por una duda de intereses.')).toBeInTheDocument();
    expect(within(estado).queryByText(/Coste/)).not.toBeInTheDocument(); // el agente no ve costes

    // Acciones de la IA (el agente dueño las ve).
    const panel = (await screen.findByText(/Acciones de la IA \(2\)/)).closest('details')!;
    expect(within(panel).getByText('derivar_a_humano')).toBeInTheDocument();
    expect(within(panel).getByText('{"numero_documento":"***4050"}')).toBeInTheDocument();

    // Devolver a la IA.
    await u.click(screen.getByRole('button', { name: 'Devolver a la IA' }));
    expect(await screen.findByText('Conversación devuelta a la IA.')).toBeInTheDocument();
    expect(llamadas(m, 'POST', '/conversaciones/12/devolver-ia')).toHaveLength(1);
    await waitFor(() => expect(screen.getByRole('region', { name: 'Atención con IA' })).toHaveTextContent('Asistente IA'));
    expect(screen.queryByRole('button', { name: 'Devolver a la IA' })).not.toBeInTheDocument();
  });

  it('"Devolver a la IA" queda deshabilitado y explica los motivos_no_devolver', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor({
      conv: conversacion({
        ia: estadoIA({ puede_devolver_ia: false, motivos_no_devolver: [{ codigo: 'CLIENTE_OPT_OUT', mensaje: 'El cliente pidió no recibir más mensajes.' }] }),
      }),
    });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'agente');
    const boton = await screen.findByRole('button', { name: 'Devolver a la IA' });
    expect(boton).toBeDisabled();
    expect(boton).toHaveAccessibleDescription('El cliente pidió no recibir más mensajes.');
    expect(llamadas(m, 'POST', '/devolver-ia')).toHaveLength(0);
  });

  it('si el servidor rechaza la devolución (409 IA_NO_DISPONIBLE) se muestra el motivo', async () => {
    iniciarSesionComo('agente');
    servidor({ conv: conversacion({ ia: estadoIA() }) }, [
      ruta('POST', '/conversaciones/12/devolver-ia', () => errorApi(409, 'IA_NO_DISPONIBLE', 'x')),
    ]);
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'agente');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Devolver a la IA' }));
    expect(await screen.findByText(/La IA no está disponible para esta conversación/)).toBeInTheDocument();
  });

  it('el supervisor puede tomar y traspasar una conversación que atiende la IA; el agente no', async () => {
    iniciarSesionComo('supervisor');
    const iaConv = conversacion({ atendida_por: 'ia', usuario_asignado: null, puede_responder: false, ia: estadoIA() });
    servidor({ conv: iaConv });
    const { unmount } = renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'supervisor');
    const acciones = await screen.findByRole('group', { name: 'Acciones de la conversación' });
    expect(within(acciones).getByRole('button', { name: 'Tomar' })).toBeInTheDocument();
    expect(within(acciones).getByRole('button', { name: 'Traspasar a cola' })).toBeInTheDocument();
    expect(within(acciones).getByRole('button', { name: 'Asignar a…' })).toBeInTheDocument();
    expect(within(acciones).queryByRole('button', { name: 'Devolver a la IA' })).not.toBeInTheDocument();
    // El supervisor ve el coste de la conversación.
    expect(within(screen.getByRole('region', { name: 'Atención con IA' })).getByText(/Coste:/)).toBeInTheDocument();
    unmount();

    sessionStorage.clear();
    iniciarSesionComo('agente');
    servidor({ conv: iaConv });
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'agente');
    const acc2 = await screen.findByRole('group', { name: 'Acciones de la conversación' });
    expect(within(acc2).queryByRole('button', { name: 'Tomar' })).not.toBeInTheDocument();
    expect(within(acc2).queryByRole('button', { name: 'Traspasar a cola' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Acciones de la IA/)).not.toBeInTheDocument(); // no es el dueño
  });

  it('conversación ya tipificada por la IA: cierra sin formulario y envía tipificacion null', async () => {
    iniciarSesionComo('agente');
    let cuerpo: unknown;
    const { e } = servidor(
      { conv: conversacion({ tipificada: true, ia: estadoIA({ gestion: { resultado: 'promesa_pago', tipificacion_id: 41 } }) }) },
      [ruta('POST', '/conversaciones/12/cerrar', (c) => {
        cuerpo = c;
        e.conv = conversacion({ estado: 'cerrada', tipificada: true, motivo_cierre: 'agente', cerrada_en: new Date().toISOString(), puede_responder: false, ia: estadoIA({ gestion: { resultado: 'promesa_pago', tipificacion_id: 41 } }) });
        return respuesta(200, { conversacion: e.conv, tipificacion: null });
      })],
    );
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'agente');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Cerrar conversación' }));
    expect(screen.getByText(/ya tiene una gestión registrada \(Promesa de pago\)/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Resultado')).not.toBeInTheDocument();
    const seccion = screen.getByRole('heading', { name: 'Cerrar la conversación' }).closest('section')!;
    await u.click(within(seccion).getByRole('button', { name: 'Cerrar conversación' }));
    expect(await screen.findByText('Conversación cerrada.')).toBeInTheDocument();
    expect(cuerpo).toEqual({ tipificacion: null });
  });

  it('una conversación sin IA no muestra el estado ni el panel de acciones', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/bandeja?conversacion=12');
    await abrirSocket(1, 'agente');
    await screen.findByRole('group', { name: 'Acciones de la conversación' });
    expect(screen.queryByRole('region', { name: 'Atención con IA' })).not.toBeInTheDocument();
    expect(llamadas(m, 'GET', '/acciones-ia')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Devolver a la IA' })).not.toBeInTheDocument();
  });
});
