import { useCallback, useState } from 'react';
import { listarCampanas, listarConversaciones } from '../../api/endpoints';
import type { AtendidaPor, EstadoConversacion, Usuario } from '../../api/tipos';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { useCarga } from '../../utilidades/useCarga';
import { ETIQUETA_ATENDIDA_POR, numeroVisible } from '../../utilidades/whatsapp';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { Paginador } from '../Paginador';

interface Props {
  usuario: Usuario;
  version: number;
  seleccionada: number | null;
  onAbrir: (id: number) => void;
}

/** "Mis conversaciones" para el agente (el servidor ya filtra) y conversaciones con filtros para A/S. */
export function ListaConversaciones({ usuario, version, seleccionada, onAbrir }: Props) {
  const gestor = usuario.rol !== 'agente';
  const { reconexiones } = useConexionTiempoReal();
  const [estado, setEstado] = useState<EstadoConversacion>('abierta');
  const [atendidaPor, setAtendidaPor] = useState<AtendidaPor | ''>('');
  const [campana, setCampana] = useState('');
  const [page, setPage] = useState(1);

  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return listarConversaciones({
      estado, page, page_size: 20,
      atendida_por: gestor ? atendidaPor : '',
      campana_id: gestor && campana !== '' && campana !== 'sin' ? Number(campana) : '',
      sin_campana: gestor && campana === 'sin' ? true : '',
    });
  }, [estado, atendidaPor, campana, page, gestor, version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);

  const cargadorCampanas = useCallback(() => (gestor ? listarCampanas({ page_size: 100 }) : Promise.resolve(null)), [gestor]);
  const { datos: campanas } = useCarga(cargadorCampanas);

  useEventoTiempoReal(['conversacion.mensaje', 'conversacion.estado'], recargar);

  return (
    <section aria-labelledby="t-lista" className="tarjeta">
      <h2 id="t-lista">{gestor ? 'Conversaciones' : 'Mis conversaciones'}</h2>
      <form className="filtros" role="search" aria-label="Filtros de conversaciones" onSubmit={(e) => e.preventDefault()}>
        <Campo etiqueta="Estado">
          {(p) => (
            <select {...p} value={estado} onChange={(e) => { setPage(1); setEstado(e.target.value as EstadoConversacion); }}>
              <option value="abierta">Abiertas</option>
              <option value="cerrada">Cerradas</option>
            </select>
          )}
        </Campo>
        {gestor && (
          <>
            <Campo etiqueta="Atendida por">
              {(p) => (
                <select {...p} value={atendidaPor} onChange={(e) => { setPage(1); setAtendidaPor(e.target.value as AtendidaPor | ''); }}>
                  <option value="">Todas</option>
                  <option value="sin_asignar">Sin asignar</option>
                  <option value="humano">Agente humano</option>
                  <option value="ia">Agente IA</option>
                </select>
              )}
            </Campo>
            <Campo etiqueta="Campaña">
              {(p) => (
                <select {...p} value={campana} onChange={(e) => { setPage(1); setCampana(e.target.value); }}>
                  <option value="">Todas</option>
                  <option value="sin">Sin campaña</option>
                  {(campanas?.items ?? []).map((c) => (
                    <option key={c.id} value={c.id}>{c.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
          </>
        )}
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay conversaciones.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <ul className="lista-simple lista-conversaciones" aria-busy={cargando}>
            {datos.items.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className="item-conversacion"
                  aria-current={seleccionada === c.id ? 'true' : undefined}
                  onClick={() => onAbrir(c.id)}
                >
                  <span className="item-titulo">
                    <strong>{c.cliente_nombre ?? c.nombre_perfil ?? numeroVisible(c, usuario.rol)}</strong>
                    {c.mensajes_sin_leer > 0 && (
                      <span className="insignia insignia-advertencia">
                        {c.mensajes_sin_leer} sin leer<span className="solo-lectura"> de {c.cliente_nombre ?? c.numero_mascara}</span>
                      </span>
                    )}
                  </span>
                  <span className="ayuda">
                    {numeroVisible(c, usuario.rol)} · {c.campana?.nombre ?? 'Sin campaña'} · {ETIQUETA_ATENDIDA_POR[c.atendida_por]}
                    {c.usuario_asignado ? ` (${c.usuario_asignado.nombre})` : ''}
                  </span>
                  <span className="ayuda">
                    {c.estado === 'abierta' ? (c.ventana_abierta ? 'Ventana abierta' : 'Ventana cerrada') : 'Cerrada'} ·{' '}
                    {formatearFechaHora(c.ultimo_mensaje_en)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
        </>
      )}
    </section>
  );
}
