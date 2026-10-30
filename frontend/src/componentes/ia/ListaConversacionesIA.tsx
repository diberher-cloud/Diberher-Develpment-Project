import { useCallback, useEffect, useState } from 'react';
import { listarCampanas, listarConversacionesIA } from '../../api/endpoints';
import type { AtendidaPor, EstadoConversacion, Usuario } from '../../api/tipos';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { formatearUSD } from '../../utilidades/ia';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { useAgrupador } from '../../utilidades/useAgrupador';
import { useCarga } from '../../utilidades/useCarga';
import { ETIQUETA_ATENDIDA_POR, numeroVisible } from '../../utilidades/whatsapp';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { Paginador } from '../Paginador';

interface Props {
  usuario: Usuario;
  seleccionada: number | null;
  onSeleccionar: (id: number) => void;
  /** Cambia cuando otra parte de la página modificó conversaciones (fuerza recarga). */
  version?: number;
}

/** Conversaciones que alguna vez atendió la IA, con actualización en vivo por `ia.turno`, `ia.accion` y mensajes. */
export function ListaConversacionesIA({ usuario, seleccionada, onSeleccionar, version = 0 }: Props) {
  const { reconexiones } = useConexionTiempoReal();
  const [campana, setCampana] = useState('');
  const [estado, setEstado] = useState<EstadoConversacion | ''>('abierta');
  const [atendida, setAtendida] = useState<AtendidaPor>('ia');
  const [gestion, setGestion] = useState<'' | 'con' | 'sin'>('');
  const [identidad, setIdentidad] = useState<'' | 'verificada' | 'no_verificada'>('');
  const [page, setPage] = useState(1);
  // Indicador de turno en curso según `ia.turno`; se descarta al llegar datos nuevos del servidor.
  const [enCurso, setEnCurso] = useState<Record<number, boolean>>({});

  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return listarConversacionesIA({
      page, page_size: 20, estado, atendida_por: atendida, campana_id: campana === '' ? '' : Number(campana),
      con_gestion: gestion === '' ? '' : gestion === 'con', identidad,
    });
  }, [page, estado, atendida, campana, gestion, identidad, version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  useEffect(() => {
    setEnCurso({});
  }, [datos]);
  const cargadorCampanas = useCallback(() => listarCampanas({ page_size: 100 }), []);
  const { datos: campanas } = useCarga(cargadorCampanas);

  const programar = useAgrupador<'lista'>(800, () => recargar());
  useEventoTiempoReal(['ia.turno', 'ia.accion', 'conversacion.mensaje', 'conversacion.estado'], (e) => {
    if (e.tipo === 'ia.turno') {
      const id = e.datos.conversacion_id;
      if (id === null) return;
      setEnCurso((m) => ({ ...m, [id]: e.datos.estado === 'en_curso' }));
      if (e.datos.estado !== 'en_curso') programar('lista');
    } else if (e.tipo === 'ia.accion' || e.tipo === 'conversacion.estado') {
      programar('lista');
    } else if (e.tipo === 'conversacion.mensaje' && e.datos.accion === 'nuevo') {
      programar('lista');
    }
  });

  return (
    <section aria-labelledby="t-lista-ia" className="tarjeta">
      <h2 id="t-lista-ia">Conversaciones con IA</h2>
      <form className="filtros" role="search" aria-label="Filtros de conversaciones con IA" onSubmit={(e) => e.preventDefault()}>
        <Campo etiqueta="Campaña">
          {(p) => (
            <select {...p} value={campana} onChange={(e) => { setPage(1); setCampana(e.target.value); }}>
              <option value="">Todas</option>
              {(campanas?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Estado">
          {(p) => (
            <select {...p} value={estado} onChange={(e) => { setPage(1); setEstado(e.target.value as EstadoConversacion | ''); }}>
              <option value="abierta">Abiertas</option>
              <option value="cerrada">Cerradas</option>
              <option value="">Todas</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Atendida por">
          {(p) => (
            <select {...p} value={atendida} onChange={(e) => { setPage(1); setAtendida(e.target.value as AtendidaPor); }}>
              <option value="ia">Agente IA</option>
              <option value="humano">Agente humano</option>
              <option value="sin_asignar">Sin asignar</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Gestión registrada">
          {(p) => (
            <select {...p} value={gestion} onChange={(e) => { setPage(1); setGestion(e.target.value as '' | 'con' | 'sin'); }}>
              <option value="">Todas</option>
              <option value="con">Con gestión</option>
              <option value="sin">Sin gestión</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Identidad">
          {(p) => (
            <select {...p} value={identidad} onChange={(e) => { setPage(1); setIdentidad(e.target.value as '' | 'verificada' | 'no_verificada'); }}>
              <option value="">Todas</option>
              <option value="verificada">Verificada</option>
              <option value="no_verificada">Sin verificar</option>
            </select>
          )}
        </Campo>
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay conversaciones con estos filtros.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <ul className="lista-simple lista-conversaciones" aria-busy={cargando} aria-label="Conversaciones con IA">
            {datos.items.map((c) => {
              const turno = enCurso[c.id] ?? c.ia.turno_en_curso;
              return (
                <li key={c.id}>
                  <button type="button" className="item-conversacion" aria-current={seleccionada === c.id ? 'true' : undefined} onClick={() => onSeleccionar(c.id)}>
                    <span className="item-titulo">
                      <strong>{c.cliente_nombre ?? c.nombre_perfil ?? numeroVisible(c, usuario.rol)}</strong>
                      <span>
                        {turno && <span className="insignia insignia-ia">IA respondiendo…</span>}
                        {c.ia.instrucciones_pendientes > 0 && (
                          <span className="insignia insignia-advertencia"> {c.ia.instrucciones_pendientes} instr. pendiente{c.ia.instrucciones_pendientes === 1 ? '' : 's'}</span>
                        )}
                      </span>
                    </span>
                    <span className="ayuda">
                      {numeroVisible(c, usuario.rol)} · {c.campana?.nombre ?? 'Sin campaña'} · {ETIQUETA_ATENDIDA_POR[c.atendida_por]}
                      {c.usuario_asignado ? ` (${c.usuario_asignado.nombre})` : ''}
                    </span>
                    <span className="ayuda">
                      {c.ia.identidad_verificada ? 'Identidad verificada' : 'Identidad sin verificar'} · {c.ia.turnos} turno{c.ia.turnos === 1 ? '' : 's'} · {formatearUSD(c.ia.costo_usd, 4)}
                    </span>
                    <span className="ayuda">
                      Gestión: {c.ia.gestion ? ETIQUETA_RESULTADO[c.ia.gestion.resultado] : 'ninguna'}
                      {c.ia.ultima_accion && (
                        <>
                          {' · '}Última acción:{' '}
                          <span className={c.ia.ultima_accion.es_error ? 'texto-error' : undefined}>
                            {c.ia.ultima_accion.herramienta}{c.ia.ultima_accion.es_error ? ' (error)' : ''}
                          </span>
                        </>
                      )}
                    </span>
                    <span className="ayuda">{c.estado === 'abierta' ? 'Abierta' : 'Cerrada'} · {formatearFechaHora(c.ultimo_mensaje_en)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
        </>
      )}
    </section>
  );
}
