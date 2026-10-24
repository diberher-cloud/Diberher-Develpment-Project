import { useCallback, useEffect, useRef, useState } from 'react';
import { listarAgentesSupervision } from '../api/endpoints';
import type { AgenteSupervision, EstadoAgenteValor, EstadoLlamada } from '../api/tipos';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import {
  ETIQUETA_ESTADO_AGENTE, ETIQUETA_ESTADO_LLAMADA, ETIQUETA_MOTIVO_PAUSA,
} from '../utilidades/consola';
import { formatearDuracion } from '../utilidades/formato';
import { useAhora } from '../utilidades/useAhora';
import { useCarga } from '../utilidades/useCarga';

const TERMINALES: EstadoLlamada[] = ['completada', 'ocupado', 'no_contesta', 'fallida', 'cancelada', 'bloqueada'];
const ORDEN_ESTADOS: EstadoAgenteValor[] = ['disponible', 'en_llamada', 'tipificando', 'pausa', 'desconectado'];

export function SupervisionAgentes() {
  const cargador = useCallback(() => listarAgentesSupervision(), []);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const { estado: conexion, reconexiones } = useConexionTiempoReal();
  const [agentes, setAgentes] = useState<AgenteSupervision[]>([]);
  const ahora = useAhora(1000);

  useEffect(() => {
    if (datos) setAgentes(datos);
  }, [datos]);
  // Al reconectar se recarga el estado autoritativo por REST.
  useEffect(() => {
    if (reconexiones > 0) recargar();
  }, [reconexiones, recargar]);

  useEventoTiempoReal('agente.estado', (e) => {
    if (e.tipo !== 'agente.estado') return;
    const d = e.datos;
    setAgentes((lista) =>
      lista.map((a) =>
        a.usuario_id === d.usuario_id
          ? { ...a, estado: d.estado, desde: d.desde, motivo_pausa: d.motivo_pausa, llamada: d.llamada_id === null ? null : a.llamada }
          : a,
      ),
    );
  });
  useEventoTiempoReal('llamada.estado', (e) => {
    if (e.tipo !== 'llamada.estado') return;
    const d = e.datos;
    const terminal = TERMINALES.includes(d.estado);
    setAgentes((lista) =>
      lista.map((a) => {
        if (a.usuario_id !== d.usuario_id) return a;
        if (terminal) return { ...a, llamada: null };
        const nombre = a.llamada?.campana_id === d.campana_id ? a.llamada.campana_nombre : undefined;
        return {
          ...a,
          llamada: { id: d.llamada_id, estado: d.estado, campana_id: d.campana_id, campana_nombre: nombre ?? `Campaña #${d.campana_id}` },
        };
      }),
    );
  });

  // Llamadas cuyo nombre de campaña aún se desconoce (el evento solo trae el id): se recarga por REST una vez por llamada.
  const recargadas = useRef(new Set<number>());
  useEffect(() => {
    const falta = agentes.find((a) => a.llamada && a.llamada.campana_nombre === `Campaña #${a.llamada.campana_id}`);
    if (falta?.llamada && !recargadas.current.has(falta.llamada.id)) {
      recargadas.current.add(falta.llamada.id);
      recargar();
    }
  }, [agentes, recargar]);

  const conteo = ORDEN_ESTADOS.map((s) => [s, agentes.filter((a) => a.estado === s).length] as const);

  return (
    <section aria-labelledby="t-sup">
      <div className="barra-titulo">
        <h1 id="t-sup">Supervisión de agentes</h1>
        <span className="ayuda">Tiempo real: {conexion === 'conectada' ? 'conectado' : conexion === 'cerrada' ? 'sin conexión' : 'reconectando…'}</span>
      </div>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && agentes.length === 0 && <p>No hay agentes activos.</p>}
      {agentes.length > 0 && (
        <>
          <dl className="contadores" aria-label="Agentes por estado">
            {conteo.map(([s, n]) => (
              <div key={s} className="contador"><dt>{ETIQUETA_ESTADO_AGENTE[s]}</dt><dd>{n}</dd></div>
            ))}
          </dl>
          <div className="tabla-scroll">
            <table>
              <caption className="solo-lectura">Estado de los agentes</caption>
              <thead>
                <tr>
                  <th scope="col">Agente</th><th scope="col">Estado</th><th scope="col">Tiempo en estado</th>
                  <th scope="col">Campañas asignadas</th><th scope="col">Llamada actual</th>
                </tr>
              </thead>
              <tbody>
                {agentes.map((a) => (
                  <tr key={a.usuario_id}>
                    <th scope="row">{a.nombre}</th>
                    <td>
                      <span className={`insignia agente-${a.estado}`}>{ETIQUETA_ESTADO_AGENTE[a.estado]}</span>
                      {a.motivo_pausa ? ` (${ETIQUETA_MOTIVO_PAUSA[a.motivo_pausa]})` : ''}
                    </td>
                    <td><time>{formatearDuracion((ahora - new Date(a.desde).getTime()) / 1000)}</time></td>
                    <td>{a.campanas.length}</td>
                    <td>
                      {a.llamada
                        ? `${a.llamada.campana_nombre}: ${ETIQUETA_ESTADO_LLAMADA[a.llamada.estado]}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
