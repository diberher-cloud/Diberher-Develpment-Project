import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { FichaCliente } from '../api/tipos';
import { aCuerpoTipificacionConversacion, resultadosPermitidos, TIPIFICACION_VACIA, validarTipificacion } from '../utilidades/tipificacion';
import { previaPlantilla, fusionarMensajes, nuevoUuid, textoEstadoMensaje, huboEntrantes } from '../utilidades/whatsapp';
import { ErrorApi, solicitarBlob } from '../api/cliente';
import { FormularioTipificacion } from '../componentes/consola/FormularioTipificacion';
import {
  errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarAppTiempoReal, respuesta, simularFetch, type Manejador,
} from './utiles';
import { fichaConWhatsApp, mensaje, plantilla } from './utilesWhatsApp';

const DESDE = '2026-10-23T15:00:00Z';

function servidorConsola(ficha: FichaCliente, extra: Manejador[] = []) {
  return simularFetch(
    ...extra,
    (url, i) => (url === '/api/v1/consola/estado' && i.method === 'GET'
      ? respuesta(200, { estado: 'disponible', desde: DESDE, motivo_pausa: null, llamada_id: null, tipificacion_pendiente: null }) : undefined),
    (url) => (url === '/api/v1/consola/campanas' ? respuesta(200, [{ id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza', pendientes: 1 }]) : undefined),
    (url) => (url.startsWith('/api/v1/consola/registros?')
      ? respuesta(200, { items: [{
        id: 15, campana_id: 1, campana_nombre: 'Cobranza cartera octubre', tipo_campana: 'cobranza', nombre_cliente: 'María Pérez', estado: 'pendiente',
        intentos: 0, max_intentos: 3, ultimo_resultado: null, ultima_gestion_en: null, proximo_intento_en: null, saldo_mora: null, dias_mora: null,
        producto: null, reservado_por_mi: false,
      }], total: 1, page: 1, page_size: 10 }) : undefined),
    (url, i) => (url === '/api/v1/consola/registros/15/tomar' && i.method === 'POST' ? respuesta(200, ficha) : undefined),
    (url) => (url === '/api/v1/telefonia/token' ? respuesta(200, { proveedor: 'falso', token: 'falso.agente_1.x', identity: 'agente_1', expira_en: '2026-10-23T16:00:00Z' }) : undefined),
    (url) => (url.startsWith('/api/v1/whatsapp/plantillas') ? respuesta(200, [plantilla()]) : undefined),
  );
}

async function tomar(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole('button', { name: 'Tomar registro de María Pérez' }));
  await screen.findByRole('heading', { name: /Ficha del cliente: María Pérez/ });
}

beforeEach(() => {
  iniciarSesionComo('agente');
  instalarWebSocketFalso();
});

describe('Consola: WhatsApp desde la ficha', () => {
  it('muestra la insignia por teléfono y envía una plantilla; luego enlaza a la conversación en la bandeja', async () => {
    let cuerpo: Record<string, unknown> = {};
    const m = servidorConsola(fichaConWhatsApp(), [
      (url, i) => {
        if (url !== '/api/v1/consola/registros/15/whatsapp/plantilla' || i.method !== 'POST') return undefined;
        cuerpo = JSON.parse(String(i.body));
        return respuesta(200, { permitido: true, motivos: [], proxima_ventana_inicio: null, politica_version: 1, conversacion_id: 12, mensaje: mensaje({ id: 300, direccion: 'saliente', autor: 'agente' }) });
      },
    ]);
    renderizarAppTiempoReal('/consola');
    const u = userEvent.setup();
    await tomar(u);
    expect(screen.getByText('Autorizado')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Enviar plantilla a \+57300\*\*\*\*567/ }));
    await u.selectOptions(await screen.findByLabelText('Plantilla'), 'recordatorio_cobranza');
    await u.click(screen.getByRole('button', { name: 'Enviar plantilla' }));
    const enlace = await screen.findByRole('link', { name: /Ver la conversación en la bandeja/ });
    expect(enlace).toHaveAttribute('href', '/bandeja?conversacion=12');
    expect(cuerpo).toMatchObject({ telefono_id: 21, plantilla_id: 3 });
    expect(String(cuerpo.idempotencia_clave)).toMatch(/^[0-9a-f-]{36}$/);
    expect(m.mock.calls.some(([u2]) => String(u2).includes('campana_id=1') && String(u2).includes('enviables=true'))).toBe(true);
  });

  it('resultado bloqueado por cumplimiento: muestra los motivos y no enlaza a una conversación', async () => {
    servidorConsola(fichaConWhatsApp(), [
      (url, i) => (url === '/api/v1/consola/registros/15/whatsapp/plantilla' && i.method === 'POST'
        ? respuesta(200, { permitido: false, motivos: [{ codigo: 'SIN_AUTORIZACION', mensaje: 'Sin autorización vigente.' }], proxima_ventana_inicio: null, politica_version: 1, conversacion_id: null, mensaje: null })
        : undefined),
    ]);
    renderizarAppTiempoReal('/consola');
    const u = userEvent.setup();
    await tomar(u);
    await u.click(screen.getByRole('button', { name: /Enviar plantilla a/ }));
    await u.selectOptions(await screen.findByLabelText('Plantilla'), 'recordatorio_cobranza');
    await u.click(screen.getByRole('button', { name: 'Enviar plantilla' }));
    expect(await screen.findByText(/SIN_AUTORIZACION/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Ver la conversación/ })).not.toBeInTheDocument();
  });

  it('botón deshabilitado con los motivos cuando el teléfono no es enviable; enlace si ya hay conversación abierta', async () => {
    const f = fichaConWhatsApp();
    f.telefonos[0].whatsapp = {
      autorizado: false, excluido: true, enviable: false,
      motivos: [{ codigo: 'EXCLUIDO', mensaje: 'Número excluido de WhatsApp.' }, { codigo: 'FUERA_DE_FRANJA', mensaje: 'Fuera de franja.' }],
      conversacion_abierta: { id: 12, atendida_por: 'humano', ventana_abierta: true },
    };
    servidorConsola(f);
    renderizarAppTiempoReal('/consola');
    await tomar(userEvent.setup());
    const boton = screen.getByRole('button', { name: /Enviar plantilla a/ });
    expect(boton).toBeDisabled();
    expect(boton).toHaveAccessibleDescription(/Número excluido de WhatsApp\..*Fuera de franja\./);
    expect(screen.getByText('Sin autorización')).toBeInTheDocument();
    expect(screen.getByText(/Excluido de WhatsApp/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Ir a la conversación/ })).toHaveAttribute('href', '/bandeja?conversacion=12');
  });

  it('un teléfono sin bloque whatsapp (campaña sin WhatsApp o fijo) no muestra controles', async () => {
    const f = fichaConWhatsApp();
    f.telefonos[0].whatsapp = null;
    servidorConsola(f);
    renderizarAppTiempoReal('/consola');
    await tomar(userEvent.setup());
    expect(screen.queryByRole('button', { name: /Enviar plantilla/ })).not.toBeInTheDocument();
  });

  it('un 409 del servidor al enviar se muestra como error', async () => {
    servidorConsola(fichaConWhatsApp(), [
      (url, i) => (url === '/api/v1/consola/registros/15/whatsapp/plantilla' && i.method === 'POST'
        ? errorApi(409, 'VENTANA_ABIERTA', 'Hay una conversación con la ventana abierta: responda en la bandeja.') : undefined),
    ]);
    renderizarAppTiempoReal('/consola');
    const u = userEvent.setup();
    await tomar(u);
    await u.click(screen.getByRole('button', { name: /Enviar plantilla a/ }));
    await u.selectOptions(await screen.findByLabelText('Plantilla'), 'recordatorio_cobranza');
    await u.click(screen.getByRole('button', { name: 'Enviar plantilla' }));
    expect(await screen.findByText(/responda en la bandeja/)).toBeInTheDocument();
  });
});

describe('FormularioTipificacion en modo conversación', () => {
  it('sin entrantes solo ofrece "No contesta" y envía el cuerpo sin llamada_id', async () => {
    const enviados: unknown[] = [];
    render(
      <FormularioTipificacion contexto="conversacion" tipoCampana="cobranza" saldoTotal="100000" huboEntrantes={false}
        onEnviar={async (c) => { enviados.push(c); }} />,
    );
    expect(screen.getByRole('heading', { name: 'Cerrar y tipificar la conversación' })).toBeInTheDocument();
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Seleccione…', 'No contesta']);
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Resultado'), 'no_contesta');
    await u.click(screen.getByRole('button', { name: 'Cerrar conversación' }));
    await waitFor(() => expect(enviados).toEqual([{ resultado: 'no_contesta', observacion: null }]));
  });

  it('con entrantes excluye "No contesta"; un error lanzado por onEnviar se muestra', async () => {
    render(
      <FormularioTipificacion contexto="conversacion" tipoCampana="venta" saldoTotal={null} huboEntrantes
        onEnviar={async () => { throw new ErrorApi(422, 'RESULTADO_INCOHERENTE', 'Resultado incoherente con la conversación.'); }} />,
    );
    const opciones = screen.getAllByRole('option').map((o) => o.textContent);
    expect(opciones).not.toContain('No contesta');
    expect(opciones).toContain('Venta');
    expect(opciones).not.toContain('Promesa de pago');
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText('Resultado'), 'rechazo');
    await u.click(screen.getByRole('button', { name: 'Cerrar conversación' }));
    expect(await screen.findByText('Resultado incoherente con la conversación.')).toBeInTheDocument();
  });
});

describe('Utilidades de WhatsApp', () => {
  it('resultadosPermitidos y validación respetan la coherencia de la conversación', () => {
    expect(resultadosPermitidos({ tipoCampana: 'cobranza', huboEntrantes: false })).toEqual(['no_contesta']);
    expect(resultadosPermitidos({ tipoCampana: 'cobranza', huboEntrantes: true })).not.toContain('no_contesta');
    expect(resultadosPermitidos({ tipoCampana: 'cobranza' })).toContain('no_contesta'); // llamada: sin cambios
    expect(validarTipificacion({ ...TIPIFICACION_VACIA, resultado: 'rechazo' }, { tipoCampana: 'venta', saldoTotal: null, huboEntrantes: false }).resultado).toBeDefined();
    expect(aCuerpoTipificacionConversacion({ ...TIPIFICACION_VACIA, resultado: 'rechazo', observacion: ' no ' })).toEqual({ resultado: 'rechazo', observacion: 'no' });
  });

  it('nuevoUuid genera UUID v4 distintos, también sin crypto.randomUUID', () => {
    const a = nuevoUuid();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(nuevoUuid()).not.toBe(a);
    const original = globalThis.crypto.randomUUID;
    Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      expect(nuevoUuid()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    } finally {
      Object.defineProperty(globalThis.crypto, 'randomUUID', { value: original, configurable: true });
    }
  });

  it('previaPlantilla, fusionarMensajes, textoEstadoMensaje y huboEntrantes', () => {
    expect(previaPlantilla({ cuerpo: 'Hola {{1}} {{ 2 }} {{3}}', mapeo_variables: { '1': 'primer_nombre', '2': 'producto' } }))
      .toBe('Hola [Primer nombre del cliente] [Producto del registro] {{3}}');
    const r = fusionarMensajes([mensaje({ id: 2, estado: 'enviado' }), mensaje({ id: 1 })], [mensaje({ id: 2, estado: 'entregado' }), mensaje({ id: 3 })]);
    expect(r.map((x) => [x.id, x.estado])).toEqual([[1, 'recibido'], [2, 'entregado'], [3, 'recibido']]);
    expect(textoEstadoMensaje(mensaje({ estado: 'fallido', error: { codigo: '63016', mensaje: 'Fuera de la ventana de 24 h.' } }))).toBe('Fallido: Fuera de la ventana de 24 h.');
    expect(huboEntrantes({ iniciada_por: 'empresa', ventana_expira_en: null })).toBe(false);
    expect(huboEntrantes({ iniciada_por: 'empresa', ventana_expira_en: '2026-10-25T00:00:00Z' })).toBe(true);
  });

  it('solicitarBlob envía el Bearer y traduce los errores del servidor', async () => {
    const m = simularFetch(
      (url) => (url === '/api/v1/ok' ? new Response(new Blob(['x']), { status: 200 }) : undefined),
      (url) => (url === '/api/v1/falla' ? errorApi(404, 'MEDIA_NO_DISPONIBLE', 'El adjunto ya no está disponible.') : undefined),
    );
    expect((await solicitarBlob('/ok')).size).toBeGreaterThan(0);
    expect((m.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: 'Bearer token-de-prueba' });
    await expect(solicitarBlob('/falla')).rejects.toMatchObject({ status: 404, codigo: 'MEDIA_NO_DISPONIBLE' });
  });
});

