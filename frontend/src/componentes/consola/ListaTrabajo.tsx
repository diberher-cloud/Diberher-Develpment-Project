import { useCallback, useState } from 'react';
import { listarRegistrosConsola } from '../../api/endpoints';
import type { CampanaConsola } from '../../api/tipos';
import { ETIQUETA_TIPO } from '../../utilidades/campanas';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { formatearCOP, formatearFechaHora } from '../../utilidades/formato';
import { useCarga } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { Paginador } from '../Paginador';

interface Props {
  campanas: CampanaConsola[];
  /** Cambia cuando hay que recargar la lista (evento `consola.registro`, reconexión, acciones propias). */
  version: number;
  bloqueado: boolean;
  onTomar: (registroId: number) => void;
}

export function ListaTrabajo({ campanas, version, bloqueado, onTomar }: Props) {
  const [campanaId, setCampanaId] = useState<number | ''>('');
  const [page, setPage] = useState(1);
  const cargador = useCallback(() => {
    void version;
    return listarRegistrosConsola({ campana_id: campanaId, page, page_size: 10 });
  }, [campanaId, page, version]);
  const { datos, cargando, error, recargar } = useCarga(cargador);

  return (
    <section aria-labelledby="t-lista" className="tarjeta">
      <h2 id="t-lista">Lista de trabajo</h2>
      {campanas.length === 0 ? (
        <p>No tiene campañas activas asignadas.</p>
      ) : (
        <ul className="lista-simple" aria-label="Campañas asignadas">
          {campanas.map((c) => (
            <li key={c.id}>
              {c.nombre} ({ETIQUETA_TIPO[c.tipo]}): {c.pendientes} pendiente(s)
            </li>
          ))}
        </ul>
      )}
      <div className="filtros">
        <Campo etiqueta="Campaña">
          {(p) => (
            <select
              {...p}
              value={campanaId}
              onChange={(e) => {
                setPage(1);
                setCampanaId(e.target.value ? Number(e.target.value) : '');
              }}
            >
              <option value="">Todas</option>
              {campanas.map((c) => (
                <option key={c.id} value={c.id}>{c.nombre}</option>
              ))}
            </select>
          )}
        </Campo>
      </div>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && <p>No hay registros disponibles en este momento.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Registros disponibles para gestionar</caption>
              <thead>
                <tr>
                  <th scope="col">Cliente</th><th scope="col">Campaña</th><th scope="col">Intentos</th>
                  <th scope="col">Último resultado</th><th scope="col">Saldo en mora</th>
                  <th scope="col">Próximo intento</th><th scope="col">Acción</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">
                      {r.nombre_cliente}
                      {r.reservado_por_mi && <span className="insignia"> Reservado por mí</span>}
                    </th>
                    <td>{r.campana_nombre} ({ETIQUETA_TIPO[r.tipo_campana]})</td>
                    <td>{r.intentos} de {r.max_intentos}</td>
                    <td>{r.ultimo_resultado ? ETIQUETA_RESULTADO[r.ultimo_resultado] : '—'}</td>
                    <td>{r.tipo_campana === 'cobranza' ? formatearCOP(r.saldo_mora) : (r.producto ?? '—')}</td>
                    <td>{formatearFechaHora(r.proximo_intento_en)}</td>
                    <td>
                      <button type="button" disabled={bloqueado} onClick={() => onTomar(r.id)}>
                        {r.reservado_por_mi ? 'Retomar' : 'Tomar'}
                        <span className="solo-lectura"> registro de {r.nombre_cliente}</span>
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
  );
}
