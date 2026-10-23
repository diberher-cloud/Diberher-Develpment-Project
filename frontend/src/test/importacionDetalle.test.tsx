import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Importacion } from '../api/tipos';
import { campanaEjemplo, errorApi, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

const imp: Importacion = {
  id: 7, campana_id: 5, nombre_archivo: 'cartera.csv', estado: 'completada', total_filas: 150,
  filas_importadas: 100, filas_duplicadas: 20, filas_invalidas: 25, filas_excluidas: 5, creado_por: 2,
  creado_en: '2026-10-23T15:10:00Z',
};

describe('Detalle de importación', () => {
  it('muestra los 5 contadores y los errores paginados con filtro de severidad', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      (url) => (url === '/api/v1/importaciones/7' ? respuesta(200, imp) : undefined),
      (url) => (url.startsWith('/api/v1/importaciones/7/errores')
        ? respuesta(200, {
          items: [{ fila: 3, campo: 'telefono_1', codigo: 'TELEFONO_INVALIDO', mensaje: 'Teléfono inválido (***4567).', severidad: 'error' }],
          total: 120, page: Number(new URL(url, 'http://x').searchParams.get('page') ?? 1), page_size: 50,
        }) : undefined),
    );
    renderizarApp('/importaciones/7');
    await screen.findByRole('heading', { name: 'Importación #7' });
    const resumen = screen.getByLabelText('Resumen de la importación');
    for (const [e, v] of [['Total de filas', '150'], ['Importadas', '100'], ['Duplicadas', '20'], ['Inválidas', '25'], ['Excluidas', '5']]) {
      expect(within(resumen).getByText(e).nextElementSibling).toHaveTextContent(v);
    }
    await screen.findByText('TELEFONO_INVALIDO');
    await screen.findByText(/Página 1 de 3 \(120 registros\)/);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Siguiente' }));
    await waitFor(() => expect(String(m.mock.calls.at(-1)![0])).toContain('page=2'));
    await user.selectOptions(screen.getByLabelText('Severidad'), 'advertencia');
    await waitFor(() => {
      const ultima = String(m.mock.calls.at(-1)![0]);
      expect(ultima).toContain('severidad=advertencia');
      expect(ultima).toContain('page=1');
    });
  });

  it('importación inexistente muestra el error 404', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => errorApi(404, 'NO_ENCONTRADO', 'Importación no encontrada.'));
    renderizarApp('/importaciones/99');
    expect(await screen.findByRole('alert')).toHaveTextContent('Importación no encontrada.');
  });

  it('el agente no puede abrir una importación', async () => {
    iniciarSesionComo('agente');
    const m = simularFetch(() => respuesta(200, imp));
    renderizarApp('/importaciones/7');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
    expect(m.mock.calls.some(([u]) => String(u).includes('/importaciones/'))).toBe(false);
  });
});

describe('Importación desde el detalle de campaña: casos adicionales', () => {
  function base(post: () => Response) {
    return simularFetch(
      (url, init) => (url === '/api/v1/campanas/5/importaciones' && init.method === 'POST' ? post() : undefined),
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
      () => respuesta(200, paginaVacia),
    );
  }

  it('con errores_truncados avisa y enlaza al detalle completo', async () => {
    iniciarSesionComo('supervisor');
    base(() => respuesta(201, { ...imp, errores: [{ fila: 2, campo: null, codigo: 'X', mensaje: 'm', severidad: 'error' }], errores_truncados: true }));
    renderizarApp('/campanas/5');
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText('Archivo CSV de clientes'), new File(['a'], 'c.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Importar' }));
    const estado = await screen.findByRole('status');
    expect(estado).toHaveTextContent('primeros 100 errores');
    expect(within(estado).getByRole('link', { name: /detalle completo/ })).toHaveAttribute('href', '/importaciones/7');
  });

  it('sin errores indica que no hay errores ni advertencias', async () => {
    iniciarSesionComo('supervisor');
    base(() => respuesta(201, { ...imp, filas_duplicadas: 0, filas_invalidas: 0, filas_excluidas: 0, errores: [], errores_truncados: false }));
    renderizarApp('/campanas/5');
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText('Archivo CSV de clientes'), new File(['a'], 'c.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Importar' }));
    expect(await screen.findByText('Sin errores ni advertencias.')).toBeInTheDocument();
  });

  it.each([
    [422, 'COLUMNAS_FALTANTES', 'Faltan columnas obligatorias.', [{ campo: 'telefono_1', mensaje: 'Columna obligatoria ausente.' }]],
    [413, 'ARCHIVO_DEMASIADO_GRANDE', 'El archivo supera el máximo permitido.', []],
    [409, 'CAMPANA_FINALIZADA', 'La campaña está finalizada.', []],
  ])('error %i %s del servidor se muestra con sus detalles', async (status, codigo, mensaje, detalles) => {
    iniciarSesionComo('supervisor');
    base(() => errorApi(status, codigo, mensaje, detalles));
    renderizarApp('/campanas/5');
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText('Archivo CSV de clientes'), new File(['a'], 'c.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Importar' }));
    const alerta = await screen.findByRole('alert');
    expect(alerta).toHaveTextContent(mensaje);
    for (const d of detalles) expect(alerta).toHaveTextContent(d.mensaje);
  });

  it('un archivo que no es .csv ni .xlsx se rechaza en cliente sin llamar a la API', async () => {
    iniciarSesionComo('supervisor');
    const m = base(() => respuesta(201, imp));
    renderizarApp('/campanas/5');
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(await screen.findByLabelText('Archivo CSV de clientes'), new File(['a'], 'datos.txt'));
    expect(await screen.findByText(/extensión \.csv/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Importar' })).toBeDisabled();
    expect(m.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(false);
  });

  it('exactamente 10 MiB se acepta', async () => {
    iniciarSesionComo('supervisor');
    const m = base(() => respuesta(201, { ...imp, errores: [], errores_truncados: false }));
    renderizarApp('/campanas/5');
    const limite = new File(['a'], 'limite.csv', { type: 'text/csv' });
    Object.defineProperty(limite, 'size', { value: 10 * 1024 * 1024 });
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText('Archivo CSV de clientes'), limite);
    expect(screen.getByRole('button', { name: 'Importar' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: 'Importar' }));
    await waitFor(() => expect(m.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true));
  });
});
