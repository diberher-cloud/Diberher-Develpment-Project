import { useState, type FormEvent } from 'react';
import type { CambioEstadoAgente, EstadoAgente, MotivoPausa } from '../../api/tipos';
import { ETIQUETA_ESTADO_AGENTE, ETIQUETA_MOTIVO_PAUSA } from '../../utilidades/consola';
import { formatearDuracion } from '../../utilidades/formato';
import { useAhora } from '../../utilidades/useAhora';
import { Campo } from '../Campo';

interface Props {
  estado: EstadoAgente | null;
  /** Rechaza con ErrorApi si el servidor no acepta el cambio. */
  onCambiar: (cambio: CambioEstadoAgente) => Promise<void>;
}

const MOTIVOS = Object.keys(ETIQUETA_MOTIVO_PAUSA) as MotivoPausa[];

export function SelectorEstado({ estado, onCambiar }: Props) {
  const [destino, setDestino] = useState<CambioEstadoAgente['estado']>('disponible');
  const [motivo, setMotivo] = useState<MotivoPausa | ''>('');
  const [errorMotivo, setErrorMotivo] = useState<string | undefined>();
  const [enviando, setEnviando] = useState(false);
  const ahora = useAhora(1000, estado !== null);
  const automatico = estado?.estado === 'en_llamada' || estado?.estado === 'tipificando';

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (destino === 'pausa' && !motivo) {
      setErrorMotivo('Seleccione el motivo de la pausa.');
      return;
    }
    setErrorMotivo(undefined);
    setEnviando(true);
    try {
      await onCambiar(destino === 'pausa' ? { estado: 'pausa', motivo_pausa: motivo as MotivoPausa } : { estado: destino });
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-estado" className="tarjeta">
      <h2 id="t-estado">Mi estado</h2>
      {estado ? (
        <>
          <p role="status">
            Estado actual:{' '}
            <strong className={`insignia agente-${estado.estado}`}>{ETIQUETA_ESTADO_AGENTE[estado.estado]}</strong>
            {estado.motivo_pausa ? ` (${ETIQUETA_MOTIVO_PAUSA[estado.motivo_pausa]})` : ''}
          </p>
          <p className="ayuda">Tiempo en este estado: {formatearDuracion((ahora - new Date(estado.desde).getTime()) / 1000)}</p>
        </>
      ) : (
        <p role="status">Cargando estado…</p>
      )}
      <form onSubmit={enviar} noValidate className="filtros">
        <Campo etiqueta="Cambiar estado a">
          {(p) => (
            <select
              {...p}
              value={destino}
              disabled={!estado || automatico}
              onChange={(e) => setDestino(e.target.value as CambioEstadoAgente['estado'])}
            >
              <option value="disponible">Disponible</option>
              <option value="pausa">En pausa</option>
              <option value="desconectado">Desconectado</option>
            </select>
          )}
        </Campo>
        {destino === 'pausa' && (
          <Campo etiqueta="Motivo de la pausa" error={errorMotivo}>
            {(p) => (
              <select {...p} value={motivo} disabled={automatico} onChange={(e) => setMotivo(e.target.value as MotivoPausa | '')}>
                <option value="">Seleccione…</option>
                {MOTIVOS.map((m) => (
                  <option key={m} value={m}>{ETIQUETA_MOTIVO_PAUSA[m]}</option>
                ))}
              </select>
            )}
          </Campo>
        )}
        <button type="submit" disabled={!estado || automatico || enviando}>Cambiar estado</button>
      </form>
      {automatico && (
        <p className="ayuda">
          {estado?.estado === 'en_llamada'
            ? 'No puede cambiar de estado durante una llamada.'
            : 'Tipifique la llamada para volver a quedar disponible.'}
        </p>
      )}
    </section>
  );
}
