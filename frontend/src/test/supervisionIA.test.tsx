import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { AccionIA, Conversacion, ConversacionIAResumen, Instruccion, Mensaje } from '../api/tipos';
import {
  abrirSocket, campanaEjemplo, emitirEvento, errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal,
  respuesta, simularFetch, type Manejador,
} from './utiles';
import { accion, configGlobal, estadoIA, instruccion, metricas, resumenIA, ruta, rutaJson, uso } from './utilesIA';
import { configuracion, consulta, conversacion, mensaje, pagina } from './utilesWhatsApp';

interface Estado {
  lista: ConversacionIAResumen[]; conv: Conversacion; mensajes: Mensaje[]; acciones: AccionIA[]; instrucciones: Instruccion[];
  global: ReturnType<typeof configGlobal>;
}

function servidor(parcial: Partial<Estado> = {}, extra: Manejador[] = []) {
  const e: Estado = {
    lista: [resumenIA({}, { id: 12 })],
    conv: conversacion({ atendida_por: 'ia', usuario_asignado: null, puede_responder: false, ia: estadoIA() }),
    mensajes: [mensaje()], acciones: [accion()], instrucciones: [], global: configGlobal(), ...parcial,
  };
  const m = simularFetch(
    ...extra,
    rutaJson('GET', '/whatsapp/configuracion', () => configuracion()),
    rutaJson('GET', '/configuracion/ia', () => e.global),
    rutaJson('GET', '/supervision/ia/metricas', () => metricas()),
    rutaJson('GET', '/supervision/ia/conversaciones', () => pagina(e.lista)),
    rutaJson('GET', '/campanas', () => pagina([campanaEjemplo({ id: 1, nombre: 'Cobranza cartera octubre' })])),
    rutaJson('GET', '/conversaciones', () => pagina([])),
    rutaJson('GET', '/conversaciones/12', () => e.conv),
    rutaJson('GET', '/conversaciones/12/mensajes', () => ({ items: e.mensajes, hay_mas: false })),
    rutaJson('GET', '/conversaciones/12/acciones-ia', () => e.acciones),
    rutaJson('GET', '/conversaciones/12/uso-ia', () => uso()),
    rutaJson('GET', '/conversaciones/12/instrucciones', () => e.instrucciones),
  );
  return { m, e };
}

const hubo = (m: ReturnType<typeof simularFetch>, metodo: string, fin: string) =>
  m.mock.calls.filter(([u, i]) => String(u).split('?')[0].endsWith(fin) && ((i as RequestInit | undefined)?.method ?? 'GET') === metodo);

beforeEach(() => {
  instalarWebSocketFalso();
});

describe('Supervisión de la IA (F21)', () => {
  it('la lista se actualiza en vivo: ia.turno marca "respondiendo" y al completar recarga por REST', async () => {
    iniciarSesionComo('supervisor');
    const { e } = servidor();
    renderizarAppTiempoReal('/supervision/ia');
    const ws = await abrirSocket(1, 'supervisor');
    const lista = await screen.findByRole('list', { name: 'Conversaciones con IA' });
    expect(within(lista).getByText('María Pérez')).toBeInTheDocument();
    expect(within(lista).getByText(/4 turnos/)).toBeInTheDocument();
    expect(within(lista).queryByText('IA respondiendo…')).not.toBeInTheDocument();

    emitirEvento(ws, { tipo: 'ia.turno', datos: { conversacion_id: 12, llamada_id: null, campana_id: 1, estado: 'en_curso', iteraciones: 1 } });
    expect(await within(lista).findByText('IA respondiendo…')).toBeInTheDocument();

    e.lista = [resumenIA({ turnos: 5, ultima_accion: { herramienta: 'consultar_obligacion', es_error: true, creado_en: new Date().toISOString() } }, { id: 12 })];
    emitirEvento(ws, { tipo: 'ia.turno', datos: { conversacion_id: 12, llamada_id: null, campana_id: 1, estado: 'completado', iteraciones: 2 } });
    await waitFor(() => expect(within(lista).getByText(/5 turnos/)).toBeInTheDocument(), { timeout: 3000 });
    expect(within(lista).queryByText('IA respondiendo…')).not.toBeInTheDocument();
    expect(within(lista).getByText(/consultar_obligacion \(error\)/)).toBeInTheDocument();
  });

  it('los filtros viajan al servidor (atendida_por=ia por defecto, con_gestion, identidad)', async () => {
    iniciarSesionComo('supervisor');
    const { m } = servidor();
    renderizarAppTiempoReal('/supervision/ia');
    await screen.findByRole('list', { name: 'Conversaciones con IA' });
    const primera = consulta(String(hubo(m, 'GET', '/supervision/ia/conversaciones')[0][0]));
    expect(primera.get('atendida_por')).toBe('ia');
    expect(primera.get('estado')).toBe('abierta');
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Gestión registrada'), 'sin');
    await u.selectOptions(screen.getByLabelText('Identidad'), 'no_verificada');
    await waitFor(() => {
      const ultima = consulta(String(hubo(m, 'GET', '/supervision/ia/conversaciones').at(-1)![0]));
      expect(ultima.get('con_gestion')).toBe('false');
      expect(ultima.get('identidad')).toBe('no_verificada');
    });
  });

  it('detalle: acciones enmascaradas, errores marcados, eventos ia.accion y texto no confiable sin HTML', async () => {
    iniciarSesionComo('supervisor');
    const { e } = servidor({
      mensajes: [mensaje({ cuerpo: '<img src=x onerror=alert(1)><b>hola</b>' })],
      acciones: [accion({ entrada: { numero_documento: '1020304050' }, resultado: { nota: '<script>alert(1)</script>' } })],
    });
    const { container } = renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    const ws = await abrirSocket(1, 'supervisor');
    const panel = (await screen.findByText(/Acciones de la IA \(1\)/)).closest('details')!;
    expect(panel).toHaveAttribute('open');
    // La entrada llega sin enmascarar por error del servidor: el cliente la enmascara de todos modos.
    expect(within(panel).getByText('{"numero_documento":"***4050"}')).toBeInTheDocument();
    expect(within(panel).queryByText(/1020304050/)).not.toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)><b>hola</b>')).toBeInTheDocument();
    expect(within(panel).getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    expect(container.querySelector('img, script, b')).toBeNull();

    e.acciones = [...e.acciones, accion({ id: 78, herramienta: 'simular_acuerdo_pago', es_error: true, codigo_error: 'DESCUENTO_EXCEDE_LIMITE', resultado: { codigo: 'DESCUENTO_EXCEDE_LIMITE' }, efecto: 'ninguno' })];
    emitirEvento(ws, { tipo: 'ia.accion', datos: { conversacion_id: 12, llamada_id: null, campana_id: 1, accion_id: 78, herramienta: 'simular_acuerdo_pago', es_error: true, codigo_error: 'DESCUENTO_EXCEDE_LIMITE' } });
    expect(await within(panel).findByText('simular_acuerdo_pago')).toBeInTheDocument();
    expect(within(panel).getByText(/Error DESCUENTO_EXCEDE_LIMITE/)).toBeInTheDocument();
    expect(within(panel).getByText(/Acciones de la IA \(2\)/, { selector: 'summary' })).toBeInTheDocument();
  });

  it('uso y coste: totales, tasa de caché y llamadas', async () => {
    iniciarSesionComo('administrador');
    servidor();
    renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    const seccion = (await screen.findByRole('heading', { name: 'Uso y coste de la IA' })).closest('section')!;
    expect(await within(seccion).findByText('93 %')).toBeInTheDocument();
    expect(within(seccion).getByRole('table')).toBeInTheDocument();
    expect(within(seccion).getAllByText('claude-opus-5-5').length).toBeGreaterThan(0);
  });

  it('instruir: queda pendiente y pasa a aplicada cuando la IA completa un turno', async () => {
    iniciarSesionComo('supervisor');
    const { e, m } = servidor({}, [
      ruta('POST', '/conversaciones/12/instrucciones', (c) => {
        const i = instruccion({ texto: String(c.texto) });
        e.instrucciones = [i];
        return respuesta(201, i);
      }),
    ]);
    renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    const ws = await abrirSocket(1, 'supervisor');
    const u = userEvent.setup();
    const campo = await screen.findByLabelText('Instrucción para la IA');
    await u.type(campo, 'Ofrézcale 6 cuotas si lo pide.');
    await u.click(screen.getByRole('button', { name: 'Enviar instrucción' }));
    const lista = await screen.findByRole('list', { name: 'Instrucciones enviadas' });
    expect(within(lista).getByText('Ofrézcale 6 cuotas si lo pide.')).toBeInTheDocument();
    expect(within(lista).getByText('Pendiente')).toBeInTheDocument();
    expect(JSON.parse(String(hubo(m, 'POST', '/instrucciones')[0][1]!.body))).toEqual({ texto: 'Ofrézcale 6 cuotas si lo pide.' });

    e.instrucciones = [instruccion({ aplicada_en: new Date().toISOString() })];
    emitirEvento(ws, { tipo: 'ia.turno', datos: { conversacion_id: 12, llamada_id: null, campana_id: 1, estado: 'completado', iteraciones: 1 } });
    expect(await within(lista).findByText(/Aplicada el/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(within(lista).queryByText('Pendiente')).not.toBeInTheDocument();
  });

  it('instruir una conversación que ya no es de la IA muestra el 409 legible', async () => {
    iniciarSesionComo('supervisor');
    servidor({}, [ruta('POST', '/conversaciones/12/instrucciones', () => errorApi(409, 'CONVERSACION_NO_IA', 'x'))]);
    renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    await abrirSocket(1, 'supervisor');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Instrucción para la IA'), 'Hola');
    await u.click(screen.getByRole('button', { name: 'Enviar instrucción' }));
    expect(await screen.findByText('La conversación ya no está atendida por la IA (alguien la tomó o la traspasó).')).toBeInTheDocument();
  });

  it('tomar: la conversación pasa al supervisor y se ofrece abrirla en la bandeja (sin compositor en la supervisión)', async () => {
    iniciarSesionComo('supervisor');
    const { e, m } = servidor({}, [
      ruta('POST', '/conversaciones/12/tomar', () => {
        e.conv = conversacion({ atendida_por: 'humano', usuario_asignado: { id: 1, nombre: 'Usuario supervisor' }, ia: estadoIA({ puede_devolver_ia: true }) });
        return respuesta(200, e.conv);
      }),
    ]);
    renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    await abrirSocket(1, 'supervisor');
    const u = userEvent.setup();
    expect(screen.queryByRole('form', { name: /enviar mensaje/i })).not.toBeInTheDocument();
    await u.click(await screen.findByRole('button', { name: 'Tomar' }));
    expect(await screen.findByText('Conversación tomada.')).toBeInTheDocument();
    const enlace = await screen.findByRole('link', { name: 'Abrir en la bandeja' });
    expect(enlace).toHaveAttribute('href', '/bandeja?conversacion=12');
    expect(hubo(m, 'POST', '/conversaciones/12/tomar')).toHaveLength(1);
  });

  it('traspasar a cola con resumen opcional; si ya no es de la IA muestra el 409', async () => {
    iniciarSesionComo('supervisor');
    let n = 0;
    const { e, m } = servidor({}, [
      ruta('POST', '/conversaciones/12/traspasar', () => {
        if (++n === 1) return errorApi(409, 'CONVERSACION_NO_IA', 'x');
        e.conv = conversacion({ atendida_por: 'sin_asignar', usuario_asignado: null, ia: estadoIA() });
        return respuesta(200, e.conv);
      }),
    ]);
    renderizarAppTiempoReal('/supervision/ia?conversacion=12');
    await abrirSocket(1, 'supervisor');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Traspasar a cola' }));
    const form = screen.getByRole('form', { name: 'Traspasar la conversación a la cola' });
    await u.type(within(form).getByLabelText(/Resumen para el asesor/), 'Cliente pide revisión de intereses.');
    await u.click(within(form).getByRole('button', { name: 'Confirmar traspaso' }));
    expect(await within(form).findByText(/ya no está atendida por la IA/)).toBeInTheDocument();
    await u.click(within(form).getByRole('button', { name: 'Confirmar traspaso' }));
    expect(await screen.findByText('Conversación traspasada a la cola de atención.')).toBeInTheDocument();
    expect(hubo(m, 'POST', '/traspasar').map(([, i]) => JSON.parse(String(i!.body)))).toEqual([
      { resumen: 'Cliente pide revisión de intereses.' }, { resumen: 'Cliente pide revisión de intereses.' },
    ]);
    // La conversación ya no es de la IA: no se puede instruir.
    await waitFor(() => expect(screen.getByLabelText('Instrucción para la IA')).toBeDisabled());
  });
});

describe('Interruptor global de la IA (kill switch global)', () => {
  it('el administrador lo desactiva con confirmación y se envía ia_activa=false', async () => {
    iniciarSesionComo('administrador');
    const { e, m } = servidor({}, [
      ruta('PUT', '/configuracion/ia', (c) => {
        e.global = configGlobal({ ia_activa: Boolean(c.ia_activa) });
        return respuesta(200, e.global);
      }),
    ]);
    renderizarAppTiempoReal('/supervision/ia');
    await abrirSocket(1, 'administrador');
    const u = userEvent.setup();
    expect(await screen.findByText('IA global activa')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Desactivar la IA en toda la plataforma' }));
    const conf = screen.getByRole('group', { name: '¿Desactivar la IA en toda la plataforma?' });
    await u.click(within(conf).getByRole('button', { name: 'Cancelar' }));
    expect(hubo(m, 'PUT', '/configuracion/ia')).toHaveLength(0);
    await u.click(screen.getByRole('button', { name: 'Desactivar la IA en toda la plataforma' }));
    await u.click(screen.getByRole('button', { name: 'Confirmar desactivación global' }));
    expect(await screen.findByText('IA global desactivada')).toBeInTheDocument();
    expect(JSON.parse(String(hubo(m, 'PUT', '/configuracion/ia')[0][1]!.body))).toEqual({ ia_activa: false });
  });

  it('el supervisor solo ve el estado (sin botón)', async () => {
    iniciarSesionComo('supervisor');
    servidor();
    renderizarAppTiempoReal('/supervision/ia');
    await abrirSocket(1, 'supervisor');
    expect(await screen.findByText('IA global activa')).toBeInTheDocument();
    expect(screen.getByText('Solo un administrador puede cambiar el interruptor global.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /toda la plataforma/ })).not.toBeInTheDocument();
  });

  it('un ia.configuracion global recarga el estado (desactivada por el entorno o por otro administrador)', async () => {
    iniciarSesionComo('supervisor');
    const { e } = servidor();
    renderizarAppTiempoReal('/supervision/ia');
    const ws = await abrirSocket(1, 'supervisor');
    expect(await screen.findByText('IA global activa')).toBeInTheDocument();
    e.global = configGlobal({ ia_activa: false });
    emitirEvento(ws, { tipo: 'ia.configuracion', datos: { campana_id: null, activa: false, version: null, desactivada_motivo: 'manual' } });
    expect(await screen.findByText('IA global desactivada')).toBeInTheDocument();
  });
});

describe('Métricas y avisos', () => {
  it('muestra métricas y recarga al elegir campaña', async () => {
    iniciarSesionComo('supervisor');
    const { m } = servidor();
    renderizarAppTiempoReal('/supervision/ia');
    await abrirSocket(1, 'supervisor');
    expect(await screen.findByText('120')).toBeInTheDocument();
    expect(screen.getByText('84 (70 %)')).toBeInTheDocument();
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Campaña de las métricas'), '1');
    await waitFor(() => {
      expect(consulta(String(hubo(m, 'GET', '/supervision/ia/metricas').at(-1)![0])).get('campana_id')).toBe('1');
    });
  });

  it('ia.alerta: crítico como alert, aviso como status, descartable; el agente no los ve', async () => {
    iniciarSesionComo('supervisor');
    servidor();
    const { unmount } = renderizarAppTiempoReal('/supervision/ia');
    const ws = await abrirSocket(1, 'supervisor');
    emitirEvento(ws, { tipo: 'ia.alerta', datos: { tipo: 'kill_switch', nivel: 'critico', campana_id: 1, conversacion_id: null } });
    emitirEvento(ws, { tipo: 'ia.alerta', datos: { tipo: 'presupuesto_campana', nivel: 'aviso', campana_id: 1, conversacion_id: null } });
    const region = await screen.findByRole('region', { name: 'Avisos de la IA' });
    expect(within(region).getByRole('alert')).toHaveTextContent('Kill switch: la IA se desactivó en la campaña #1');
    expect(within(region).getByRole('status')).toHaveTextContent('alcanzó el umbral de aviso');
    await userEvent.setup().click(within(region).getByRole('button', { name: /Descartar aviso: Kill switch/ }));
    expect(within(region).queryByRole('alert')).not.toBeInTheDocument();
    act(() => unmount());

    sessionStorage.clear();
    iniciarSesionComo('agente');
    servidor();
    renderizarAppTiempoReal('/bandeja');
    const ws2 = await abrirSocket(1, 'agente');
    emitirEvento(ws2, { tipo: 'ia.alerta', datos: { tipo: 'kill_switch', nivel: 'critico', campana_id: 1, conversacion_id: null } });
    await screen.findByRole('heading', { name: 'Bandeja de WhatsApp' });
    expect(screen.queryByRole('region', { name: 'Avisos de la IA' })).not.toBeInTheDocument();
  });

  it('el agente no accede a /supervision/ia', async () => {
    iniciarSesionComo('agente');
    const { m } = servidor();
    renderizarAppTiempoReal('/supervision/ia');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
    expect(hubo(m, 'GET', '/supervision/ia/conversaciones')).toHaveLength(0);
  });
});
