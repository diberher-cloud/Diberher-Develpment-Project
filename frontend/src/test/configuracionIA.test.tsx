import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import type { ConfiguracionIA, Oferta } from '../api/tipos';
import {
  abrirSocket, campanaEjemplo, emitirEvento, errorApi, iniciarSesionComo, instalarWebSocketFalso, paginaVacia, renderizarApp,
  renderizarAppTiempoReal, respuesta, simularFetch, type Manejador,
} from './utiles';
import { configGlobal, configIA, oferta, reglasCobranza, ruta, rutaJson } from './utilesIA';
import { validarFormIA, formDesdeConfig, construirActualizacion } from '../utilidades/ia';

function base(c: Parameters<typeof campanaEjemplo>[0] = {}, extra: Manejador[] = []) {
  return simularFetch(
    ...extra,
    rutaJson('GET', '/campanas/5', () => campanaEjemplo({ whatsapp_habilitado: true, ...c })),
    rutaJson('GET', '/configuracion/ia', () => configGlobal()),
    (url) => (/^\/api\/v1\/campanas\/5\/(importaciones|clientes|tipificaciones|agentes)/.test(url) ? respuesta(200, paginaVacia) : undefined),
  );
}

async function abrirPestanaIA() {
  const u = userEvent.setup();
  await u.click(await screen.findByRole('tab', { name: 'Agente IA' }));
  await screen.findByRole('form', { name: 'Configuración del agente IA' });
  return u;
}

const cuerpos = (m: ReturnType<typeof simularFetch>, metodo: string, fin: string) =>
  m.mock.calls.filter(([u, i]) => String(u).endsWith(fin) && (i as RequestInit | undefined)?.method === metodo)
    .map(([, i]) => JSON.parse(String((i as RequestInit).body ?? '{}')) as Record<string, unknown>);

beforeEach(() => {
  instalarWebSocketFalso();
});

describe('Configuración IA de la campaña (F20)', () => {
  it('crear configuración -> activar con faltantes -> ver faltantes -> activar OK', async () => {
    iniciarSesionComo('supervisor');
    let c: ConfiguracionIA = configIA({
      configurada: false, version: 0, reglas: null, presupuesto_usd_mensual: '0.00', instrucciones: null,
      requisitos: { cumple: false, faltantes: [
        { codigo: 'SIN_CONFIGURACION', mensaje: 'Falta guardar la configuración.' },
        { codigo: 'EVALUACION_OFFLINE_PENDIENTE', mensaje: 'No hay una evaluación offline aprobada.' },
      ] },
    });
    let cumple = false;
    const m = base({}, [
      rutaJson('GET', '/campanas/5/ia', () => c),
      ruta('PUT', '/campanas/5/ia', (cuerpo) => {
        c = configIA({ configurada: true, version: 1, presupuesto_usd_mensual: String(cuerpo.presupuesto_usd_mensual), requisitos: c.requisitos });
        return respuesta(200, c);
      }),
      ruta('POST', '/campanas/5/ia/activar', () => {
        if (!cumple) {
          return errorApi(409, 'IA_REQUISITOS_ACTIVACION', 'No se cumplen los requisitos para activar la IA.', [
            { campo: 'requisitos', mensaje: 'No hay una evaluación offline aprobada.' },
          ]);
        }
        c = configIA({ activa: true, version: 1, activada_en: '2026-10-23T16:00:00Z' });
        return respuesta(200, c);
      }),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestanaIA();

    // Faltantes visibles desde el inicio, con enlace a las evaluaciones.
    const req = screen.getByRole('region', { name: 'Requisitos pendientes para activar la IA' });
    expect(within(req).getByText(/Falta guardar la configuración/)).toBeInTheDocument();
    expect(within(req).getByRole('link', { name: 'Ir a las evaluaciones' })).toHaveAttribute('href', '/ia/evaluaciones');

    // Guardar la configuración inicial (version_esperada 0).
    await u.clear(screen.getByLabelText('Presupuesto mensual (USD)'));
    await u.type(screen.getByLabelText('Presupuesto mensual (USD)'), '200');
    await u.clear(screen.getByLabelText('Descuento máximo general (%)'));
    await u.type(screen.getByLabelText('Descuento máximo general (%)'), '20');
    await u.clear(screen.getByLabelText('Monto mínimo de la promesa (COP)'));
    await u.type(screen.getByLabelText('Monto mínimo de la promesa (COP)'), '100000');
    await u.clear(screen.getByLabelText('Monto mínimo por cuota (COP)'));
    await u.type(screen.getByLabelText('Monto mínimo por cuota (COP)'), '50000');
    await u.click(screen.getByRole('button', { name: 'Guardar configuración' }));
    expect(await screen.findByText('Configuración guardada (versión 1).')).toBeInTheDocument();
    const put = cuerpos(m, 'PUT', '/campanas/5/ia')[0] as { version_esperada: number; reglas: Record<string, unknown>; presupuesto_usd_mensual: string };
    expect(put.version_esperada).toBe(0);
    expect(put.presupuesto_usd_mensual).toBe('200.00');
    expect(put.reglas).toMatchObject({ descuento_max_pct: '20.00', monto_minimo_promesa: '100000.00', monto_minimo_cuota: '50000.00', max_cuotas: 1 });

    // Activar con faltantes: la confirmación es en la propia página; el servidor responde 409.
    await u.click(screen.getByRole('button', { name: 'Activar IA' }));
    expect(screen.getByRole('group', { name: '¿Activar el agente IA?' })).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Confirmar activación' }));
    const alerta = await screen.findByText('No se cumplen los requisitos para activar la IA.');
    expect(alerta.closest('[role="alert"]')).toHaveTextContent('No hay una evaluación offline aprobada.');
    expect(screen.getByText('IA inactiva')).toBeInTheDocument();

    // Cumplidos los requisitos, se activa.
    cumple = true;
    await u.click(screen.getByRole('button', { name: 'Activar IA' }));
    await u.click(screen.getByRole('button', { name: 'Confirmar activación' }));
    expect(await screen.findByText('Agente IA activado.')).toBeInTheDocument();
    expect(screen.getByText('IA activa')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Desactivar IA (kill switch)' })).toBeInTheDocument();
  });

  it('409 IA_VERSION_CONFLICTO: explica el conflicto, no pisa lo escrito y tras recargar usa la versión nueva', async () => {
    iniciarSesionComo('administrador');
    let c = configIA({ version: 3 });
    let puts = 0;
    const m = base({}, [
      rutaJson('GET', '/campanas/5/ia', () => c),
      ruta('PUT', '/campanas/5/ia', (cuerpo) => {
        puts += 1;
        if (cuerpo.version_esperada !== 4) return errorApi(409, 'IA_VERSION_CONFLICTO', 'La versión esperada no coincide.');
        c = configIA({ version: 5, instrucciones: String(cuerpo.instrucciones) });
        return respuesta(200, c);
      }),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestanaIA();
    const instr = screen.getByLabelText('Instrucciones de la campaña para la IA');
    await u.clear(instr);
    await u.type(instr, 'Mi cambio');
    c = configIA({ version: 4, instrucciones: 'Cambio de otra persona' }); // otra sesión guardó antes
    await u.click(screen.getByRole('button', { name: 'Guardar configuración' }));

    const alerta = await screen.findByText('La configuración cambió mientras la editaba.');
    expect(alerta.closest('[role="alert"]')).toHaveTextContent('versión 3');
    expect(screen.getByLabelText('Instrucciones de la campaña para la IA')).toHaveValue('Mi cambio'); // no se pierde el texto

    await u.click(screen.getByRole('button', { name: 'Recargar configuración vigente' }));
    await waitFor(() => expect(screen.getByLabelText('Instrucciones de la campaña para la IA')).toHaveValue('Cambio de otra persona'));
    await u.clear(screen.getByLabelText('Instrucciones de la campaña para la IA'));
    await u.type(screen.getByLabelText('Instrucciones de la campaña para la IA'), 'Segundo intento');
    await u.click(screen.getByRole('button', { name: 'Guardar configuración' }));
    expect(await screen.findByText('Configuración guardada (versión 5).')).toBeInTheDocument();
    expect(puts).toBe(2);
    expect(cuerpos(m, 'PUT', '/campanas/5/ia').map((x) => x.version_esperada)).toEqual([3, 4]);
  });

  it('tramos inválidos se marcan antes de enviar y los errores 422 por ruta aparecen junto al campo', async () => {
    iniciarSesionComo('supervisor');
    const m = base({}, [
      rutaJson('GET', '/campanas/5/ia', () => configIA()),
      ruta('PUT', '/campanas/5/ia', () => errorApi(422, 'VALIDACION', 'Datos inválidos.', [
        { campo: 'reglas.descuento_max_pct_por_cuotas.1.max_cuotas', mensaje: 'Debe ser mayor que el tramo anterior (servidor).' },
      ])),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestanaIA();

    // Tramo 2 desordenado (2 <= 1 no; ponemos 1, igual que el tramo 1) y descuento por encima del general.
    const cuotas2 = screen.getByLabelText('Cuotas del tramo 2');
    await u.clear(cuotas2);
    await u.type(cuotas2, '1');
    const pct2 = screen.getByLabelText('Descuento del tramo 2 (%)');
    await u.clear(pct2);
    await u.type(pct2, '35');
    await u.click(screen.getByRole('button', { name: 'Guardar configuración' }));
    expect(await screen.findByText('Los tramos deben ir en orden estrictamente creciente de cuotas.')).toBeInTheDocument();
    expect(screen.getByText(/No puede superar el descuento máximo general/)).toBeInTheDocument();
    expect(screen.getByLabelText('Cuotas del tramo 2')).toHaveAttribute('aria-invalid', 'true');
    expect(cuerpos(m, 'PUT', '/campanas/5/ia')).toHaveLength(0);

    // Con tramos válidos localmente, el 422 del servidor por ruta se muestra junto al campo.
    await u.clear(screen.getByLabelText('Cuotas del tramo 2'));
    await u.type(screen.getByLabelText('Cuotas del tramo 2'), '3');
    await u.clear(screen.getByLabelText('Descuento del tramo 2 (%)'));
    await u.type(screen.getByLabelText('Descuento del tramo 2 (%)'), '10');
    await u.click(screen.getByRole('button', { name: 'Guardar configuración' }));
    expect(await screen.findByText('Debe ser mayor que el tramo anterior (servidor).')).toBeInTheDocument();
    expect(screen.getByLabelText('Cuotas del tramo 2')).toHaveAttribute('aria-invalid', 'true');
    expect(cuerpos(m, 'PUT', '/campanas/5/ia')).toHaveLength(1);
  });

  it('desactivar (kill switch) pide confirmación en la página; cancelar no llama a la API', async () => {
    iniciarSesionComo('supervisor');
    let c = configIA({ activa: true, activada_en: '2026-10-23T16:00:00Z' });
    const m = base({}, [
      rutaJson('GET', '/campanas/5/ia', () => c),
      ruta('POST', '/campanas/5/ia/desactivar', () => {
        c = configIA({ activa: false, desactivada_motivo: 'manual', desactivada_en: '2026-10-23T17:00:00Z' });
        return respuesta(200, c);
      }),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestanaIA();
    expect(screen.getByText('IA activa')).toBeInTheDocument();

    await u.click(screen.getByRole('button', { name: 'Desactivar IA (kill switch)' }));
    const conf = screen.getByRole('group', { name: '¿Desactivar el agente IA?' });
    expect(within(conf).getByText(/pasarán a la cola de atención humana/)).toBeInTheDocument();
    expect(conf).toHaveFocus();
    await u.click(within(conf).getByRole('button', { name: 'Cancelar' }));
    expect(m.mock.calls.some(([u2]) => String(u2).endsWith('/desactivar'))).toBe(false);

    await u.click(screen.getByRole('button', { name: 'Desactivar IA (kill switch)' }));
    await u.click(screen.getByRole('button', { name: 'Confirmar desactivación' }));
    expect(await screen.findByText(/Agente IA desactivado/)).toBeInTheDocument();
    expect(screen.getByText('IA inactiva')).toBeInTheDocument();
    expect(screen.getByText(/desactivada manualmente/)).toBeInTheDocument();
    expect(m.mock.calls.filter(([u2]) => String(u2).endsWith('/desactivar'))).toHaveLength(1);
  });

  it('un evento ia.configuracion (kill switch automático por presupuesto) actualiza el estado sin pisar el formulario', async () => {
    iniciarSesionComo('supervisor');
    let c = configIA({ activa: true });
    base({}, [rutaJson('GET', '/campanas/5/ia', () => c)]);
    renderizarAppTiempoReal('/campanas/5');
    const ws = await abrirSocket(1, 'supervisor');
    const u = await abrirPestanaIA();
    const instr = screen.getByLabelText('Instrucciones de la campaña para la IA');
    await u.type(instr, ' extra');
    c = configIA({ activa: false, version: 4, desactivada_motivo: 'presupuesto', instrucciones: 'otra' });
    emitirEvento(ws, { tipo: 'ia.configuracion', datos: { campana_id: 5, activa: false, version: 4, desactivada_motivo: 'presupuesto' } });
    expect(await screen.findByText('IA inactiva')).toBeInTheDocument();
    expect(screen.getByText(/presupuesto mensual agotado/)).toBeInTheDocument();
    expect(screen.getByLabelText('Instrucciones de la campaña para la IA')).toHaveValue('Si el cliente menciona desempleo, ofrezca 6 cuotas. extra');
    expect(screen.getByText(/Otra persona guardó una versión nueva/)).toBeInTheDocument();
  });

  it('campaña finalizada: el formulario queda deshabilitado', async () => {
    iniciarSesionComo('supervisor');
    base({ estado: 'finalizada' }, [rutaJson('GET', '/campanas/5/ia', () => configIA())]);
    renderizarApp('/campanas/5');
    await abrirPestanaIA();
    expect(screen.getByLabelText('Modelo')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Guardar configuración' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Activar IA' })).toBeDisabled();
  });

  it('el agente no ve la pestaña', async () => {
    iniciarSesionComo('agente');
    base({}, []);
    renderizarApp('/campanas/5');
    await screen.findByRole('heading', { name: 'Cobranza octubre' });
    expect(screen.queryByRole('tab', { name: 'Agente IA' })).not.toBeInTheDocument();
  });
});

describe('Ofertas de la campaña de venta (F20)', () => {
  it('lista, crea (código en mayúsculas, precio con 2 decimales), duplicado y desactivar sin requisitos', async () => {
    iniciarSesionComo('supervisor');
    let ofertas: Oferta[] = [oferta()];
    const m = base({ tipo: 'venta' }, [
      rutaJson('GET', '/campanas/5/ia', () => configIA({ campana_tipo: 'venta', reglas: { max_unidades_por_venta: 2, requiere_aceptacion_terminos: true } })),
      rutaJson('GET', '/campanas/5/ofertas', () => ofertas),
      ruta('POST', '/campanas/5/ofertas', (cuerpo) => {
        if (cuerpo.codigo === 'SEG-HOGAR') return errorApi(409, 'OFERTA_DUPLICADA', 'Duplicada.');
        ofertas = [...ofertas, oferta({ id: 5, codigo: String(cuerpo.codigo), nombre: String(cuerpo.nombre), precio: String(cuerpo.precio) })];
        return respuesta(201, ofertas[1]);
      }),
      ruta('PATCH', '/campanas/5/ofertas/4', () => errorApi(409, 'IA_REQUISITOS_ACTIVACION', 'No se puede desactivar la última oferta activa con la IA activa.')),
    ]);
    renderizarApp('/campanas/5');
    const u = await abrirPestanaIA();
    expect(screen.getByLabelText('Unidades máximas por venta')).toHaveValue(2);
    expect(await screen.findByRole('rowheader', { name: 'SEG-HOGAR' })).toBeInTheDocument();
    expect(screen.getByText('$ 89.900')).toBeInTheDocument();

    await u.click(screen.getByRole('button', { name: 'Nueva oferta' }));
    const form = screen.getByRole('form', { name: 'Nueva oferta' });
    await u.type(within(form).getByLabelText('Código'), 'seg-hogar');
    await u.type(within(form).getByLabelText('Nombre'), 'Otro seguro');
    await u.type(within(form).getByLabelText('Precio unitario (COP)'), '0');
    await u.click(within(form).getByRole('button', { name: 'Guardar oferta' }));
    expect(await within(form).findByText(/El precio debe ser un número mayor que 0/)).toBeInTheDocument();
    await u.clear(within(form).getByLabelText('Precio unitario (COP)'));
    await u.type(within(form).getByLabelText('Precio unitario (COP)'), '120000');
    await u.click(within(form).getByRole('button', { name: 'Guardar oferta' }));
    expect(await within(form).findByText('Ya existe una oferta con ese código en la campaña.')).toBeInTheDocument();
    expect(cuerpos(m, 'POST', '/campanas/5/ofertas')[0]).toMatchObject({ codigo: 'SEG-HOGAR', precio: '120000.00' });

    await u.clear(within(form).getByLabelText('Código'));
    await u.type(within(form).getByLabelText('Código'), 'seg-vida');
    await u.click(within(form).getByRole('button', { name: 'Guardar oferta' }));
    expect(await screen.findByText('Oferta creada.')).toBeInTheDocument();
    expect(await screen.findByRole('rowheader', { name: 'SEG-VIDA' })).toBeInTheDocument();

    await u.click(screen.getByRole('button', { name: /Desactivar\s*oferta SEG-HOGAR/ }));
    expect(await screen.findByText('No se puede desactivar la última oferta activa con la IA activa.')).toBeInTheDocument();
  });
});

describe('Validación y construcción del formulario (unidad)', () => {
  it('formDesdeConfig -> construirActualizacion conserva las reglas y normaliza decimales', () => {
    const c = configIA({ reglas: reglasCobranza() });
    const f = formDesdeConfig(c);
    f.cobranza.descuento_max_pct = '20,5';
    f.max_costo_conversacion_usd = '0.8';
    expect(validarFormIA(f, 'cobranza')).toEqual({});
    const cuerpo = construirActualizacion(f, 'cobranza', 3);
    expect(cuerpo.version_esperada).toBe(3);
    expect(cuerpo.max_costo_conversacion_usd).toBe('0.80');
    expect(cuerpo.reglas).toMatchObject({ descuento_max_pct: '20.50', max_cuotas: 6, periodicidades: ['quincenal', 'mensual'] });
  });

  it('detecta periodicidades vacías con varias cuotas, plazo total menor y montos no positivos', () => {
    const f = formDesdeConfig(configIA());
    f.cobranza.periodicidades = [];
    f.cobranza.plazo_max_dias_total = '5';
    f.cobranza.monto_minimo_cuota = '0';
    const e = validarFormIA(f, 'cobranza');
    expect(Object.keys(e).sort()).toEqual(['reglas.monto_minimo_cuota', 'reglas.periodicidades', 'reglas.plazo_max_dias_total']);
  });
});
