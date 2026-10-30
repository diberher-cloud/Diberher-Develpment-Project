import { useCallback } from 'react';
import { obtenerUsoIA } from '../../api/endpoints';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { formatearEntero, formatearPorcentaje, formatearUSD } from '../../utilidades/ia';
import { useAgrupador } from '../../utilidades/useAgrupador';
import { useCarga } from '../../utilidades/useCarga';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

/** Uso y coste del modelo en la conversación (solo A/S): totales, tasa de caché y cada llamada. */
export function PanelUsoIA({ conversacionId: id, version = 0 }: { conversacionId: number; version?: number }) {
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return obtenerUsoIA(id);
  }, [id, version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const programar = useAgrupador<'uso'>(600, () => recargar());
  useEventoTiempoReal('ia.turno', (e) => {
    if (e.tipo === 'ia.turno' && e.datos.conversacion_id === id && e.datos.estado !== 'en_curso') programar('uso');
  });

  return (
    <section aria-labelledby="t-uso-ia" className="tarjeta">
      <h3 id="t-uso-ia">Uso y coste de la IA</h3>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && (
        <>
          <dl className="contadores" aria-label="Totales de uso">
            <div className="contador"><dt>Llamadas al modelo</dt><dd>{formatearEntero(datos.total.llamadas)}</dd></div>
            <div className="contador"><dt>Coste</dt><dd>{formatearUSD(datos.total.costo_usd, 4)}</dd></div>
            <div className="contador"><dt>Tokens de entrada</dt><dd>{formatearEntero(datos.total.input_tokens)}</dd></div>
            <div className="contador"><dt>Tokens de salida</dt><dd>{formatearEntero(datos.total.output_tokens)}</dd></div>
            <div className="contador"><dt>Caché leída</dt><dd>{formatearEntero(datos.total.cache_read_input_tokens)}</dd></div>
            <div className="contador"><dt>Caché escrita</dt><dd>{formatearEntero(datos.total.cache_creation_input_tokens)}</dd></div>
            <div className="contador"><dt>Aciertos de caché</dt><dd>{formatearPorcentaje(datos.total.tasa_cache)}</dd></div>
          </dl>
          {datos.llamadas.length === 0 ? (
            <p>Aún no hay llamadas al modelo.</p>
          ) : (
            <div className="tabla-scroll">
              <table>
                <caption className="solo-lectura">Llamadas al modelo</caption>
                <thead>
                  <tr>
                    <th scope="col">Hora</th><th scope="col">Iteración</th><th scope="col">Modelo</th><th scope="col">Parada</th>
                    <th scope="col">Entrada</th><th scope="col">Salida</th><th scope="col">Caché (leída)</th>
                    <th scope="col">Duración</th><th scope="col">Coste</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.llamadas.map((l) => (
                    <tr key={l.id}>
                      <th scope="row">{formatearFechaHora(l.creado_en)}</th>
                      <td>{l.iteracion}</td>
                      <td>{l.modelo_servido}{l.modelo_servido !== l.modelo ? ` (pedido: ${l.modelo})` : ''}</td>
                      <td>{l.stop_reason}</td>
                      <td>{formatearEntero(l.input_tokens)}</td>
                      <td>{formatearEntero(l.output_tokens)}</td>
                      <td>{formatearEntero(l.cache_read_input_tokens)}</td>
                      <td>{formatearEntero(l.duracion_ms)} ms</td>
                      <td>{formatearUSD(l.costo_usd, 6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
