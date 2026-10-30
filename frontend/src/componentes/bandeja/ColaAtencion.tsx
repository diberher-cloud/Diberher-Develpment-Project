import { useCallback, useEffect, useState } from 'react';
import { listarColaAtencion, tomarConversacion, tomarSiguiente } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Conversacion, ItemCola, Usuario } from '../../api/tipos';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { useAhora } from '../../utilidades/useAhora';
import { formatearDuracion } from '../../utilidades/formato';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { ETIQUETA_MOTIVO_COLA } from '../../utilidades/whatsapp';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { AsignarA } from './AsignarA';

interface Props {
  usuario: Usuario;
  /** Cambia cuando otra parte de la bandeja modifica conversaciones (fuerza recarga). */
  version: number;
  onAbrir: (conversacionId: number) => void;
  /** Una conversación fue tomada o asignada desde la cola. */
  onCambio: (c?: Conversacion) => void;
}

/** Motivos de cola originados por la IA (`ia_*`, identidad bloqueada, presupuesto excedido): el resumen se destaca. */
const esMotivoIA = (m: string) => m.startsWith('ia_') || m === 'identidad_bloqueada' || m === 'presupuesto_excedido' || m === 'solicitud_cliente' || m === 'queja';

export function ColaAtencion({ usuario, version, onAbrir, onCambio }: Props) {
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void version;
    void reconexiones;
    return listarColaAtencion();
  }, [version, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const [cargadoEn, setCargadoEn] = useState(() => Date.now());
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [asignando, setAsignando] = useState<number | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const ahora = useAhora(1000, (datos?.length ?? 0) > 0);
  const gestor = usuario.rol !== 'agente';

  useEffect(() => {
    if (datos) setCargadoEn(Date.now());
  }, [datos]);
  useEventoTiempoReal('atencion.cola', recargar);

  async function tomar(id: number) {
    setErrorAccion(null);
    setAviso(null);
    setOcupado(true);
    try {
      const c = await tomarConversacion(id);
      onCambio(c);
      onAbrir(c.id);
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
      recargar();
    } finally {
      setOcupado(false);
    }
  }

  async function siguiente() {
    setErrorAccion(null);
    setAviso(null);
    setOcupado(true);
    try {
      const c = await tomarSiguiente();
      if (c) {
        onCambio(c);
        onAbrir(c.id);
      } else {
        setAviso('No hay conversaciones en la cola.');
        recargar();
      }
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
      recargar();
    } finally {
      setOcupado(false);
    }
  }

  const items: ItemCola[] = datos ?? [];
  return (
    <section aria-labelledby="t-cola" className="tarjeta">
      <h2 id="t-cola">Cola de atención</h2>
      <p aria-live="polite" className="ayuda">
        {items.length === 1 ? '1 conversación en espera.' : `${items.length} conversaciones en espera.`}
      </p>
      {!gestor && (
        <button type="button" className="primario" disabled={ocupado || items.length === 0} onClick={() => void siguiente()}>
          Tomar siguiente
        </button>
      )}
      <MensajeError error={errorAccion} />
      <MensajeError error={error} onReintentar={recargar} />
      {aviso && <p role="status">{aviso}</p>}
      {cargando && !datos && <Cargando />}
      {datos && items.length === 0 && !error && <p>La cola está vacía.</p>}
      {items.length > 0 && (
        <ul className="lista-simple lista-cola">
          {items.map((i) => {
            const espera = i.espera_segundos + Math.max(0, ahora - cargadoEn) / 1000;
            return (
              <li key={i.id} className="item-cola">
                <p>
                  <strong>{i.numero_mascara}</strong>
                  {' · '}
                  {i.campana?.nombre ?? 'Sin campaña'}
                  {' · '}
                  {ETIQUETA_MOTIVO_COLA[i.motivo]}
                  {i.prioridad === 1 && <span className="insignia insignia-advertencia"> Prioridad alta</span>}
                </p>
                {i.resumen && (
                  <p className={esMotivoIA(i.motivo) ? 'resumen-traspaso resumen-texto' : 'ayuda'}>
                    {esMotivoIA(i.motivo) && <strong>Resumen de la IA: </strong>}
                    {i.resumen}
                  </p>
                )}
                <p className="ayuda">
                  En espera: <time>{formatearDuracion(espera)}</time>
                </p>
                <div className="acciones">
                  <button type="button" onClick={() => onAbrir(i.conversacion_id)}>
                    Abrir<span className="solo-lectura"> conversación con {i.numero_mascara}</span>
                  </button>
                  {gestor && (
                    <>
                      <button type="button" disabled={ocupado} onClick={() => void tomar(i.conversacion_id)}>
                        Tomar<span className="solo-lectura"> conversación con {i.numero_mascara}</span>
                      </button>
                      <button type="button" aria-expanded={asignando === i.conversacion_id} onClick={() => setAsignando((x) => (x === i.conversacion_id ? null : i.conversacion_id))}>
                        Asignar a…<span className="solo-lectura"> conversación con {i.numero_mascara}</span>
                      </button>
                    </>
                  )}
                </div>
                {asignando === i.conversacion_id && (
                  <AsignarA
                    conversacionId={i.conversacion_id}
                    campanaId={i.campana?.id ?? null}
                    onAsignada={(c) => { setAsignando(null); onCambio(c); }}
                    onCancelar={() => setAsignando(null)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
