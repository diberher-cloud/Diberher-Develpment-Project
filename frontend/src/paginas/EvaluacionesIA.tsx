import { useCallback, useState } from 'react';
import { lanzarEvaluacion, listarCampanas, listarEvaluaciones, obtenerEvaluacion } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { EvaluacionIA } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../utilidades/formato';
import { ETIQUETA_ESTADO_EVALUACION, formatearUSD, traducirErrorIA } from '../utilidades/ia';
import { useAgrupador } from '../utilidades/useAgrupador';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';

const textoAprobada = (e: EvaluacionIA) => (e.aprobada === null ? '—' : e.aprobada ? 'Aprobada' : 'No aprobada');

/** Evaluaciones de la IA: lanzar (solo administrador), ver estado y resultados por caso. */
export function EvaluacionesIA() {
  const { tieneRol } = useAuth();
  const esAdmin = tieneRol('administrador');
  const { reconexiones } = useConexionTiempoReal();
  const [modo, setModo] = useState<'' | 'offline' | 'online'>('');
  const [page, setPage] = useState(1);
  const [seleccion, setSeleccion] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return listarEvaluaciones({ page, page_size: 20, modo });
  }, [page, modo, version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const cargadorCampanas = useCallback(() => listarCampanas({ page_size: 100 }), []);
  const { datos: campanas } = useCarga(cargadorCampanas);
  const nombreCampana = (id: number | null) => (id === null ? '—' : campanas?.items.find((c) => c.id === id)?.nombre ?? `Campaña #${id}`);

  const programar = useAgrupador<'lista'>(500, () => setVersion((v) => v + 1));
  useEventoTiempoReal('ia.evaluacion', () => programar('lista'));

  return (
    <section aria-labelledby="t-eval">
      <div className="barra-titulo">
        <h1 id="t-eval">Evaluaciones de la IA</h1>
      </div>
      <p>
        La evaluación offline (casos con un modelo simulado) es requisito para activar la IA en una campaña. La online usa el modelo
        real de la campaña y tiene coste.
      </p>
      {esAdmin && <LanzarEvaluacion campanas={campanas?.items ?? []} onLanzada={(e) => { setSeleccion(e.id); setVersion((v) => v + 1); }} />}
      {!esAdmin && <p className="ayuda">Solo un administrador puede lanzar evaluaciones.</p>}

      <section aria-labelledby="t-eval-lista" className="tarjeta">
        <h2 id="t-eval-lista">Evaluaciones realizadas</h2>
        <form className="filtros" role="search" aria-label="Filtros de evaluaciones" onSubmit={(e) => e.preventDefault()}>
          <Campo etiqueta="Modo">
            {(p) => (
              <select {...p} value={modo} onChange={(e) => { setPage(1); setModo(e.target.value as '' | 'offline' | 'online'); }}>
                <option value="">Todos</option>
                <option value="offline">Offline</option>
                <option value="online">Online</option>
              </select>
            )}
          </Campo>
        </form>
        <MensajeError error={error} onReintentar={recargar} />
        {cargando && !datos && <Cargando />}
        {datos && datos.items.length === 0 && !error && <p>Aún no hay evaluaciones.</p>}
        {datos && datos.items.length > 0 && (
          <>
            <div className="tabla-scroll" aria-busy={cargando} aria-live="polite">
              <table>
                <caption className="solo-lectura">Evaluaciones de la IA</caption>
                <thead>
                  <tr>
                    <th scope="col">N.º</th><th scope="col">Modo</th><th scope="col">Campaña</th><th scope="col">Prompt</th>
                    <th scope="col">Huella</th><th scope="col">Estado</th><th scope="col">Resultado</th><th scope="col">Coste</th>
                    <th scope="col">Fecha</th><th scope="col"><span className="solo-lectura">Acciones</span></th>
                  </tr>
                </thead>
                <tbody>
                  {datos.items.map((e) => (
                    <tr key={e.id} aria-current={seleccion === e.id ? 'true' : undefined}>
                      <th scope="row">{e.id}</th>
                      <td>{e.modo === 'offline' ? 'Offline' : 'Online'}{e.patron_casos ? ` (casos: ${e.patron_casos})` : ''}</td>
                      <td>{nombreCampana(e.campana_id)}</td>
                      <td>v{e.prompt_version}</td>
                      <td><code title={e.huella}>{e.huella.slice(0, 8)}</code></td>
                      <td>{ETIQUETA_ESTADO_EVALUACION[e.estado]}</td>
                      <td>
                        <span className={`insignia ${e.aprobada === true ? 'estado-activa' : e.aprobada === false ? 'insignia-error' : ''}`}>{textoAprobada(e)}</span>
                        {e.resumen.total !== undefined && ` ${e.resumen.aprobados ?? 0}/${e.resumen.total}`}
                      </td>
                      <td>{e.resumen.costo_usd !== undefined ? formatearUSD(e.resumen.costo_usd, 4) : '—'}</td>
                      <td>{formatearFechaHora(e.creado_en)}</td>
                      <td>
                        <button type="button" onClick={() => setSeleccion(e.id)}>
                          Ver detalle<span className="solo-lectura"> de la evaluación {e.id}</span>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
          </>
        )}
      </section>
      {seleccion !== null && <DetalleEvaluacion key={seleccion} id={seleccion} version={version} nombreCampana={nombreCampana} />}
    </section>
  );
}

function LanzarEvaluacion({ campanas, onLanzada }: { campanas: { id: number; nombre: string }[]; onLanzada: (e: EvaluacionIA) => void }) {
  const [campana, setCampana] = useState('');
  const [casos, setCasos] = useState('');
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState<'offline' | 'online' | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  async function lanzar(modo: 'offline' | 'online') {
    setError(null);
    setAviso(null);
    if (modo === 'online' && campana === '') {
      setErrLocal('Seleccione la campaña para la evaluación online.');
      return;
    }
    setErrLocal(undefined);
    setEnviando(modo);
    try {
      const e = await lanzarEvaluacion({
        modo, canal: 'chat', casos: casos.trim() || undefined, campana_id: modo === 'online' ? Number(campana) : undefined,
      });
      setAviso(`Evaluación ${modo === 'offline' ? 'offline' : 'online'} #${e.id} en cola.`);
      onLanzada(e);
    } catch (err) {
      setError(traducirErrorIA(comoErrorApi(err)));
    } finally {
      setEnviando(null);
    }
  }

  return (
    <section aria-labelledby="t-lanzar" className="tarjeta">
      <h2 id="t-lanzar">Lanzar una evaluación</h2>
      <div className="fila-campos">
        <Campo etiqueta="Campaña (solo evaluación online)" error={errLocal ?? error?.detalleDe('campana_id')}>
          {(p) => (
            <select {...p} value={campana} onChange={(e) => setCampana(e.target.value)}>
              <option value="">Seleccione una campaña…</option>
              {campanas.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Casos (patrón, opcional)" ayuda="Ejemplo: cobranza_*. Una evaluación con patrón nunca cuenta como aprobada para activar la IA." error={error?.detalleDe('casos')}>
          {(p) => <input {...p} type="text" maxLength={100} value={casos} onChange={(e) => setCasos(e.target.value)} />}
        </Campo>
      </div>
      <MensajeError error={error} camposMostrados={['campana_id', 'casos']} />
      {aviso && <p role="status" className="alerta alerta-ok">{aviso}</p>}
      <div className="acciones">
        <button type="button" className="primario" disabled={enviando !== null} onClick={() => void lanzar('offline')}>
          {enviando === 'offline' ? 'Lanzando…' : 'Lanzar offline'}
        </button>
        <button type="button" disabled={enviando !== null} onClick={() => void lanzar('online')}>
          {enviando === 'online' ? 'Lanzando…' : 'Lanzar online'}
        </button>
      </div>
    </section>
  );
}

function DetalleEvaluacion({ id, version, nombreCampana }: { id: number; version: number; nombreCampana: (id: number | null) => string }) {
  const cargador = useCallback(() => {
    void version;
    return obtenerEvaluacion(id);
  }, [id, version]);
  const { datos: e, cargando, error, recargar } = useCarga(cargador);
  const [soloFallidos, setSoloFallidos] = useState(false);

  return (
    <section aria-labelledby="t-eval-detalle" className="tarjeta">
      <h2 id="t-eval-detalle">Evaluación #{id}</h2>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !e && <Cargando />}
      {e && (
        <>
          <dl className="datos">
            <div><dt>Modo</dt><dd>{e.modo === 'offline' ? 'Offline' : 'Online'}</dd></div>
            <div><dt>Estado</dt><dd>{ETIQUETA_ESTADO_EVALUACION[e.estado]}</dd></div>
            <div><dt>Resultado</dt><dd>{textoAprobada(e)}</dd></div>
            <div><dt>Campaña</dt><dd>{nombreCampana(e.campana_id)}</dd></div>
            <div><dt>Modelo</dt><dd>{e.modelo ?? '—'}{e.esfuerzo ? ` (${e.esfuerzo})` : ''}</dd></div>
            <div><dt>Prompt</dt><dd>v{e.prompt_version}</dd></div>
            <div><dt>Huella</dt><dd><code>{e.huella}</code></dd></div>
            <div><dt>Casos aprobados</dt><dd>{e.resumen.total !== undefined ? `${e.resumen.aprobados ?? 0} de ${e.resumen.total}` : '—'}</dd></div>
            <div><dt>Coste</dt><dd>{e.resumen.costo_usd !== undefined ? formatearUSD(e.resumen.costo_usd, 4) : '—'}</dd></div>
            <div><dt>Iniciada por</dt><dd>{e.iniciada_por?.nombre ?? 'Línea de comandos'}</dd></div>
            <div><dt>Creada</dt><dd>{formatearFechaHora(e.creado_en)}</dd></div>
            <div><dt>Completada</dt><dd>{formatearFechaHora(e.completada_en)}</dd></div>
          </dl>
          {(e.estado === 'pendiente' || e.estado === 'en_curso') && <p role="status">La evaluación está {e.estado === 'pendiente' ? 'pendiente' : 'en curso'}: se actualizará sola al terminar.</p>}
          {e.estado === 'fallida' && <p role="alert" className="alerta alerta-error">La evaluación falló antes de terminar.</p>}
          {e.resumen.por_categoria && Object.keys(e.resumen.por_categoria).length > 0 && (
            <div className="tabla-scroll">
              <table>
                <caption className="solo-lectura">Resultado por categoría</caption>
                <thead><tr><th scope="col">Categoría</th><th scope="col">Aprobados</th><th scope="col">Total</th></tr></thead>
                <tbody>
                  {Object.entries(e.resumen.por_categoria).map(([k, v]) => (
                    <tr key={k}><th scope="row">{k}</th><td>{v.aprobados}</td><td>{v.total}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <h3>Casos</h3>
          {e.casos.length === 0 ? (
            <p>Sin resultados por caso todavía.</p>
          ) : (
            <>
              <label>
                <input type="checkbox" checked={soloFallidos} onChange={(ev) => setSoloFallidos(ev.target.checked)} /> Mostrar solo los fallidos
              </label>
              <div className="tabla-scroll">
                <table>
                  <caption className="solo-lectura">Resultado por caso</caption>
                  <thead><tr><th scope="col">Caso</th><th scope="col">Categoría</th><th scope="col">Resultado</th><th scope="col">Fallos</th></tr></thead>
                  <tbody>
                    {e.casos.filter((c) => !soloFallidos || !c.aprobado).map((c) => (
                      <tr key={c.id} className={c.aprobado ? undefined : 'fila-error'}>
                        <th scope="row"><code>{c.id}</code></th>
                        <td>{c.categoria}</td>
                        <td>{c.aprobado ? 'Aprobado' : <strong className="texto-error">Fallido</strong>}</td>
                        <td>
                          {c.fallos.length === 0 ? '—' : (
                            <ul className="lista-simple">{c.fallos.map((f, i) => <li key={i}>{f}</li>)}</ul>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
