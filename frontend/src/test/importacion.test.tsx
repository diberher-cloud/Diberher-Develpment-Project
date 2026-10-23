import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { campanaEjemplo, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';
import type { Importacion } from '../api/tipos';

const importacion: Importacion = {
  id: 7, campana_id: 5, nombre_archivo: 'cartera.csv', estado: 'completada', total_filas: 5,
  filas_importadas: 2, filas_duplicadas: 1, filas_invalidas: 1, filas_excluidas: 1, creado_por: 2,
  creado_en: '2026-10-23T15:10:00Z',
  errores: [
    { fila: 3, campo: 'telefono_1', codigo: 'TELEFONO_INVALIDO', mensaje: 'Teléfono inválido (***4567).', severidad: 'error' },
    { fila: 4, campo: 'numero_documento', codigo: 'DUPLICADO_EN_ARCHIVO', mensaje: 'Documento repetido.', severidad: 'advertencia' },
  ],
  errores_truncados: false,
};

function baseCampana() {
  return simularFetch(
    (url, init) => (url === '/api/v1/campanas/5/importaciones' && init.method === 'POST' ? respuesta(201, importacion) : undefined),
    (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
    (url) => (/^\/api\/v1\/campanas\/5\/(importaciones|clientes)/.test(url) ? respuesta(200, paginaVacia) : undefined),
  );
}

describe('Importación de clientes', () => {
  it('rechaza un archivo mayor a 10 MiB sin llamar a la API', async () => {
    iniciarSesionComo('supervisor');
    const fetchMock = baseCampana();
    renderizarApp('/campanas/5');
    const entrada = await screen.findByLabelText('Archivo CSV de clientes');
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const llamadasPrevias = fetchMock.mock.calls.length;

    const grande = new File(['a'], 'enorme.csv', { type: 'text/csv' });
    Object.defineProperty(grande, 'size', { value: 10 * 1024 * 1024 + 1 });
    await userEvent.setup().upload(entrada, grande);

    expect(await screen.findByText(/supera el máximo de 10 MiB/)).toBeInTheDocument();
    const boton = screen.getByRole('button', { name: 'Importar' });
    expect(boton).toBeDisabled();
    await userEvent.setup().click(boton);
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(posts).toHaveLength(0);
    expect(fetchMock.mock.calls.length).toBe(llamadasPrevias);
  });

  it('el input solo acepta .csv', async () => {
    iniciarSesionComo('supervisor');
    baseCampana();
    renderizarApp('/campanas/5');
    expect(await screen.findByLabelText('Archivo CSV de clientes')).toHaveAttribute('accept', '.csv');
  });

  it('sube el archivo como multipart y muestra los 5 contadores y la tabla de errores', async () => {
    iniciarSesionComo('supervisor');
    const fetchMock = baseCampana();
    renderizarApp('/campanas/5');
    const entrada = await screen.findByLabelText('Archivo CSV de clientes');
    const u = userEvent.setup();
    await u.upload(entrada, new File(['tipo_documento;numero_documento'], 'cartera.csv', { type: 'text/csv' }));
    await u.click(screen.getByRole('button', { name: 'Importar' }));

    const resumen = await screen.findByRole('status');
    for (const [etiqueta, valor] of [['Total de filas', '5'], ['Importadas', '2'], ['Duplicadas', '1'], ['Inválidas', '1'], ['Excluidas', '1']]) {
      expect(within(resumen).getByText(etiqueta).nextElementSibling).toHaveTextContent(valor);
    }
    expect(within(resumen).getByRole('columnheader', { name: 'Severidad' })).toBeInTheDocument();
    expect(within(resumen).getByText('TELEFONO_INVALIDO')).toBeInTheDocument();
    expect(within(resumen).getByText('Advertencia')).toBeInTheDocument();

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!;
    expect(post[1]!.body).toBeInstanceOf(FormData);
    expect((post[1]!.headers as Record<string, string>)['Content-Type']).toBeUndefined();
  });
});
