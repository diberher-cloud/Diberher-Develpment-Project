import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { EstadoAgente, FichaCliente, Llamada, RegistroTrabajo } from '../api/tipos';
import { hoyBogota, sumarDias } from '../utilidades/formato';
import {
  abrirSocket, emitirEvento, errorApi, iniciarSesionComo, instalarWebSocketFalso, renderizarApp,
  renderizarAppTiempoReal, respuesta, simularFetch,
} from './utiles';

const DESDE = '2026-10-23T15:00:00Z';
const disponible: EstadoAgente = { estado: 'disponible', desde: DESDE, motivo_pausa: null, llamada_id: null, tipificacion_pendiente: null };

const registro = (o: Partial<RegistroTrabajo> = {}): RegistroTrabajo => ({
  id: 15, campana_id: 1, campana_nombre: 'Cobranza cartera octubre', tipo_campana: 'cobranza', nombre_cliente: 'María Pérez',
  estado: 'pendiente', intentos: 1, max_intentos: 3, ultimo_resultado: 'no_contesta', ultima_gestion_en: '2026-10-22T20:00:00Z',
  proximo_intento_en: null, saldo_mora: '250000.50', dias_mora: 45, producto: null, reservado_por_mi: false, ...o,
});

const ficha = (o: Partial<FichaCliente> = {}): FichaCliente => ({
  id: 15, campana: { id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza' }, estado: 'en_gestion',
  reservado_hasta: '2026-10-23T15:25:00Z', intentos: 1, max_intentos: 3, ultimo_resultado: 'no_contesta', proximo_intento_en: null,
  cliente: { id: 9, tipo_documento: 'CC', numero_documento: '1020304050', nombre: 'María Pérez', email: null, ciudad: 'Bogotá' },
  telefonos: [
    { id: 21, numero_mascara: '+57300****567', tipo_linea: 'movil', prioridad: 1, excluido: false, llamable: true, motivos: [], whatsapp: null },
    { id: 22, numero_mascara: '+57601****678', tipo_linea: 'fijo', prioridad: 2, excluido: true, llamable: false,
      motivos: [{ codigo: 'EXCLUIDO', mensaje: 'Número excluido (numero_errado).' }], whatsapp: null },
  ],
  numero_obligacion: 'OB-001', saldo_total: '1500000.00', saldo_mora: '250000.50', dias_mora: 45, fecha_vencimiento: '2026-09-15',
  producto: null, oferta: null, datos_adicionales: { segmento: 'A' },
  guion: 'Buenos días, María Pérez. Le habla Pedro Agente de Mi Empresa S.A.S.',
  cumplimiento: { permitido: true, motivos: [], momento_local: '2026-10-23T10:15:00-05:00', proxima_ventana_inicio: null, politica_version: 1 },
  historial: [
    { id: 40, canal: 'voz', origen: 'agente', agente_nombre: 'Pedro Agente', resultado: 'no_contesta', contacto_directo: false,
      observacion: null, creado_en: '2026-10-22T20:00:00Z', promesa: null, venta: null, volver_a_llamar_en: null },
  ],
  ...o,
});

const llamada = (o: Partial<Llamada> = {}): Llamada => ({
  id: 31, campana_cliente_id: 15, telefono_id: 21, canal: 'voz', direccion: 'saliente', estado: 'completada', motivos_bloqueo: [],
  iniciada_en: DESDE, contestada_en: DESDE, finalizada_en: DESDE, duracion_segundos: 42, tipificada: false, ...o,
});

interface Config {
  estado?: EstadoAgente;
  ficha?: FichaCliente;
  llamada?: Llamada;
  simulacion?: { llamada_id: number | null; permitida: boolean; motivos: { codigo: string; mensaje: string }[] };
  tomar?: () => Response;
  tipificar?: (cuerpo: Record<string, unknown>) => Response;
}

/** Servidor simulado con estado: reproduce las transiciones del agente descritas en fase-2.md §4.3-4.6. */
function servidor(c: Config = {}) {
  let estado: EstadoAgente = c.estado ?? disponible;
  let gestionado = false;
  const f = c.ficha ?? ficha();
  const m = simularFetch(
    (url, i) => (url === '/api/v1/consola/estado' && i.method === 'GET' ? respuesta(200, estado) : undefined),
    (url, i) => {
      if (url === '/api/v1/consola/estado' && i.method === 'PUT') {
        const cuerpo = JSON.parse(String(i.body));
        estado = { ...estado, estado: cuerpo.estado, motivo_pausa: cuerpo.motivo_pausa ?? null };
        return respuesta(200, estado);
      }
    },
    (url) => (url === '/api/v1/consola/campanas' ? respuesta(200, [{ id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza', pendientes: 120 }]) : undefined),
    (url) => (url.startsWith('/api/v1/consola/registros?')
      ? respuesta(200, { items: gestionado ? [] : [registro()], total: gestionado ? 0 : 1, page: 1, page_size: 10 }) : undefined),
    (url, i) => (url === '/api/v1/consola/registros/15/tomar' && i.method === 'POST' ? (c.tomar ? c.tomar() : respuesta(200, f)) : undefined),
    (url, i) => (url === '/api/v1/consola/registros/15/soltar' && i.method === 'POST' ? respuesta(204) : undefined),
    (url, i) => (url === '/api/v1/consola/registros/15' && i.method === 'GET' ? respuesta(200, f) : undefined),
    (url, i) => (url === '/api/v1/telefonia/token' && i.method === 'POST'
      ? respuesta(200, { proveedor: 'falso', token: 'falso.agente_1.x', identity: 'agente_1', expira_en: '2026-10-23T16:00:00Z' }) : undefined),
    (url, i) => {
      if (url !== '/api/v1/telefonia/simulacion/llamadas' || i.method !== 'POST') return undefined;
      const r = c.simulacion ?? { llamada_id: 31, permitida: true, motivos: [] };
      if (r.permitida) estado = { ...estado, estado: 'en_llamada', llamada_id: r.llamada_id };
      return respuesta(200, r);
    },
    (url, i) => {
      if (!/\/telefonia\/simulacion\/llamadas\/31\/eventos$/.test(url)) return undefined;
      const e = JSON.parse(String(i.body));
      if (e.evento === 'finalizada') {
        estado = { ...estado, estado: 'tipificando', tipificacion_pendiente: { llamada_id: 31, campana_cliente_id: 15 } };
      }
      return respuesta(204);
    },
    (url) => (url === '/api/v1/consola/llamadas/31' ? respuesta(200, c.llamada ?? llamada()) : undefined),
    (url, i) => {
      if (url !== '/api/v1/consola/tipificaciones' || i.method !== 'POST') return undefined;
      const cuerpo = JSON.parse(String(i.body));
      if (c.tipificar) return c.tipificar(cuerpo);
      gestionado = true;
      estado = { ...estado, estado: 'disponible', llamada_id: null, tipificacion_pendiente: null };
      return respuesta(201, {
        id: 41, campana_cliente_id: 15, llamada_id: 31, canal: 'voz', origen: 'agente', usuario_id: 1, resultado: cuerpo.resultado,
        contacto_directo: true, observacion: cuerpo.observacion, promesa: null, venta: null, volver_a_llamar_en: null,
        creado_en: DESDE, registro: { estado: 'gestionado', intentos: 2, proximo_intento_en: null },
      });
    },
  );
  const cuerpoDe = (ruta: string, metodo = 'POST') => {
    const llamadaFetch = m.mock.calls.find(([u, i]) => String(u) === ruta && i?.method === metodo);
    const cuerpo = llamadaFetch?.[1]?.body;
    return cuerpo ? JSON.parse(String(cuerpo)) : undefined;
  };
  return { m, cuerpoDe, estado: () => estado };
}

async function tomarRegistro(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole('button', { name: 'Tomar registro de María Pérez' }));
  await screen.findByRole('heading', { name: /Ficha del cliente: María Pérez/ });
}

async function llamarYColgar(u: ReturnType<typeof userEvent.setup>) {
  const llamar = await screen.findByRole('button', { name: /^Llamar/ });
  await waitFor(() => expect(llamar).toBeEnabled());
  await u.click(llamar);
  await u.click(await screen.findByRole('button', { name: 'Contesta' }));
  await u.click(await screen.findByRole('button', { name: 'Colgar' }));
  await screen.findByRole('heading', { name: 'Tipificar la llamada' });
}

beforeEach(() => {
  iniciarSesionComo('agente');
  instalarWebSocketFalso();
});

describe('Consola del agente: flujo completo con SoftphoneFalso', () => {
  it('tomar, llamar, contestar, colgar, tipificar promesa: registro gestionado y agente disponible', async () => {
    const s = servidor();
    renderizarAppTiempoReal('/consola');
    const u = userEvent.setup();

    expect(await screen.findByText('Disponible', { selector: 'strong' })).toBeInTheDocument();
    await tomarRegistro(u);
    expect(s.cuerpoDe('/api/v1/consola/registros/15/tomar')).toBeUndefined(); // POST sin cuerpo
    expect(screen.getByText(/Le habla Pedro Agente/)).toBeInTheDocument(); // guion renderizado por el servidor
    expect(screen.getByText('Historial de gestiones')).toBeInTheDocument();

    await llamarYColgar(u);
    expect(s.cuerpoDe('/api/v1/telefonia/simulacion/llamadas')).toEqual({ campana_cliente_id: 15, telefono_id: 21 });
    expect(s.cuerpoDe('/api/v1/telefonia/simulacion/llamadas/31/eventos')).toEqual({ evento: 'contestada' });
    // Mientras hay una llamada por tipificar no se puede soltar el registro ni cambiar de estado.
    expect(screen.getByRole('button', { name: /Soltar registro/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cambiar estado' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Tomar registro de María Pérez' })).not.toBeInTheDocument();

    const hoy = hoyBogota();
    const form = screen.getByRole('form', { name: 'Formulario de tipificación' });
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'promesa_pago');
    await u.type(within(form).getByLabelText('Monto prometido (COP)'), '250000.50');
    fireEvent.change(within(form).getByLabelText('Fecha de pago'), { target: { value: sumarDias(hoy, 3) } });
    await u.type(within(form).getByLabelText('Observación (opcional)'), 'Paga el viernes');
    await u.click(within(form).getByRole('button', { name: 'Registrar tipificación' }));

    await screen.findByText(/Tipificación registrada: Promesa de pago/);
    expect(s.cuerpoDe('/api/v1/consola/tipificaciones')).toEqual({
      llamada_id: 31, resultado: 'promesa_pago', observacion: 'Paga el viernes',
      promesa: { monto: '250000.50', fecha_pago: sumarDias(hoy, 3) },
    });
    expect(screen.getByText(/quedó en estado "gestionado"/)).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Lista de trabajo' })).toBeInTheDocument();
    expect(await screen.findByText('No hay registros disponibles en este momento.')).toBeInTheDocument();
    expect(screen.getByText('Disponible', { selector: 'strong' })).toBeInTheDocument();
    expect(s.estado().estado).toBe('disponible');
  });

  it('nunca muestra un teléfono E.164 completo', async () => {
    servidor();
    renderizarApp('/consola');
    const u = userEvent.setup();
    await tomarRegistro(u);
    expect(screen.getAllByText(/\+57300\*\*\*\*567/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/\+57\d{7,}/);
    await llamarYColgar(u);
    expect(document.body.textContent).not.toMatch(/\+57\d{7,}/);
  });

  it('el botón Llamar se deshabilita con un teléfono no llamable y explica el motivo', async () => {
    servidor();
    renderizarApp('/consola');
    const u = userEvent.setup();
    await tomarRegistro(u);
    await waitFor(() => expect(screen.getByRole('button', { name: /^Llamar/ })).toBeEnabled());
    await u.selectOptions(screen.getByLabelText('Teléfono a llamar'), '22');
    const boton = screen.getByRole('button', { name: /^Llamar/ });
    expect(boton).toBeDisabled();
    expect(screen.getAllByText('Número excluido (numero_errado).').length).toBeGreaterThan(0);
  });

  it('con el agente en pausa no se puede llamar', async () => {
    servidor({ estado: { ...disponible, estado: 'pausa', motivo_pausa: 'almuerzo' } });
    renderizarApp('/consola');
    const u = userEvent.setup();
    await tomarRegistro(u);
    expect(await screen.findByText('Debe estar en estado Disponible para llamar.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Llamar/ })).toBeDisabled();
  });

  it('muestra el bloqueo FUERA_DE_FRANJA y no pide tipificación', async () => {
    const s = servidor({
      simulacion: { llamada_id: 32, permitida: false, motivos: [{ codigo: 'FUERA_DE_FRANJA', mensaje: 'Fuera de la franja horaria permitida.' }] },
    });
    renderizarApp('/consola');
    const u = userEvent.setup();
    await tomarRegistro(u);
    const llamar = screen.getByRole('button', { name: /^Llamar/ });
    await waitFor(() => expect(llamar).toBeEnabled());
    await u.click(llamar);
    const alerta = await screen.findByRole('alert');
    expect(alerta).toHaveTextContent('FUERA_DE_FRANJA');
    expect(alerta).toHaveTextContent('Fuera de la franja horaria permitida.');
    expect(screen.queryByRole('heading', { name: 'Tipificar la llamada' })).not.toBeInTheDocument();
    expect(s.estado().estado).toBe('disponible');
  });

  it('muestra el bloqueo recibido por llamada.estado (flujo Twilio)', async () => {
    servidor({ simulacion: { llamada_id: 40, permitida: false, motivos: [] } });
    renderizarAppTiempoReal('/consola');
    const ws = await abrirSocket(1);
    const u = userEvent.setup();
    await tomarRegistro(u);
    const llamar = screen.getByRole('button', { name: /^Llamar/ });
    await waitFor(() => expect(llamar).toBeEnabled());
    await u.click(llamar);
    await screen.findByText('Llamada finalizada.');
    expect(screen.queryByText(/FRECUENCIA_DIA/)).not.toBeInTheDocument();
    emitirEvento(ws, {
      tipo: 'llamada.estado',
      datos: { llamada_id: 40, usuario_id: 1, campana_id: 1, campana_cliente_id: 15, estado: 'bloqueada',
               motivos: [{ codigo: 'FRECUENCIA_DIA', mensaje: 'Ya hubo 1 contacto(s) con el cliente hoy (máximo 1).' }] },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('FRECUENCIA_DIA');
    // Eventos de otro agente se ignoran.
    emitirEvento(ws, {
      tipo: 'llamada.estado',
      datos: { llamada_id: 41, usuario_id: 99, campana_id: 1, campana_cliente_id: 16, estado: 'bloqueada', motivos: [{ codigo: 'EXCLUIDO', mensaje: 'x' }] },
    });
    expect(screen.queryByText('EXCLUIDO')).not.toBeInTheDocument();
  });

  it('409 REGISTRO_RESERVADO se muestra y la lista sigue visible', async () => {
    servidor({ tomar: () => errorApi(409, 'REGISTRO_RESERVADO', 'El registro está reservado por otro agente.') });
    renderizarApp('/consola');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Tomar registro de María Pérez' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El registro está reservado por otro agente.');
    expect(screen.getByRole('heading', { name: 'Lista de trabajo' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Ficha del cliente/ })).not.toBeInTheDocument();
  });

  it('409 TIPIFICACION_PENDIENTE al tomar se muestra con el mensaje del servidor', async () => {
    servidor({ tomar: () => errorApi(409, 'TIPIFICACION_PENDIENTE', 'Tiene una llamada sin tipificar.') });
    renderizarApp('/consola');
    const u = userEvent.setup();
    await u.click(await screen.findByRole('button', { name: 'Tomar registro de María Pérez' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Tiene una llamada sin tipificar.');
  });

  it('con una tipificación pendiente al cargar, recupera la ficha, muestra el formulario y no deja tomar otro registro', async () => {
    servidor({
      estado: { estado: 'tipificando', desde: DESDE, motivo_pausa: null, llamada_id: 31, tipificacion_pendiente: { llamada_id: 31, campana_cliente_id: 15 } },
    });
    renderizarApp('/consola');
    expect(await screen.findByRole('heading', { name: 'Tipificar la llamada' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Lista de trabajo' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Ficha del cliente: María Pérez/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cambiar estado' })).toBeDisabled();
    expect(screen.getByText('Tipifique la llamada para volver a quedar disponible.')).toBeInTheDocument();
  });

  it('soltar el registro lo libera y vuelve a la lista', async () => {
    const s = servidor();
    renderizarApp('/consola');
    const u = userEvent.setup();
    await tomarRegistro(u);
    await u.click(screen.getByRole('button', { name: /Soltar registro/ }));
    expect(await screen.findByRole('heading', { name: 'Lista de trabajo' })).toBeInTheDocument();
    expect(s.m.mock.calls.some(([url, i]) => String(url) === '/api/v1/consola/registros/15/soltar' && i?.method === 'POST')).toBe(true);
  });

  it('la lista se refresca al recibir consola.registro', async () => {
    const s = servidor();
    renderizarAppTiempoReal('/consola');
    const ws = await abrirSocket(1);
    await screen.findByRole('button', { name: 'Tomar registro de María Pérez' });
    const contar = () => s.m.mock.calls.filter(([u]) => String(u).startsWith('/api/v1/consola/registros?')).length;
    const antes = contar();
    emitirEvento(ws, { tipo: 'consola.registro', datos: { campana_id: 1, campana_cliente_id: 15, accion: 'liberado' } });
    await waitFor(() => expect(contar()).toBeGreaterThan(antes));
  });

  it('cambiar a pausa exige motivo y lo envía', async () => {
    const s = servidor();
    renderizarApp('/consola');
    const u = userEvent.setup();
    await screen.findByText('Disponible', { selector: 'strong' });
    await u.selectOptions(screen.getByLabelText('Cambiar estado a'), 'pausa');
    await u.click(screen.getByRole('button', { name: 'Cambiar estado' }));
    expect(await screen.findByText('Seleccione el motivo de la pausa.')).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText('Motivo de la pausa'), 'almuerzo');
    await u.click(screen.getByRole('button', { name: 'Cambiar estado' }));
    await screen.findByText('En pausa', { selector: 'strong' });
    expect(s.cuerpoDe('/api/v1/consola/estado', 'PUT')).toEqual({ estado: 'pausa', motivo_pausa: 'almuerzo' });
  });

  it('muestra el error del servidor al cambiar de estado', async () => {
    servidor();
    renderizarApp('/consola');
    const u = userEvent.setup();
    await screen.findByText('Disponible', { selector: 'strong' });
    simularFetch(
      (url, i) => (url === '/api/v1/consola/estado' && i.method === 'PUT' ? errorApi(409, 'AGENTE_EN_LLAMADA', 'No puede cambiar de estado en llamada.') : undefined),
      (url) => (url === '/api/v1/consola/estado' ? respuesta(200, disponible) : undefined),
      (url) => (url.startsWith('/api/v1/consola/') ? respuesta(200, { items: [], total: 0, page: 1, page_size: 10 }) : undefined),
    );
    await u.selectOptions(screen.getByLabelText('Cambiar estado a'), 'desconectado');
    await u.click(screen.getByRole('button', { name: 'Cambiar estado' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No puede cambiar de estado en llamada.');
  });
});

describe('Formulario de tipificación', () => {
  const pendiente: EstadoAgente = {
    estado: 'tipificando', desde: DESDE, motivo_pausa: null, llamada_id: 31,
    tipificacion_pendiente: { llamada_id: 31, campana_cliente_id: 15 },
  };

  async function abrirFormulario(c: Config = {}) {
    const s = servidor({ estado: pendiente, ...c });
    renderizarApp('/consola');
    const form = await screen.findByRole('form', { name: 'Formulario de tipificación' });
    return { s, form, u: userEvent.setup() };
  }

  it('muestra solo los campos del resultado elegido', async () => {
    const { form, u } = await abrirFormulario();
    const r = within(form).getByLabelText('Resultado');
    expect(within(form).queryByLabelText('Monto prometido (COP)')).not.toBeInTheDocument();
    await u.selectOptions(r, 'promesa_pago');
    expect(within(form).getByLabelText('Monto prometido (COP)')).toBeInTheDocument();
    expect(within(form).getByLabelText('Fecha de pago')).toBeInTheDocument();
    await u.selectOptions(r, 'volver_a_llamar');
    expect(within(form).queryByLabelText('Monto prometido (COP)')).not.toBeInTheDocument();
    expect(within(form).getByLabelText('Volver a llamar el (hora de Bogotá)')).toBeInTheDocument();
    expect(within(form).getByLabelText('¿Hubo contacto directo con el cliente?')).toBeInTheDocument();
    await u.selectOptions(r, 'no_contesta');
    expect(within(form).queryByLabelText('Volver a llamar el (hora de Bogotá)')).not.toBeInTheDocument();
  });

  it('en una campaña de cobranza no ofrece "Venta"', async () => {
    const { form } = await abrirFormulario();
    const opciones = within(within(form).getByLabelText('Resultado')).getAllByRole('option').map((o) => o.textContent);
    expect(opciones).toContain('Promesa de pago');
    expect(opciones).not.toContain('Venta');
  });

  it('si la llamada no se contestó solo ofrece No contesta y Número errado', async () => {
    const { form } = await abrirFormulario({ llamada: llamada({ estado: 'no_contesta', contestada_en: null }) });
    await waitFor(() => {
      const opciones = within(within(form).getByLabelText('Resultado')).getAllByRole('option').map((o) => o.textContent);
      expect(opciones).toEqual(['Seleccione…', 'No contesta', 'Número errado']);
    });
  });

  it('valida el monto y la fecha en cliente sin llamar a la API', async () => {
    const { s, form, u } = await abrirFormulario();
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'promesa_pago');
    await u.type(within(form).getByLabelText('Monto prometido (COP)'), '2000000');
    fireEvent.change(within(form).getByLabelText('Fecha de pago'), { target: { value: sumarDias(hoyBogota(), 61) } });
    await u.click(within(form).getByRole('button', { name: 'Registrar tipificación' }));
    expect(await within(form).findByText(/no puede superar el saldo total/)).toBeInTheDocument();
    expect(within(form).getByText(/no puede superar 60 días/)).toBeInTheDocument();
    expect(s.cuerpoDe('/api/v1/consola/tipificaciones')).toBeUndefined();
  });

  it('volver a llamar envía la fecha con -05:00 y contacto_directo', async () => {
    const { s, form, u } = await abrirFormulario({ tipificar: () => errorApi(500, 'X', 'x') });
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'volver_a_llamar');
    const fecha = `${sumarDias(hoyBogota(), 2)}T09:30`;
    fireEvent.change(within(form).getByLabelText('Volver a llamar el (hora de Bogotá)'), { target: { value: fecha } });
    await u.selectOptions(within(form).getByLabelText('¿Hubo contacto directo con el cliente?'), 'si');
    await u.click(within(form).getByRole('button', { name: 'Registrar tipificación' }));
    await waitFor(() => expect(s.cuerpoDe('/api/v1/consola/tipificaciones')).toBeDefined());
    expect(s.cuerpoDe('/api/v1/consola/tipificaciones')).toEqual({
      llamada_id: 31, resultado: 'volver_a_llamar', observacion: null, volver_a_llamar_en: `${fecha}:00-05:00`, contacto_directo: true,
    });
  });

  it('muestra el 422 VOLVER_A_LLAMAR_FUERA_DE_FRANJA junto al campo', async () => {
    const { form, u } = await abrirFormulario({
      tipificar: () => errorApi(422, 'VOLVER_A_LLAMAR_FUERA_DE_FRANJA', 'La fecha no está permitida.', [
        { campo: 'volver_a_llamar_en', mensaje: 'Fuera de franja. Próxima ventana: 2026-10-26T07:00:00-05:00' },
      ]),
    });
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'volver_a_llamar');
    fireEvent.change(within(form).getByLabelText('Volver a llamar el (hora de Bogotá)'), { target: { value: `${sumarDias(hoyBogota(), 2)}T09:30` } });
    await u.selectOptions(within(form).getByLabelText('¿Hubo contacto directo con el cliente?'), 'no');
    await u.click(within(form).getByRole('button', { name: 'Registrar tipificación' }));
    expect(await within(form).findByText(/Próxima ventana: 2026-10-26T07:00:00-05:00/)).toBeInTheDocument();
  });

  it('muestra un 409 LLAMADA_YA_TIPIFICADA como error general', async () => {
    const { form, u } = await abrirFormulario({ tipificar: () => errorApi(409, 'LLAMADA_YA_TIPIFICADA', 'La llamada ya fue tipificada.') });
    await u.selectOptions(within(form).getByLabelText('Resultado'), 'rechazo');
    await u.click(within(form).getByRole('button', { name: 'Registrar tipificación' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('La llamada ya fue tipificada.');
  });
});
