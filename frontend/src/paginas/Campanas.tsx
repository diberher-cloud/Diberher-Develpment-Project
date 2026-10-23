import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { listarCampanas } from '../api/endpoints';
import type { EstadoCampana, TipoCampana } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { ETIQUETA_ESTADO, ETIQUETA_TIPO } from '../utilidades/campanas';
import { formatearFecha } from '../utilidades/formato';
import { useCarga } from '../utilidades/useCarga';

const TAM = 20;

export function Campanas() {
  const { tieneRol } = useAuth();
  const gestiona = tieneRol('administrador', 'supervisor');
  const [estado, setEstado] = useState<EstadoCampana | ''>('');
  const [tipo, setTipo] = useState<TipoCampana | ''>('');
  const [busqueda, setBusqueda] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);

  const cargador = useCallback(
    () => listarCampanas({ estado: gestiona ? estado : 'activa', tipo, q, page, page_size: TAM }),
    [gestiona, estado, tipo, q, page],
  );
  const { datos, cargando, error, recargar } = useCarga(cargador);

  return (
    <section aria-labelledby="t-campanas">
      <div className="barra-titulo">
        <h1 id="t-campanas">Campañas</h1>
        {gestiona && (
          <Link to="/campanas/nueva" className="boton primario">
            Nueva campaña
          </Link>
        )}
      </div>
      {!gestiona && <p>Se muestran únicamente las campañas activas.</p>}

      <form
        className="filtros"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQ(busqueda.trim());
        }}
      >
        <Campo etiqueta="Buscar por nombre">
          {(p) => <input {...p} type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />}
        </Campo>
        {gestiona && (
          <Campo etiqueta="Estado">
            {(p) => (
              <select {...p} value={estado} onChange={(e) => { setPage(1); setEstado(e.target.value as EstadoCampana | ''); }}>
                <option value="">Todos</option>
                {(Object.keys(ETIQUETA_ESTADO) as EstadoCampana[]).map((k) => (
                  <option key={k} value={k}>{ETIQUETA_ESTADO[k]}</option>
                ))}
              </select>
            )}
          </Campo>
        )}
        <Campo etiqueta="Tipo">
          {(p) => (
            <select {...p} value={tipo} onChange={(e) => { setPage(1); setTipo(e.target.value as TipoCampana | ''); }}>
              <option value="">Todos</option>
              <option value="venta">Venta</option>
              <option value="cobranza">Cobranza</option>
            </select>
          )}
        </Campo>
        <button type="submit">Buscar</button>
      </form>

      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay campañas que coincidan con los filtros.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Listado de campañas</caption>
              <thead>
                <tr>
                  <th scope="col">Nombre</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Inicio</th>
                  <th scope="col">Fin</th>
                  <th scope="col">Clientes</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((c) => (
                  <tr key={c.id}>
                    <th scope="row">
                      <Link to={`/campanas/${c.id}`}>{c.nombre}</Link>
                    </th>
                    <td>{ETIQUETA_TIPO[c.tipo]}</td>
                    <td><span className={`insignia estado-${c.estado}`}>{ETIQUETA_ESTADO[c.estado]}</span></td>
                    <td>{formatearFecha(c.fecha_inicio)}</td>
                    <td>{formatearFecha(c.fecha_fin)}</td>
                    <td>{c.total_clientes}</td>
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
