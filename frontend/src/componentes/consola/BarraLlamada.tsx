import { useEffect, useState } from 'react';
import type { Motivo, TelefonoFicha } from '../../api/tipos';
import { esSimulable, type EstadoSoftphone, type Softphone } from '../../telefonia/softphone';
import { TEXTO_SOFTPHONE } from '../../utilidades/consola';
import { formatearDuracion } from '../../utilidades/formato';
import { useAhora } from '../../utilidades/useAhora';
import { Campo } from '../Campo';

interface Props {
  telefonos: TelefonoFicha[];
  softphone: Softphone | null;
  estado: EstadoSoftphone;
  detalle?: string;
  /** El agente está `disponible` y sin tipificación pendiente. */
  agenteDisponible: boolean;
  /** Motivos de bloqueo recibidos de la última llamada. */
  motivosBloqueo: Motivo[];
  onLlamar: (telefonoId: number) => void;
}

export function BarraLlamada({ telefonos, softphone, estado, detalle, agenteDisponible, motivosBloqueo, onLlamar }: Props) {
  const [seleccion, setSeleccion] = useState<number | null>(null);
  const [silenciado, setSilenciado] = useState(false);
  const [inicio, setInicio] = useState<number | null>(null);
  const enCurso = estado === 'en_curso';
  const ahora = useAhora(1000, enCurso);

  // El temporizador arranca al entrar en `en_curso` (se mide en el navegador; solo informativo).
  useEffect(() => {
    setInicio(enCurso ? Date.now() : null);
  }, [enCurso]);
  const segundos = enCurso && inicio !== null ? Math.max(0, ahora - inicio) / 1000 : 0;

  const telefono = telefonos.find((t) => t.id === seleccion) ?? telefonos.find((t) => t.llamable) ?? telefonos[0];
  const ocupada = estado === 'conectando' || enCurso;
  const softphoneListo = estado === 'listo' || estado === 'finalizada' || estado === 'error';
  const puede = !!telefono && telefono.llamable && agenteDisponible && softphoneListo && !!softphone;

  let razon: string | null = null;
  if (!softphone || estado === 'inactivo' || estado === 'registrando') razon = 'El softphone aún no está listo.';
  else if (!agenteDisponible) razon = 'Debe estar en estado Disponible para llamar.';
  else if (!telefono) razon = 'El cliente no tiene teléfonos.';
  else if (!telefono.llamable) {
    razon = telefono.motivos.length ? telefono.motivos.map((m) => m.mensaje).join(' ') : 'Este teléfono no se puede llamar.';
  }

  function alternarSilencio() {
    const nuevo = !silenciado;
    softphone?.silenciar(nuevo);
    setSilenciado(nuevo);
  }

  const sim = esSimulable(softphone) ? softphone : null;
  const bloqueada = estado === 'finalizada' && motivosBloqueo.length > 0;

  return (
    <section aria-labelledby="t-llamada" className="tarjeta barra-llamada">
      <h2 id="t-llamada">Llamada</h2>
      <p role="status" aria-live="polite" className="estado-softphone">
        {TEXTO_SOFTPHONE[estado]}
        {detalle && estado !== 'finalizada' ? ` ${detalle}` : ''}
      </p>
      {enCurso && <p>Duración: <time>{formatearDuracion(segundos)}</time></p>}
      {bloqueada && (
        <div role="alert" className="alerta alerta-error">
          <p>La llamada fue bloqueada por cumplimiento o por el estado del registro:</p>
          <ul>
            {motivosBloqueo.map((m) => (
              <li key={m.codigo}><strong>{m.codigo}</strong>: {m.mensaje}</li>
            ))}
          </ul>
        </div>
      )}
      {estado === 'error' && detalle && <p role="alert" className="alerta alerta-error">{detalle}</p>}

      <div className="acciones">
        {telefonos.length > 1 && (
          <Campo etiqueta="Teléfono a llamar">
            {(p) => (
              <select {...p} value={telefono?.id ?? ''} disabled={ocupada} onChange={(e) => setSeleccion(Number(e.target.value))}>
                {telefonos.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.numero_mascara} ({t.tipo_linea === 'movil' ? 'móvil' : 'fijo'}){t.llamable ? '' : ' - no llamable'}
                  </option>
                ))}
              </select>
            )}
          </Campo>
        )}
        {!ocupada ? (
          <button
            type="button"
            className="primario"
            disabled={!puede}
            aria-describedby={razon ? 'razon-llamar' : undefined}
            onClick={() => telefono && onLlamar(telefono.id)}
          >
            Llamar{telefono ? <span className="solo-lectura"> a {telefono.numero_mascara}</span> : null}
          </button>
        ) : (
          <>
            <button type="button" className="peligro" onClick={() => softphone?.colgar()}>Colgar</button>
            <button type="button" aria-pressed={silenciado} disabled={!enCurso} onClick={alternarSilencio}>
              {silenciado ? 'Quitar silencio' : 'Silenciar'}
            </button>
          </>
        )}
      </div>
      {razon && !ocupada && <p id="razon-llamar" className="ayuda">{razon}</p>}

      {sim && estado === 'conectando' && (
        <div role="group" aria-label="Simulación de la llamada (solo desarrollo)" className="acciones">
          <span className="ayuda">Simulación:</span>
          <button type="button" onClick={() => void sim.simular({ evento: 'contestada' })}>Contesta</button>
          <button type="button" onClick={() => void sim.simular({ evento: 'finalizada', resultado: 'no-answer' })}>No contesta</button>
          <button type="button" onClick={() => void sim.simular({ evento: 'finalizada', resultado: 'busy' })}>Ocupado</button>
        </div>
      )}
    </section>
  );
}
