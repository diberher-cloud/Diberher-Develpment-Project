import { useCallback, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  actualizarCampana, eliminarCampana, listarClientesCampana, listarImportaciones, obtenerCampana,
} from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Campana, EstadoCampana } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { CampanaAgentes } from '../componentes/CampanaAgentes';
import { ConfiguracionIACampana } from '../componentes/ia/ConfiguracionIACampana';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { ImportarClientes } from '../componentes/ImportarClientes';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { TipificacionesCampana } from '../componentes/TipificacionesCampana';
import { ETIQUETA_ACCION, ETIQUETA_ESTADO, ETIQUETA_TIPO, TRANSICIONES } from '../utilidades/campanas';
import { formatearCOP, formatearFecha, formatearFechaHora } from '../utilidades/formato';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';

type Pestana = 'clientes' | 'agentes' | 'tipificaciones' | 'ia';
const PESTANAS: [Pestana, string][] = [['clientes', 'Clientes'], ['agentes', 'Agentes'], ['tipificaciones', 'Tipificaciones'], ['ia', 'Agente IA']];

export function CampanaDetalle() {
  const id = Number(useParams().id);
  const { tieneRol } = useAuth();
  const gestiona = tieneRol('administrador', 'supervisor');
  const navegar = useNavigate();
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [version, setVersion] = useState(0);
  const [pestana, setPestana] = useState<Pestana>('clientes');

  const cargador = useCallback(() => obtenerCampana(id), [id]);
  const { datos: campana, cargando, error, recargar } = useCarga(cargador);

  async function cambiarEstado(estado: EstadoCampana) {
    setOcupado(true);
    setErrorAccion(null);
    try {
      await actualizarCampana(id, { estado });
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    } finally {
      setOcupado(false);
    }
  }

  async function eliminar(c: Campana) {
    if (!window.confirm(`¿Eliminar la campaña "${c.nombre}"? Se borrarán sus importaciones y clientes asociados.`)) return;
    setOcupado(true);
    setErrorAccion(null);
    try {
      await eliminarCampana(id);
      navegar('/campanas', { replace: true });
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
      setOcupado(false);
    }
  }

  function teclaPestana(e: KeyboardEvent) {
    const i = PESTANAS.findIndex(([c]) => c === pestana);
    let n = -1;
    if (e.key === 'ArrowRight') n = (i + 1) % PESTANAS.length;
    else if (e.key === 'ArrowLeft') n = (i + PESTANAS.length - 1) % PESTANAS.length;
    if (n < 0) return;
    e.preventDefault();
    setPestana(PESTANAS[n][0]);
    document.getElementById(`pestana-${PESTANAS[n][0]}`)?.focus();
  }

  if (cargando && !campana) return <Cargando />;
  if (error) return <MensajeError error={error} onReintentar={recargar} />;
  if (!campana) return null;

  const alImportar = () => {
    recargar();
    setVersion((v) => v + 1);
  };

  return (
    <section aria-labelledby="t-campana">
      <p><Link to="/campanas">← Campañas</Link></p>
      <div className="barra-titulo">
        <h1 id="t-campana">{campana.nombre}</h1>
        <span className={`insignia estado-${campana.estado}`}>{ETIQUETA_ESTADO[campana.estado]}</span>
      </div>

      <dl className="datos">
        <div><dt>Tipo</dt><dd>{ETIQUETA_TIPO[campana.tipo]}</dd></div>
        <div><dt>Inicio</dt><dd>{formatearFecha(campana.fecha_inicio)}</dd></div>
        <div><dt>Fin</dt><dd>{formatearFecha(campana.fecha_fin)}</dd></div>
        <div><dt>Máximo de intentos</dt><dd>{campana.max_intentos}</dd></div>
        <div><dt>Intervalo de reintento</dt><dd>{campana.intervalo_reintento_minutos} min</dd></div>
        <div><dt>WhatsApp</dt><dd>{campana.whatsapp_habilitado ? 'Habilitado' : 'No habilitado'}</dd></div>
        <div><dt>Clientes</dt><dd>{campana.total_clientes}</dd></div>
        <div><dt>Creada</dt><dd>{formatearFechaHora(campana.creado_en)}</dd></div>
      </dl>
      {campana.descripcion && <p>{campana.descripcion}</p>}
      {campana.guion && (
        <details>
          <summary>Guion</summary>
          <pre className="guion">{campana.guion}</pre>
        </details>
      )}

      {gestiona && (
        <div className="acciones" role="group" aria-label="Acciones de la campaña">
          {TRANSICIONES[campana.estado].map((destino) => (
            <button key={destino} type="button" disabled={ocupado} onClick={() => cambiarEstado(destino)}>
              {ETIQUETA_ACCION[destino]}
            </button>
          ))}
          {campana.estado !== 'finalizada' && (
            <Link to={`/campanas/${campana.id}/editar`} className="boton">Editar</Link>
          )}
          {campana.estado === 'borrador' && (
            <button type="button" className="peligro" disabled={ocupado} onClick={() => eliminar(campana)}>
              Eliminar
            </button>
          )}
        </div>
      )}
      <MensajeError error={errorAccion} />

      {gestiona && (
        <>
          <div role="tablist" aria-label="Secciones de la campaña" className="pestanas" onKeyDown={teclaPestana}>
            {PESTANAS.map(([clave, nombre]) => (
              <button
                key={clave}
                type="button"
                role="tab"
                id={`pestana-${clave}`}
                aria-selected={pestana === clave}
                aria-controls="panel-campana"
                tabIndex={pestana === clave ? 0 : -1}
                onClick={() => setPestana(clave)}
              >
                {nombre}
              </button>
            ))}
          </div>
          <div role="tabpanel" id="panel-campana" aria-labelledby={`pestana-${pestana}`}>
            {pestana === 'clientes' && (
              <>
                {campana.estado !== 'finalizada' && <ImportarClientes campanaId={id} onImportada={alImportar} />}
                <HistorialImportaciones campanaId={id} version={version} />
                <ClientesCampana campana={campana} version={version} />
              </>
            )}
            {pestana === 'agentes' && <CampanaAgentes campana={campana} />}
            {pestana === 'tipificaciones' && <TipificacionesCampana campanaId={id} />}
            {pestana === 'ia' && <ConfiguracionIACampana campana={campana} onIrAPestana={setPestana} />}
          </div>
        </>
      )}
    </section>
  );
}

function HistorialImportaciones({ campanaId, version }: { campanaId: number; version: number }) {
  const [page, setPage] = useState(1);
  const cargador = useCallback(() => {
    void version;
    return listarImportaciones(campanaId, { page, page_size: 10 });
  }, [campanaId, page, version]);
  const { datos, cargando, error, recargar } = useCarga(cargador);

  return (
    <section aria-labelledby="t-hist">
      <h2 id="t-hist">Historial de importaciones</h2>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && <p>Aún no se han realizado importaciones.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll">
            <table>
              <caption className="solo-lectura">Importaciones de la campaña</caption>
              <thead>
                <tr>
                  <th scope="col">Fecha</th><th scope="col">Archivo</th><th scope="col">Total</th>
                  <th scope="col">Importadas</th><th scope="col">Duplicadas</th><th scope="col">Inválidas</th>
                  <th scope="col">Excluidas</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((i) => (
                  <tr key={i.id}>
                    <th scope="row"><Link to={`/importaciones/${i.id}`}>{formatearFechaHora(i.creado_en)}</Link></th>
                    <td>{i.nombre_archivo}</td><td>{i.total_filas}</td><td>{i.filas_importadas}</td>
                    <td>{i.filas_duplicadas}</td><td>{i.filas_invalidas}</td><td>{i.filas_excluidas}</td>
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

function ClientesCampana({ campana, version }: { campana: Campana; version: number }) {
  const [busqueda, setBusqueda] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const cargador = useCallback(() => {
    void version;
    return listarClientesCampana(campana.id, { q, page, page_size: 20 });
  }, [campana.id, q, page, version]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const cobranza = campana.tipo === 'cobranza';

  return (
    <section aria-labelledby="t-clientes">
      <h2 id="t-clientes">Clientes de la campaña</h2>
      <form
        className="filtros"
        role="search"
        onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(busqueda.trim()); }}
      >
        <Campo etiqueta="Buscar por nombre, documento o teléfono">
          {(p) => <input {...p} type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />}
        </Campo>
        <button type="submit">Buscar</button>
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && <p>No hay clientes que mostrar.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Clientes de la campaña</caption>
              <thead>
                <tr>
                  <th scope="col">Nombre</th><th scope="col">Documento</th><th scope="col">Teléfonos</th>
                  {cobranza ? (
                    <>
                      <th scope="col">Obligación</th><th scope="col">Saldo total</th><th scope="col">Saldo en mora</th>
                      <th scope="col">Días de mora</th><th scope="col">Vencimiento</th>
                    </>
                  ) : (
                    <><th scope="col">Producto</th><th scope="col">Oferta</th></>
                  )}
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((c) => (
                  <tr key={c.id}>
                    <th scope="row">{c.cliente.nombre}</th>
                    <td>{c.cliente.tipo_documento} {c.cliente.numero_documento}</td>
                    <td>
                      <ul className="lista-simple">
                        {c.telefonos.map((t) => (
                          <li key={t.id}>
                            {t.numero_e164} ({t.tipo_linea})
                            {t.excluido && <span className="insignia insignia-error"> Excluido</span>}
                          </li>
                        ))}
                      </ul>
                    </td>
                    {cobranza ? (
                      <>
                        <td>{c.numero_obligacion ?? '—'}</td><td>{formatearCOP(c.saldo_total)}</td>
                        <td>{formatearCOP(c.saldo_mora)}</td><td>{c.dias_mora ?? '—'}</td>
                        <td>{formatearFecha(c.fecha_vencimiento)}</td>
                      </>
                    ) : (
                      <><td>{c.producto ?? '—'}</td><td>{c.oferta ?? '—'}</td></>
                    )}
                    <td>{c.estado}</td>
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
