import { useCallback, useState } from 'react';
import { asignarConversacion, listarAgentesCampana } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Conversacion } from '../../api/tipos';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { MensajeError } from '../MensajeError';

interface Props {
  conversacionId: number;
  /** Campaña de la conversación; sin campaña no hay agentes asignables y solo se puede tomar. */
  campanaId: number | null;
  onAsignada: (c: Conversacion) => void;
  onCancelar: () => void;
}

/** Asigna una conversación a un agente asignado a su campaña (administrador y supervisor). */
export function AsignarA({ conversacionId, campanaId, onAsignada, onCancelar }: Props) {
  const cargador = useCallback(() => (campanaId === null ? Promise.resolve([]) : listarAgentesCampana(campanaId)), [campanaId]);
  const { datos, cargando, error: errorCarga } = useCarga(cargador);
  const [destino, setDestino] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  const agentes = (datos ?? []).filter((a) => a.activo);

  async function asignar() {
    if (!destino) return;
    setError(null);
    setEnviando(true);
    try {
      onAsignada(await asignarConversacion(conversacionId, Number(destino)));
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="asignar">
      <MensajeError error={errorCarga} />
      {!cargando && agentes.length === 0 && !errorCarga && (
        <p className="ayuda">
          {campanaId === null ? 'Sin campaña: use "Tomar" para atenderla usted.' : 'La campaña no tiene agentes activos asignados.'}
        </p>
      )}
      {agentes.length > 0 && (
        <Campo etiqueta="Asignar a" error={error?.detalleDe('usuario_id')}>
          {(p) => (
            <select {...p} value={destino} onChange={(e) => setDestino(e.target.value)}>
              <option value="">Seleccione un agente…</option>
              {agentes.map((a) => (
                <option key={a.usuario_id} value={a.usuario_id}>{a.nombre}</option>
              ))}
            </select>
          )}
        </Campo>
      )}
      <MensajeError error={error} camposMostrados={['usuario_id']} />
      <div className="acciones">
        {agentes.length > 0 && (
          <button type="button" className="primario" disabled={!destino || enviando} onClick={() => void asignar()}>
            {enviando ? 'Asignando…' : 'Confirmar asignación'}
          </button>
        )}
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </div>
  );
}
