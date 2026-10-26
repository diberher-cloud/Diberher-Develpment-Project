import { useCallback, useEffect } from 'react';
import { obtenerEstadoTrabajos } from '../api/endpoints';
import { useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../utilidades/formato';
import { useCarga } from '../utilidades/useCarga';
import { Cargando } from './Cargando';
import { MensajeError } from './MensajeError';

const REFRESCO_MS = 30_000;

/** Estado del worker y de la cola de trabajos (supervisión). Avisa si no hay un trabajador activo. */
export function TarjetaWorker() {
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void reconexiones;
    return obtenerEstadoTrabajos();
  }, [reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);

  useEventoTiempoReal('trabajo.fallido', recargar);
  useEffect(() => {
    const id = setInterval(recargar, REFRESCO_MS);
    return () => clearInterval(id);
  }, [recargar]);

  const valido = datos && Array.isArray(datos.trabajadores) && Array.isArray(datos.por_estado) && Array.isArray(datos.fallidos_recientes);
  const activos = valido ? datos.trabajadores.filter((t) => t.activo).length : 0;
  const pendientes = valido ? datos.por_estado.filter((x) => x.estado === 'pendiente').reduce((n, x) => n + x.total, 0) : 0;
  return (
    <section aria-labelledby="t-worker" className="tarjeta">
      <h2 id="t-worker">Worker de trabajos en segundo plano</h2>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {valido && (
        <>
          {activos === 0 ? (
            <p role="alert" className="alerta alerta-error">
              No hay un trabajador activo: los mensajes de WhatsApp no se envían ni se procesan.
              {pendientes > 0 ? ` Hay ${pendientes} trabajos pendientes.` : ''}
            </p>
          ) : (
            <p role="status" className="alerta alerta-ok">
              {activos === 1 ? '1 trabajador activo' : `${activos} trabajadores activos`}. Trabajos pendientes: {pendientes}.
            </p>
          )}
          {datos.trabajadores.length > 0 && (
            <ul className="lista-simple" aria-label="Trabajadores">
              {datos.trabajadores.map((t) => (
                <li key={t.trabajador}>
                  {t.trabajador}: {t.activo ? 'activo' : 'sin latido reciente'} (último latido {formatearFechaHora(t.ultimo_latido)})
                </li>
              ))}
            </ul>
          )}
          {datos.por_estado.length > 0 && (
            <div className="tabla-scroll">
              <table>
                <caption className="solo-lectura">Trabajos por tipo y estado</caption>
                <thead>
                  <tr><th scope="col">Tipo</th><th scope="col">Estado</th><th scope="col">Total</th></tr>
                </thead>
                <tbody>
                  {datos.por_estado.map((x) => (
                    <tr key={`${x.tipo}-${x.estado}`}>
                      <th scope="row">{x.tipo}</th><td>{x.estado}</td><td>{x.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {datos.fallidos_recientes.length > 0 && (
            <>
              <h3>Fallidos en las últimas 24 h</h3>
              <div className="tabla-scroll">
                <table>
                  <caption className="solo-lectura">Trabajos fallidos recientes</caption>
                  <thead>
                    <tr><th scope="col">Tipo</th><th scope="col">Error</th><th scope="col">Intentos</th><th scope="col">Actualizado</th></tr>
                  </thead>
                  <tbody>
                    {datos.fallidos_recientes.map((f) => (
                      <tr key={f.id}>
                        <th scope="row">{f.tipo}</th><td>{f.ultimo_error ?? '—'}</td><td>{f.intentos}</td><td>{formatearFechaHora(f.actualizado_en)}</td>
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
