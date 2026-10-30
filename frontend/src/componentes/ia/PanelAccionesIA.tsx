import { useCallback } from 'react';
import { listarAccionesIA } from '../../api/endpoints';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { ETIQUETA_EFECTO, entradaEnmascarada, resumirResultado } from '../../utilidades/ia';
import { useAgrupador } from '../../utilidades/useAgrupador';
import { useCarga } from '../../utilidades/useCarga';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

interface Props {
  conversacionId: number;
  /** Empieza desplegado (supervisión) o plegado (bandeja). */
  abierto?: boolean;
  /** Cambia para forzar una recarga (p. ej. tras una acción del usuario). */
  version?: number;
}

/**
 * Acciones de la IA en la conversación (herramientas llamadas). Las entradas llegan enmascaradas del servidor; los
 * textos se pintan siempre como texto. Se actualiza por `ia.accion` (el evento no trae datos: se recarga por REST).
 */
export function PanelAccionesIA({ conversacionId: id, abierto = false, version = 0 }: Props) {
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return listarAccionesIA(id);
  }, [id, version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const programar = useAgrupador<'acciones'>(400, () => recargar());
  useEventoTiempoReal('ia.accion', (e) => {
    if (e.tipo === 'ia.accion' && e.datos.conversacion_id === id) programar('acciones');
  });

  return (
    <details className="tarjeta panel-acciones-ia" open={abierto}>
      <summary>Acciones de la IA{datos ? ` (${datos.length})` : ''}</summary>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.length === 0 && <p>La IA aún no ha ejecutado acciones en esta conversación.</p>}
      {datos && datos.length > 0 && (
        <div className="tabla-scroll" aria-live="polite">
          <table>
            <caption className="solo-lectura">Acciones de la IA en la conversación</caption>
            <thead>
              <tr>
                <th scope="col">Hora</th><th scope="col">Herramienta</th><th scope="col">Entrada</th>
                <th scope="col">Resultado</th><th scope="col">Efecto</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((a) => (
                <tr key={a.id} className={a.es_error ? 'fila-error' : undefined}>
                  <th scope="row">{formatearFechaHora(a.creado_en)}</th>
                  <td><code>{a.herramienta}</code></td>
                  <td><code>{entradaEnmascarada(a.entrada)}</code></td>
                  <td>
                    {a.es_error && <strong className="texto-error">Error{a.codigo_error ? ` ${a.codigo_error}` : ''}. </strong>}
                    <code>{resumirResultado(a.resultado)}</code>
                  </td>
                  <td>{ETIQUETA_EFECTO[a.efecto] ?? a.efecto}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}
