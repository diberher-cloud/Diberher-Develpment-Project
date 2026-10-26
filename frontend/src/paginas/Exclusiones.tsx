import { useCallback, useState, type FormEvent } from 'react';
import {
  crearExclusion, eliminarExclusion, importarExclusiones, listarExclusiones,
} from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { AplicaA, CanalExclusion, MotivoExclusion, ResultadoImportacionExclusiones } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { TablaErroresImportacion, Contador } from '../componentes/ResumenImportacion';
import { SelectorCsv } from '../componentes/SelectorCsv';
import { formatearFechaHora } from '../utilidades/formato';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';

const MOTIVOS: Record<MotivoExclusion, string> = {
  rne: 'Registro de Números Excluidos (RNE)',
  solicitud_titular: 'Solicitud del titular',
  numero_errado: 'Número errado',
  manual: 'Manual',
};
const APLICA: Record<AplicaA, string> = { venta: 'Venta', cobranza: 'Cobranza', todas: 'Todas' };
const CANALES: Record<CanalExclusion, string> = { todos: 'Todos los canales', voz: 'Solo voz', whatsapp: 'Solo WhatsApp' };

function OpcionesMotivo() {
  return (
    <>
      {(Object.keys(MOTIVOS) as MotivoExclusion[]).map((m) => (
        <option key={m} value={m}>{MOTIVOS[m]}</option>
      ))}
    </>
  );
}
function OpcionesAplica() {
  return (
    <>
      {(Object.keys(APLICA) as AplicaA[]).map((a) => (
        <option key={a} value={a}>{APLICA[a]}</option>
      ))}
    </>
  );
}

function OpcionesCanal() {
  return (
    <>
      {(Object.keys(CANALES) as CanalExclusion[]).map((c) => (
        <option key={c} value={c}>{CANALES[c]}</option>
      ))}
    </>
  );
}

export function Exclusiones() {
  const [busqueda, setBusqueda] = useState('');
  const [q, setQ] = useState('');
  const [motivo, setMotivo] = useState<MotivoExclusion | ''>('');
  const [aplicaA, setAplicaA] = useState<AplicaA | ''>('');
  const [canal, setCanal] = useState<CanalExclusion | ''>('');
  const [page, setPage] = useState(1);
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);

  const cargador = useCallback(
    () => listarExclusiones({ q, motivo, aplica_a: aplicaA, canal, page, page_size: 20 }),
    [q, motivo, aplicaA, canal, page],
  );
  const { datos, cargando, error, recargar } = useCarga(cargador);

  async function eliminar(id: number, numero: string) {
    if (!window.confirm(`¿Eliminar la exclusión de ${numero}?`)) return;
    setErrorAccion(null);
    try {
      await eliminarExclusion(id);
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
  }

  return (
    <section aria-labelledby="t-excl">
      <h1 id="t-excl">Exclusiones de números</h1>

      <FormularioAlta onCreada={recargar} />
      <CargaMasiva onCargada={recargar} />

      <h2>Listado</h2>
      <form className="filtros" role="search" onSubmit={(e) => { e.preventDefault(); setPage(1); setQ(busqueda.trim()); }}>
        <Campo etiqueta="Buscar por teléfono">
          {(p) => <input {...p} type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Filtrar por motivo">
          {(p) => (
            <select {...p} value={motivo} onChange={(e) => { setPage(1); setMotivo(e.target.value as MotivoExclusion | ''); }}>
              <option value="">Todos</option>
              <OpcionesMotivo />
            </select>
          )}
        </Campo>
        <Campo etiqueta="Filtrar por aplicación">
          {(p) => (
            <select {...p} value={aplicaA} onChange={(e) => { setPage(1); setAplicaA(e.target.value as AplicaA | ''); }}>
              <option value="">Todas</option>
              <OpcionesAplica />
            </select>
          )}
        </Campo>
        <Campo etiqueta="Filtrar por canal">
          {(p) => (
            <select {...p} value={canal} onChange={(e) => { setPage(1); setCanal(e.target.value as CanalExclusion | ''); }}>
              <option value="">Todos</option>
              <OpcionesCanal />
            </select>
          )}
        </Campo>
        <button type="submit">Buscar</button>
      </form>

      <MensajeError error={errorAccion} />
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay exclusiones que coincidan.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Números excluidos</caption>
              <thead>
                <tr>
                  <th scope="col">Teléfono</th><th scope="col">Motivo</th><th scope="col">Aplica a</th><th scope="col">Canal</th>
                  <th scope="col">Observación</th><th scope="col">Creada</th><th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((x) => (
                  <tr key={x.id}>
                    <th scope="row">{x.numero_e164}</th>
                    <td>{MOTIVOS[x.motivo]}</td><td>{APLICA[x.aplica_a]}</td><td>{CANALES[x.canal] ?? '—'}</td>
                    <td>{x.observacion ?? '—'}</td><td>{formatearFechaHora(x.creado_en)}</td>
                    <td>
                      <button type="button" className="peligro" onClick={() => eliminar(x.id, x.numero_e164)}>
                        Eliminar<span className="solo-lectura"> {x.numero_e164}</span>
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

const CAMPOS_ALTA = ['telefono', 'motivo', 'aplica_a', 'canal', 'observacion'];

function FormularioAlta({ onCreada }: { onCreada: () => void }) {
  const [telefono, setTelefono] = useState('');
  const [motivo, setMotivo] = useState<MotivoExclusion>('manual');
  const [aplicaA, setAplicaA] = useState<AplicaA>('todas');
  const [canal, setCanal] = useState<CanalExclusion>('todos');
  const [observacion, setObservacion] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  function cambiarMotivo(m: MotivoExclusion) {
    setMotivo(m);
    if (m === 'rne') setAplicaA('venta'); // valor por defecto del RNE (§4.7)
  }

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    setEnviando(true);
    try {
      const x = await crearExclusion({
        telefono: telefono.trim(), motivo, aplica_a: aplicaA, observacion: observacion.trim() || null,
        ...(canal !== 'todos' ? { canal } : {}),
      });
      setOk(`Número ${x.numero_e164} excluido.`);
      setTelefono('');
      setObservacion('');
      onCreada();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-alta">
      <h2 id="t-alta">Agregar número</h2>
      <form onSubmit={enviar} noValidate className="formulario">
        <Campo etiqueta="Teléfono" error={error?.detalleDe('telefono')} ayuda="Cualquier formato, p. ej. 300 123 4567.">
          {(p) => <input {...p} value={telefono} onChange={(e) => setTelefono(e.target.value)} inputMode="tel" required />}
        </Campo>
        <div className="fila-campos">
          <Campo etiqueta="Motivo" error={error?.detalleDe('motivo')}>
            {(p) => (
              <select {...p} value={motivo} onChange={(e) => cambiarMotivo(e.target.value as MotivoExclusion)}>
                <OpcionesMotivo />
              </select>
            )}
          </Campo>
          <Campo etiqueta="Aplica a" error={error?.detalleDe('aplica_a')}>
            {(p) => (
              <select {...p} value={aplicaA} onChange={(e) => setAplicaA(e.target.value as AplicaA)}>
                <OpcionesAplica />
              </select>
            )}
          </Campo>
        </div>
        <Campo etiqueta="Canal" error={error?.detalleDe('canal')} ayuda="Una exclusión por canal solo bloquea ese medio.">
          {(p) => (
            <select {...p} value={canal} onChange={(e) => setCanal(e.target.value as CanalExclusion)}>
              <OpcionesCanal />
            </select>
          )}
        </Campo>
        <Campo etiqueta="Observación (opcional)" error={error?.detalleDe('observacion')}>
          {(p) => <input {...p} value={observacion} maxLength={300} onChange={(e) => setObservacion(e.target.value)} />}
        </Campo>
        <MensajeError error={error} camposMostrados={CAMPOS_ALTA} />
        {ok && <p role="status" className="alerta alerta-ok">{ok}</p>}
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Guardando…' : 'Agregar'}</button>
      </form>
    </section>
  );
}

function CargaMasiva({ onCargada }: { onCargada: () => void }) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [clave, setClave] = useState(0);
  const [motivo, setMotivo] = useState<MotivoExclusion>('rne');
  const [aplicaA, setAplicaA] = useState<AplicaA>('venta');
  const [canal, setCanal] = useState<CanalExclusion>('todos');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacionExclusiones | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (!archivo) return;
    setError(null);
    setResultado(null);
    setEnviando(true);
    try {
      setResultado(await importarExclusiones(archivo, motivo, aplicaA, canal));
      setArchivo(null);
      setClave((c) => c + 1);
      onCargada();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-masiva">
      <h2 id="t-masiva">Carga masiva desde CSV</h2>
      <form onSubmit={enviar} className="formulario">
        <SelectorCsv etiqueta="Archivo CSV de exclusiones (columna telefono)" archivo={archivo} onCambiar={setArchivo} clave={clave} />
        <div className="fila-campos">
          <Campo etiqueta="Motivo de la carga" error={error?.detalleDe('motivo')}>
            {(p) => (
              <select {...p} value={motivo} onChange={(e) => { const m = e.target.value as MotivoExclusion; setMotivo(m); if (m === 'rne') setAplicaA('venta'); }}>
                <OpcionesMotivo />
              </select>
            )}
          </Campo>
          <Campo etiqueta="Aplica a (carga)" error={error?.detalleDe('aplica_a')}>
            {(p) => (
              <select {...p} value={aplicaA} onChange={(e) => setAplicaA(e.target.value as AplicaA)}>
                <OpcionesAplica />
              </select>
            )}
          </Campo>
        </div>
        <Campo etiqueta="Canal (carga)" error={error?.detalleDe('canal')}>
          {(p) => (
            <select {...p} value={canal} onChange={(e) => setCanal(e.target.value as CanalExclusion)}>
              <OpcionesCanal />
            </select>
          )}
        </Campo>
        <MensajeError error={error} camposMostrados={['motivo', 'aplica_a', 'canal']} />
        <button type="submit" className="primario" disabled={!archivo || enviando}>{enviando ? 'Cargando…' : 'Cargar'}</button>
      </form>
      {resultado && (
        <div role="status" className="alerta alerta-ok">
          <h3>Resultado de la carga</h3>
          <dl className="contadores" aria-label="Resumen de la carga masiva">
            <Contador etiqueta="Total de filas" valor={resultado.total_filas} />
            <Contador etiqueta="Creadas" valor={resultado.creadas} />
            <Contador etiqueta="Duplicadas" valor={resultado.duplicadas} />
            <Contador etiqueta="Inválidas" valor={resultado.invalidas} />
          </dl>
          {resultado.errores_truncados && <p>Se muestran solo los primeros errores.</p>}
          <TablaErroresImportacion errores={resultado.errores} />
        </div>
      )}
    </section>
  );
}
