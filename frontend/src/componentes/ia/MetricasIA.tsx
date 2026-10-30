import { useCallback, useState } from 'react';
import { listarCampanas, obtenerMetricasIA } from '../../api/endpoints';
import { useConexionTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { ETIQUETA_MOTIVO_COLA } from '../../utilidades/whatsapp';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { formatearCOP, formatearFecha } from '../../utilidades/formato';
import { formatearEntero, formatearPorcentaje, formatearSegundos, formatearUSD } from '../../utilidades/ia';
import { useCarga } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import type { MotivoCola, ResultadoTipificacion } from '../../api/tipos';

/** Métricas agregadas de la IA por campaña y rango de fechas (por defecto, hoy). */
export function MetricasIA() {
  const { reconexiones } = useConexionTiempoReal();
  const [campana, setCampana] = useState('');
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const cargador = useCallback(() => {
    void reconexiones;
    return obtenerMetricasIA({ campana_id: campana === '' ? '' : Number(campana), desde, hasta });
  }, [campana, desde, hasta, reconexiones]);
  const { datos: m, cargando, error, recargar } = useCarga(cargador);
  const cargadorCampanas = useCallback(() => listarCampanas({ page_size: 100 }), []);
  const { datos: campanas } = useCarga(cargadorCampanas);

  const derivaciones = Object.entries(m?.derivaciones ?? {}) as [MotivoCola, number][];
  const totalDeriv = derivaciones.reduce((n, [, v]) => n + v, 0);
  const resultados = Object.entries(m?.resultados ?? {}) as [ResultadoTipificacion, number][];
  return (
    <section aria-labelledby="t-metricas-ia" className="tarjeta">
      <h2 id="t-metricas-ia">Métricas de la IA</h2>
      <form className="filtros" role="search" aria-label="Filtros de métricas" onSubmit={(e) => e.preventDefault()}>
        <Campo etiqueta="Campaña de las métricas">
          {(p) => (
            <select {...p} value={campana} onChange={(e) => setCampana(e.target.value)}>
              <option value="">Todas las campañas</option>
              {(campanas?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Desde">
          {(p) => <input {...p} type="date" value={desde} max={hasta || undefined} onChange={(e) => setDesde(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Hasta">
          {(p) => <input {...p} type="date" value={hasta} min={desde || undefined} onChange={(e) => setHasta(e.target.value)} />}
        </Campo>
        <button type="button" onClick={recargar}>Actualizar métricas</button>
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !m && <Cargando />}
      {m && (
        <div aria-busy={cargando}>
          <p className="ayuda">Del {formatearFecha(m.desde)} al {formatearFecha(m.hasta)}.</p>
          <dl className="contadores" aria-label="Métricas de la IA">
            <div className="contador"><dt>Conversaciones</dt><dd>{formatearEntero(m.conversaciones)}</dd></div>
            <div className="contador"><dt>Identidad verificada</dt><dd>{formatearEntero(m.con_identidad_verificada)} ({formatearPorcentaje(m.tasa_verificacion)})</dd></div>
            <div className="contador"><dt>Acuerdos de pago</dt><dd>{formatearEntero(m.acuerdos.numero)}</dd><dd className="ayuda">{formatearCOP(m.acuerdos.monto_total)}</dd></div>
            <div className="contador"><dt>Ventas</dt><dd>{formatearEntero(m.ventas.numero)}</dd><dd className="ayuda">{formatearCOP(m.ventas.valor_total)}</dd></div>
            <div className="contador"><dt>Traspasos a humano</dt><dd>{formatearEntero(totalDeriv)}</dd></div>
            <div className="contador"><dt>Bajas (opt-out)</dt><dd>{formatearEntero(m.opt_outs)}</dd></div>
            <div className="contador"><dt>Cerradas por la IA</dt><dd>{formatearEntero(m.cerradas_por_ia)}</dd></div>
            <div className="contador"><dt>Cerradas por inactividad</dt><dd>{formatearEntero(m.cerradas_por_inactividad)}</dd></div>
            <div className="contador"><dt>Coste total</dt><dd>{formatearUSD(m.costo_usd)}</dd></div>
            <div className="contador"><dt>Coste por acuerdo</dt><dd>{formatearUSD(m.costo_por_acuerdo_usd, 4)}</dd></div>
            <div className="contador"><dt>Aciertos de caché</dt><dd>{formatearPorcentaje(m.tasa_cache)}</dd></div>
            <div className="contador"><dt>Respuesta p50 / p95</dt><dd>{formatearSegundos(m.tiempo_respuesta_ms.p50)} / {formatearSegundos(m.tiempo_respuesta_ms.p95)}</dd></div>
          </dl>
          {(derivaciones.length > 0 || resultados.length > 0 || Object.keys(m.errores).length > 0 || Object.keys(m.guardas).length > 0) && (
            <details>
              <summary>Detalle de resultados, traspasos, errores y guardas</summary>
              {resultados.length > 0 && (
                <p>Resultados: {resultados.map(([k, v]) => `${ETIQUETA_RESULTADO[k] ?? k}: ${v}`).join(' · ')}.</p>
              )}
              {derivaciones.length > 0 && (
                <p>Traspasos: {derivaciones.map(([k, v]) => `${ETIQUETA_MOTIVO_COLA[k] ?? k}: ${v}`).join(' · ')}.</p>
              )}
              {Object.keys(m.errores).length > 0 && (
                <p>Errores del proveedor: {Object.entries(m.errores).map(([k, v]) => `${k}: ${v}`).join(' · ')}.</p>
              )}
              {Object.keys(m.guardas).length > 0 && (
                <p>Guardas activadas: {Object.entries(m.guardas).map(([k, v]) => `${k}: ${v}`).join(' · ')}.</p>
              )}
            </details>
          )}
        </div>
      )}
    </section>
  );
}
