import { useCallback, useState, type FormEvent } from 'react';
import { listarTipificacionesCampana } from '../api/endpoints';
import type { OrigenGestion, ResultadoTipificacion, Tipificacion } from '../api/tipos';
import { ETIQUETA_RESULTADO, RESULTADOS } from '../utilidades/tipificacion';
import { formatearCOP, formatearFecha, formatearFechaHora } from '../utilidades/formato';
import { useCarga } from '../utilidades/useCarga';
import { Campo } from './Campo';
import { Cargando } from './Cargando';
import { MensajeError } from './MensajeError';
import { Paginador } from './Paginador';

const ORIGENES: [OrigenGestion, string][] = [['agente', 'Agente'], ['agente_ia', 'Agente IA'], ['sistema', 'Sistema']];

interface Filtros { resultado: ResultadoTipificacion | ''; origen: OrigenGestion | ''; desde: string; hasta: string }
const SIN_FILTROS: Filtros = { resultado: '', origen: '', desde: '', hasta: '' };

function Detalle({ t }: { t: Tipificacion }) {
  return (
    <>
      {t.promesa && <div>Promesa de {formatearCOP(t.promesa.monto)} para el {formatearFecha(t.promesa.fecha_pago)}</div>}
      {t.venta && <div>{t.venta.producto}: {formatearCOP(t.venta.valor)}</div>}
      {t.volver_a_llamar_en && <div>Volver a llamar: {formatearFechaHora(t.volver_a_llamar_en)}</div>}
      {t.observacion && <div>{t.observacion}</div>}
    </>
  );
}

/** Pestaña "Tipificaciones" del detalle de campaña. */
export function TipificacionesCampana({ campanaId }: { campanaId: number }) {
  const [form, setForm] = useState<Filtros>(SIN_FILTROS);
  const [filtros, setFiltros] = useState<Filtros>(SIN_FILTROS);
  const [page, setPage] = useState(1);
  const [errorFechas, setErrorFechas] = useState<string | undefined>();

  const cargador = useCallback(
    () => listarTipificacionesCampana(campanaId, { ...filtros, page, page_size: 20 }),
    [campanaId, filtros, page],
  );
  const { datos, cargando, error, recargar } = useCarga(cargador);

  function aplicar(e: FormEvent) {
    e.preventDefault();
    if (form.desde && form.hasta && form.hasta < form.desde) {
      setErrorFechas('La fecha final no puede ser anterior a la inicial.');
      return;
    }
    setErrorFechas(undefined);
    setPage(1);
    setFiltros(form);
  }

  return (
    <section aria-labelledby="t-tipifs">
      <h2 id="t-tipifs">Tipificaciones</h2>
      <form className="filtros" onSubmit={aplicar} noValidate aria-label="Filtros de tipificaciones">
        <Campo etiqueta="Resultado">
          {(p) => (
            <select {...p} value={form.resultado} onChange={(e) => setForm({ ...form, resultado: e.target.value as Filtros['resultado'] })}>
              <option value="">Todos</option>
              {RESULTADOS.map((r) => (
                <option key={r} value={r}>{ETIQUETA_RESULTADO[r]}</option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Origen">
          {(p) => (
            <select {...p} value={form.origen} onChange={(e) => setForm({ ...form, origen: e.target.value as Filtros['origen'] })}>
              <option value="">Todos</option>
              {ORIGENES.map(([v, n]) => (
                <option key={v} value={v}>{n}</option>
              ))}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Desde">
          {(p) => <input {...p} type="date" value={form.desde} onChange={(e) => setForm({ ...form, desde: e.target.value })} />}
        </Campo>
        <Campo etiqueta="Hasta" error={errorFechas}>
          {(p) => <input {...p} type="date" value={form.hasta} onChange={(e) => setForm({ ...form, hasta: e.target.value })} />}
        </Campo>
        <button type="submit">Filtrar</button>
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && <p>No hay tipificaciones que mostrar.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Tipificaciones de la campaña</caption>
              <thead>
                <tr>
                  <th scope="col">Fecha</th><th scope="col">Cliente</th><th scope="col">Agente</th>
                  <th scope="col">Origen</th><th scope="col">Resultado</th><th scope="col">Contacto directo</th>
                  <th scope="col">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((t) => (
                  <tr key={t.id}>
                    <th scope="row">{formatearFechaHora(t.creado_en)}</th>
                    <td>{t.cliente_nombre ?? '—'}</td>
                    <td>{t.agente_nombre ?? '—'}</td>
                    <td>{ORIGENES.find(([v]) => v === t.origen)?.[1] ?? t.origen}</td>
                    <td>{ETIQUETA_RESULTADO[t.resultado]}</td>
                    <td>{t.contacto_directo ? 'Sí' : 'No'}</td>
                    <td><Detalle t={t} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
        </>
      )}
    </section>
  );
}
