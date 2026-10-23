import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import type { Exclusion } from '../api/tipos';
import { errorApi, iniciarSesionComo, renderizarApp, respuesta, simularFetch } from './utiles';

const excl = (o: Partial<Exclusion> = {}): Exclusion => ({
  id: 3, numero_e164: '+573001234567', motivo: 'rne', aplica_a: 'venta', observacion: 'Carga RNE', creado_por: 2,
  creado_en: '2026-10-23T15:20:00Z', ...o,
});
const pag = (items: Exclusion[]) => ({ items, total: items.length, page: 1, page_size: 20 });

describe('Exclusiones', () => {
  it('lista con motivo y alcance legibles', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => respuesta(200, pag([excl()])));
    renderizarApp('/exclusiones');
    const fila = (await screen.findByRole('rowheader', { name: '+573001234567' })).closest('tr')!;
    expect(within(fila).getByText('Registro de Números Excluidos (RNE)')).toBeInTheDocument();
    expect(within(fila).getByText('Venta')).toBeInTheDocument();
    expect(within(fila).getByText('Carga RNE')).toBeInTheDocument();
  });

  it('alta individual envía el teléfono recortado y limpia el formulario', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      (url, init) => (url === '/api/v1/exclusiones' && init.method === 'POST' ? respuesta(201, excl({ motivo: 'manual', aplica_a: 'todas' })) : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Teléfono'), '  300 123 4567 ');
    await u.type(screen.getByLabelText('Observación (opcional)'), 'pidió no ser llamado');
    await u.click(screen.getByRole('button', { name: 'Agregar' }));
    expect(await screen.findByText('Número +573001234567 excluido.')).toBeInTheDocument();
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({
      telefono: '300 123 4567', motivo: 'manual', aplica_a: 'todas', observacion: 'pidió no ser llamado',
    });
    expect(screen.getByLabelText('Teléfono')).toHaveValue('');
  });

  it('elegir motivo RNE preselecciona "Venta" como alcance', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => respuesta(200, pag([])));
    renderizarApp('/exclusiones');
    await screen.findByLabelText('Teléfono');
    await userEvent.setup().selectOptions(screen.getByLabelText('Motivo'), 'rne');
    expect(screen.getByLabelText('Aplica a')).toHaveValue('venta');
  });

  it('422 del teléfono se muestra junto al campo', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (_url, init) => (init.method === 'POST' ? errorApi(422, 'VALIDACION', 'Los datos enviados no son válidos.', [{ campo: 'telefono', mensaje: 'TELEFONO_INVALIDO: El teléfono no es válido.' }]) : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    const campo = await screen.findByLabelText('Teléfono');
    await u.type(campo, '12345');
    await u.click(screen.getByRole('button', { name: 'Agregar' }));
    await waitFor(() => expect(campo).toHaveAccessibleDescription(expect.stringContaining('TELEFONO_INVALIDO')));
    expect(campo).toHaveAttribute('aria-invalid', 'true');
  });

  it('409 EXCLUSION_DUPLICADA se informa con role=alert', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (_url, init) => (init.method === 'POST' ? errorApi(409, 'EXCLUSION_DUPLICADA', 'El número ya está excluido para esa finalidad.') : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText('Teléfono'), '3001234567');
    await u.click(screen.getByRole('button', { name: 'Agregar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('ya está excluido');
  });

  it('eliminar pide confirmación; cancelar no llama a DELETE y aceptar sí', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      (url, init) => (url === '/api/v1/exclusiones/3' && init.method === 'DELETE' ? respuesta(204) : undefined),
      () => respuesta(200, pag([excl()])),
    );
    const confirmar = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderizarApp('/exclusiones');
    const boton = await screen.findByRole('button', { name: /Eliminar \+573001234567/ });
    const u = userEvent.setup();
    await u.click(boton);
    expect(m.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(false);
    confirmar.mockReturnValue(true);
    await u.click(boton);
    await waitFor(() => expect(m.mock.calls.some(([url, i]) => url === '/api/v1/exclusiones/3' && i?.method === 'DELETE')).toBe(true));
  });

  it('filtros y búsqueda viajan como parámetros', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(() => respuesta(200, pag([])));
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await screen.findByText(/No hay exclusiones/);
    await u.selectOptions(screen.getByLabelText('Filtrar por motivo'), 'rne');
    await u.selectOptions(screen.getByLabelText('Filtrar por aplicación'), 'venta');
    await u.type(screen.getByLabelText('Buscar por teléfono'), '300 123');
    await u.click(screen.getAllByRole('button', { name: 'Buscar' })[0]);
    await waitFor(() => {
      const ultima = String(m.mock.calls.at(-1)![0]);
      expect(ultima).toContain('motivo=rne');
      expect(ultima).toContain('aplica_a=venta');
      expect(ultima).toContain('q=300+123');
    });
  });

  it('carga masiva: sube multipart con motivo y aplica_a y muestra el resumen', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      (url, init) => (url === '/api/v1/exclusiones/importar' && init.method === 'POST'
        ? respuesta(200, {
          total_filas: 1000, creadas: 990, duplicadas: 8, invalidas: 2,
          errores: [{ fila: 17, campo: 'telefono', codigo: 'TELEFONO_INVALIDO', mensaje: 'Teléfono inválido (***1234).', severidad: 'error' }],
          errores_truncados: false,
        }) : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await u.upload(await screen.findByLabelText('Archivo CSV de exclusiones (columna telefono)'), new File(['telefono\n3001234567'], 'rne.csv', { type: 'text/csv' }));
    await u.click(screen.getByRole('button', { name: 'Cargar' }));
    const resumen = await screen.findByText('Resultado de la carga');
    const caja = resumen.closest('[role="status"]') as HTMLElement;
    for (const [etiqueta, valor] of [['Total de filas', '1000'], ['Creadas', '990'], ['Duplicadas', '8'], ['Inválidas', '2']]) {
      expect(within(caja).getByText(etiqueta).nextElementSibling).toHaveTextContent(valor);
    }
    expect(within(caja).getByText('TELEFONO_INVALIDO')).toBeInTheDocument();
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    const form = post[1]!.body as FormData;
    expect(form.get('motivo')).toBe('rne');
    expect(form.get('aplica_a')).toBe('venta');
    expect((form.get('archivo') as File).name).toBe('rne.csv');
  });

  it('carga masiva: archivo que no es .csv/.xlsx o > 10 MiB se rechaza sin llamar a la API', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(() => respuesta(200, pag([])));
    renderizarApp('/exclusiones');
    await screen.findByText(/No hay exclusiones/);
    const antes = m.mock.calls.length;
    const entrada = screen.getByLabelText('Archivo CSV de exclusiones (columna telefono)');
    const u = userEvent.setup({ applyAccept: false });
    await u.upload(entrada, new File(['x'], 'lista.txt'));
    expect(await screen.findByText(/extensión \.csv/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cargar' })).toBeDisabled();
    const grande = new File(['x'], 'grande.csv');
    Object.defineProperty(grande, 'size', { value: 10 * 1024 * 1024 + 1 });
    await u.upload(entrada, grande);
    expect(await screen.findByText(/supera el máximo de 10 MiB/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cargar' })).toBeDisabled();
    expect(m.mock.calls.length).toBe(antes);
  });

  it('carga masiva: error 413 del servidor se muestra', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (_url, init) => (init.method === 'POST' ? errorApi(413, 'ARCHIVO_DEMASIADO_GRANDE', 'El archivo supera el máximo permitido.') : undefined),
      () => respuesta(200, pag([])),
    );
    renderizarApp('/exclusiones');
    const u = userEvent.setup();
    await u.upload(await screen.findByLabelText('Archivo CSV de exclusiones (columna telefono)'), new File(['telefono\n1'], 'a.csv'));
    await u.click(screen.getByRole('button', { name: 'Cargar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El archivo supera el máximo permitido.');
  });
});
