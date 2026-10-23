import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ConfiguracionPolitica, Festivo, Politica } from '../api/tipos';
import { errorApi, iniciarSesionComo, renderizarApp, respuesta, simularFetch, type Manejador } from './utiles';

const cfg: ConfiguracionPolitica = {
  zona_horaria: 'America/Bogota',
  franjas: {
    lunes: [{ inicio: '07:00', fin: '19:00' }], martes: [{ inicio: '07:00', fin: '19:00' }],
    miercoles: [{ inicio: '07:00', fin: '19:00' }], jueves: [{ inicio: '07:00', fin: '19:00' }],
    viernes: [{ inicio: '07:00', fin: '19:00' }], sabado: [{ inicio: '08:00', fin: '15:00' }], domingo: [],
  },
  permitir_festivos: false,
  frecuencia: { max_contactos_dia: 1, max_canales_semana: 1, semana: 'calendario', solo_tras_contacto_directo: true, contar_intentos_sin_contacto: true },
  entrantes: { responder_fuera_de_franja: true, establecen_contacto_directo: true },
};
const politicas: Politica[] = [
  { id: 1, tipo_campana: 'cobranza', version: 1, activa: true, configuracion: cfg, creado_por: null, creado_en: '2026-10-23T15:00:00Z' },
  { id: 2, tipo_campana: 'venta', version: 3, activa: true, configuracion: { ...cfg, permitir_festivos: true }, creado_por: 1, creado_en: '2026-10-23T15:00:00Z' },
];
const festivo = (o: Partial<Festivo> = {}): Festivo => ({ id: 10, fecha: '2026-11-02', nombre: 'Todos los Santos', origen: 'calculado', activo: true, ...o });

function api(extra: Manejador[] = [], festivos: Festivo[] = [festivo()]) {
  return simularFetch(
    ...extra,
    (url) => (url === '/api/v1/cumplimiento/politicas' ? respuesta(200, politicas) : undefined),
    (url) => (url.startsWith('/api/v1/festivos?anio=') ? respuesta(200, festivos) : undefined),
  );
}

describe('Cumplimiento: políticas y festivos', () => {
  it('muestra las políticas activas en lectura, por día, con sábado 08:00-15:00 y domingo sin llamadas', async () => {
    iniciarSesionComo('agente');
    api();
    renderizarApp('/cumplimiento');
    const cobranza = await screen.findByRole('article', { name: 'Política de Cobranza' });
    expect(within(cobranza).getByRole('rowheader', { name: 'Sábado' }).nextElementSibling).toHaveTextContent('08:00 - 15:00');
    expect(within(cobranza).getByRole('rowheader', { name: 'Lunes' }).nextElementSibling).toHaveTextContent('07:00 - 19:00');
    expect(within(cobranza).getByRole('rowheader', { name: 'Domingo' }).nextElementSibling).toHaveTextContent('Sin llamadas');
    expect(within(cobranza).getByText(/versión 1/)).toBeInTheDocument();
    expect(within(cobranza).getByText(/no se llama/)).toBeInTheDocument();
    const venta = screen.getByRole('article', { name: 'Política de Venta' });
    expect(within(venta).getByText(/versión 3/)).toBeInTheDocument();
    expect(within(venta).getByText(/se permite llamar/)).toBeInTheDocument();
    // solo lectura: ningún campo editable ni botón de guardar política en las tarjetas
    expect(within(cobranza).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(cobranza).queryByRole('button')).not.toBeInTheDocument();
  });

  it('indica que todas las horas son de America/Bogota', async () => {
    iniciarSesionComo('agente');
    api();
    renderizarApp('/cumplimiento');
    expect(await screen.findByText(/zona horaria America\/Bogota/)).toBeInTheDocument();
  });

  it.each(['supervisor', 'agente'] as const)('%s ve festivos pero sin controles de administración', async (rol) => {
    iniciarSesionComo(rol);
    api();
    renderizarApp('/cumplimiento');
    await screen.findByRole('rowheader', { name: '02/11/2026' });
    expect(screen.queryByRole('button', { name: /Generar festivos/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Desactivar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Agregar festivo manual' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Acciones' })).not.toBeInTheDocument();
  });

  it('el administrador genera el año y ve el resumen', async () => {
    iniciarSesionComo('administrador');
    const m = api([(url, init) => (url === '/api/v1/festivos/generar' && init.method === 'POST' ? respuesta(200, { anio: 2026, creados: 18, existentes: 0 }) : undefined)]);
    renderizarApp('/cumplimiento');
    const anio = Number(new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Bogota', year: 'numeric' }).format(new Date()));
    await userEvent.setup().click(await screen.findByRole('button', { name: `Generar festivos de ${anio}` }));
    expect(await screen.findByText(`Año 2026: 18 festivos creados, 0 ya existían.`)).toBeInTheDocument();
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ anio });
  });

  it('el administrador desactiva un festivo con PATCH {activo:false}', async () => {
    iniciarSesionComo('administrador');
    const m = api([(url, init) => (url === '/api/v1/festivos/10' && init.method === 'PATCH' ? respuesta(200, festivo({ activo: false })) : undefined)]);
    renderizarApp('/cumplimiento');
    await userEvent.setup().click(await screen.findByRole('button', { name: /Desactivar Todos los Santos/ }));
    await waitFor(() => {
      const p = m.mock.calls.find(([, i]) => i?.method === 'PATCH')!;
      expect(JSON.parse(p[1]!.body as string)).toEqual({ activo: false });
    });
  });

  it('agregar festivo manual valida en cliente y muestra el 409 del servidor', async () => {
    iniciarSesionComo('administrador');
    const m = api([(url, init) => (url === '/api/v1/festivos' && init.method === 'POST'
      ? errorApi(409, 'FESTIVO_DUPLICADO', 'Ya existe un festivo en esa fecha.') : undefined)]);
    renderizarApp('/cumplimiento');
    const user = userEvent.setup();
    const formulario = await screen.findByRole('form', { name: 'Agregar festivo manual' });
    await user.click(within(formulario).getByRole('button', { name: 'Agregar festivo' }));
    expect(within(formulario).getByText('Seleccione una fecha.')).toBeInTheDocument();
    expect(within(formulario).getByText('Ingrese el nombre del festivo.')).toBeInTheDocument();
    expect(m.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(false);
    await user.type(within(formulario).getByLabelText('Fecha del festivo'), '2026-12-31');
    await user.type(within(formulario).getByLabelText('Nombre del festivo'), 'Día cívico');
    await user.click(within(formulario).getByRole('button', { name: 'Agregar festivo' }));
    expect(await screen.findByText('Ya existe un festivo en esa fecha.')).toBeInTheDocument();
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ fecha: '2026-12-31', nombre: 'Día cívico' });
  });

  it('consultar otro año valida el rango 1984..2100 y pide los festivos del año', async () => {
    iniciarSesionComo('supervisor');
    const m = api();
    renderizarApp('/cumplimiento');
    const user = userEvent.setup();
    const campo = await screen.findByLabelText('Año');
    const llamadas = () => m.mock.calls.filter(([u]) => String(u).startsWith('/api/v1/festivos?anio=')).map(([u]) => String(u));
    const antes = llamadas().length;
    for (const malo of ['1983', '2101', '']) {
      await user.clear(campo);
      if (malo) await user.type(campo, malo);
      await user.click(screen.getByRole('button', { name: 'Consultar' }));
      expect(await screen.findByText('Ingrese un año entre 1984 y 2100.')).toBeInTheDocument();
    }
    expect(llamadas().length).toBe(antes);
    await user.clear(campo);
    await user.type(campo, '2027');
    await user.click(screen.getByRole('button', { name: 'Consultar' }));
    await waitFor(() => expect(llamadas().at(-1)).toBe('/api/v1/festivos?anio=2027'));
    expect(screen.queryByText('Ingrese un año entre 1984 y 2100.')).not.toBeInTheDocument();
  });

  it('año sin festivos muestra el estado vacío', async () => {
    iniciarSesionComo('supervisor');
    api([], []);
    renderizarApp('/cumplimiento');
    expect(await screen.findByText(/No hay festivos registrados para/)).toBeInTheDocument();
  });
});

describe('Evaluador: casos adicionales', () => {
  it('permitido=true no muestra motivos ni próxima ventana', async () => {
    iniciarSesionComo('supervisor');
    api([(url, init) => (url.endsWith('/evaluar') && init.method === 'POST'
      ? respuesta(200, { permitido: true, motivos: [], momento_local: '2026-10-23T07:00:00-05:00', proxima_ventana_inicio: null, politica_version: 2 }) : undefined)]);
    renderizarApp('/cumplimiento');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText('Tipo de campaña'), 'venta');
    await user.type(screen.getByLabelText(/Fecha y hora/), '2026-10-23T07:00');
    await user.click(screen.getByRole('button', { name: 'Evaluar' }));
    const caja = (await screen.findByText('Llamada permitida')).closest('[role="status"]') as HTMLElement;
    expect(caja).toHaveTextContent('Política versión 2');
    expect(within(caja).queryByRole('list')).not.toBeInTheDocument();
    expect(caja).not.toHaveTextContent('Próxima ventana');
    expect(caja).not.toHaveTextContent('No hay ventana disponible');
  });

  it('los tres motivos se listan; sin próxima ventana avisa que no hay en 14 días', async () => {
    iniciarSesionComo('supervisor');
    api([(url, init) => (url.endsWith('/evaluar') && init.method === 'POST'
      ? respuesta(200, {
        permitido: false,
        motivos: [
          { codigo: 'FESTIVO', mensaje: 'x es festivo (Prueba).' },
          { codigo: 'DIA_SIN_FRANJA', mensaje: 'domingo sin franja.' },
          { codigo: 'FUERA_DE_FRANJA', mensaje: 'fuera de franja.' },
        ],
        momento_local: '2026-10-25T10:00:00-05:00', proxima_ventana_inicio: null, politica_version: 1,
      }) : undefined)]);
    renderizarApp('/cumplimiento');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Evaluar' }));
    const caja = (await screen.findByText('Llamada no permitida')).closest('[role="status"]') as HTMLElement;
    expect(within(caja).getAllByRole('listitem').map((l) => l.textContent?.split(':')[0])).toEqual(['FESTIVO', 'DIA_SIN_FRANJA', 'FUERA_DE_FRANJA']);
    expect(caja).toHaveTextContent('No hay ventana disponible en los próximos 14 días.');
  });

  it('el 422 del servidor sobre momento se muestra junto al campo', async () => {
    iniciarSesionComo('supervisor');
    api([(url, init) => (url.endsWith('/evaluar') && init.method === 'POST'
      ? errorApi(422, 'VALIDACION', 'Los datos enviados no son válidos.', [{ campo: 'momento', mensaje: 'Debe incluir zona horaria.' }]) : undefined)]);
    renderizarApp('/cumplimiento');
    const user = userEvent.setup();
    const campo = await screen.findByLabelText(/Fecha y hora/);
    await user.type(campo, '2026-10-23T07:00');
    await user.click(screen.getByRole('button', { name: 'Evaluar' }));
    await waitFor(() => expect(campo).toHaveAccessibleDescription(expect.stringContaining('Debe incluir zona horaria.')));
  });

  it('el offset enviado es -05:00 aunque el navegador esté en otra zona (TZ simulada)', async () => {
    iniciarSesionComo('supervisor');
    const m = api([(url, init) => (url.endsWith('/evaluar') && init.method === 'POST'
      ? respuesta(200, { permitido: true, motivos: [], momento_local: '2026-10-23T19:00:00-05:00', proxima_ventana_inicio: null, politica_version: 1 }) : undefined)]);
    renderizarApp('/cumplimiento');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Fecha y hora/), '2026-10-23T19:00');
    await user.click(screen.getByRole('button', { name: 'Evaluar' }));
    await screen.findByText('Llamada permitida');
    const llamada = m.mock.calls.find(([u]) => String(u).endsWith('/evaluar'))!;
    expect(JSON.parse(llamada[1]!.body as string).momento).toBe('2026-10-23T19:00:00-05:00');
    // la hora mostrada es la de Bogotá (7:00 p. m.), no la del navegador
    expect(screen.getByText(/Momento evaluado:/)).toHaveTextContent(/7:00|19:00/);
  });
});
