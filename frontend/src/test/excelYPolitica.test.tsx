import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ConfiguracionPolitica, Politica } from '../api/tipos';
import { campanaEjemplo, iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

describe('Importación desde Excel (.xlsx)', () => {
  it('clientes: acepta un .xlsx (también en mayúsculas) y lo envía como multipart', async () => {
    iniciarSesionComo('supervisor');
    const m = simularFetch(
      (url, i) => (url === '/api/v1/campanas/5/importaciones' && i.method === 'POST'
        ? respuesta(201, { id: 9, campana_id: 5, nombre_archivo: 'cartera.xlsx', estado: 'completada', total_filas: 1, filas_importadas: 1,
            filas_duplicadas: 0, filas_invalidas: 0, filas_excluidas: 0, creado_por: 2, creado_en: '2026-10-23T15:10:00Z', errores: [], errores_truncados: false })
        : undefined),
      (url) => (url === '/api/v1/campanas/5' ? respuesta(200, campanaEjemplo()) : undefined),
      (url) => (/^\/api\/v1\/campanas\/5\/(importaciones|clientes)/.test(url) ? respuesta(200, paginaVacia) : undefined),
    );
    renderizarApp('/campanas/5');
    const u = userEvent.setup();
    const entrada = await screen.findByLabelText('Archivo CSV de clientes');
    expect(screen.getByText('Archivo .csv o .xlsx de hasta 10 MiB.')).toBeInTheDocument();
    await u.upload(entrada, new File(['x'], 'CARTERA.XLSX', { type: XLSX }));
    expect(screen.queryByText(/extensión/)).not.toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Importar' }));
    await screen.findByText(/Resultado de la importación #9/);
    const post = m.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect((post[1]!.body as FormData).get('archivo')).toBeInstanceOf(File);
    expect(((post[1]!.body as FormData).get('archivo') as File).name).toBe('CARTERA.XLSX');
  });

  it('exclusiones: acepta .xlsx y rechaza .xls', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(() => respuesta(200, paginaVacia));
    renderizarApp('/exclusiones');
    const entrada = await screen.findByLabelText('Archivo CSV de exclusiones (columna telefono)');
    expect(entrada).toHaveAttribute('accept', '.csv,.xlsx');
    const u = userEvent.setup({ applyAccept: false });
    await u.upload(entrada, new File(['x'], 'lista.xlsx'));
    expect(screen.getByRole('button', { name: 'Cargar' })).toBeEnabled();
    await u.upload(entrada, new File(['x'], 'lista.xls'));
    expect(await screen.findByText('El archivo debe tener extensión .csv o .xlsx.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cargar' })).toBeDisabled();
  });
});

describe('Cumplimiento: campos nuevos de la política', () => {
  const cfg: ConfiguracionPolitica = {
    zona_horaria: 'America/Bogota',
    franjas: { lunes: [], martes: [], miercoles: [], jueves: [], viernes: [], sabado: [], domingo: [] },
    permitir_festivos: false,
    frecuencia: { max_contactos_dia: 1, max_canales_semana: 1, semana: 'calendario', solo_tras_contacto_directo: true, contar_intentos_sin_contacto: false },
    entrantes: { responder_fuera_de_franja: true, establecen_contacto_directo: false },
  };
  const pol: Politica = { id: 1, tipo_campana: 'cobranza', version: 2, activa: true, configuracion: cfg, creado_por: null, creado_en: '2026-10-23T15:00:00Z' };

  it('muestra contar_intentos_sin_contacto y entrantes', async () => {
    iniciarSesionComo('supervisor');
    simularFetch(
      (url) => (url === '/api/v1/cumplimiento/politicas' ? respuesta(200, [pol]) : undefined),
      (url) => (url.startsWith('/api/v1/festivos') ? respuesta(200, []) : undefined),
    );
    renderizarApp('/cumplimiento');
    const art = await screen.findByRole('article', { name: 'Política de Cobranza' });
    expect(within(art).getByText(/Intentos sin contacto directo: no cuentan/)).toBeInTheDocument();
    expect(within(art).getByText(/se responde fuera de la franja; no establecen contacto directo/)).toBeInTheDocument();
    expect(within(art).getByText(/máximo 1 contacto\(s\) por día/)).toBeInTheDocument();
  });
});
