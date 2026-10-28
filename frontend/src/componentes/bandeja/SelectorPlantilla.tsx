import { useCallback, useRef, useState } from 'react';
import { listarPlantillas } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { ResultadoEnvioPlantilla } from '../../api/tipos';
import { conPunto, formatearFechaHora } from '../../utilidades/formato';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { nuevoUuid, previaPlantilla } from '../../utilidades/whatsapp';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

interface Props {
  campanaId: number;
  /** Envía la plantilla con la clave de idempotencia del intento (bandeja o consola). */
  enviar: (plantillaId: number, idempotenciaClave: string) => Promise<ResultadoEnvioPlantilla>;
  /** Se llama solo cuando el envío fue permitido. */
  onEnviada: (resultado: ResultadoEnvioPlantilla) => void;
  /** Texto de introducción (p. ej. "La ventana de 24 h está cerrada"). */
  introduccion?: string;
}

/**
 * Selector de plantillas enviables de la campaña, con vista previa y resultado de cumplimiento. Un resultado
 * `permitido=false` no es un error HTTP: se muestran sus motivos y la próxima ventana.
 */
export function SelectorPlantilla({ campanaId, enviar, onEnviada, introduccion }: Props) {
  const cargador = useCallback(() => listarPlantillas({ campana_id: campanaId, enviables: true }), [campanaId]);
  const { datos, cargando, error: errorCarga, recargar } = useCarga(cargador);
  const [seleccion, setSeleccion] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [bloqueo, setBloqueo] = useState<ResultadoEnvioPlantilla | null>(null);
  // Una clave por intento: si el envío falla por red/servidor se reintenta con la misma, para no duplicar el mensaje.
  const intento = useRef<{ plantillaId: number; clave: string } | null>(null);

  const plantillas = (datos ?? []).filter((p) => p.enviable);
  const elegida = plantillas.find((p) => String(p.id) === seleccion) ?? null;

  async function alEnviar() {
    if (!elegida) return;
    setError(null);
    setBloqueo(null);
    if (!intento.current || intento.current.plantillaId !== elegida.id) {
      intento.current = { plantillaId: elegida.id, clave: nuevoUuid() };
    }
    setEnviando(true);
    try {
      const r = await enviar(elegida.id, intento.current.clave);
      if (r.permitido) {
        intento.current = null;
        setSeleccion('');
        onEnviada(r);
      } else {
        setBloqueo(r);
      }
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-plantilla" className="tarjeta selector-plantilla">
      <h3 id="t-plantilla">Enviar una plantilla</h3>
      {introduccion && <p>{introduccion}</p>}
      {cargando && !datos && <Cargando />}
      <MensajeError error={errorCarga} onReintentar={recargar} />
      {datos && plantillas.length === 0 && <p>No hay plantillas disponibles para esta campaña.</p>}
      {plantillas.length > 0 && (
        <>
          <Campo etiqueta="Plantilla">
            {(p) => (
              <select {...p} value={seleccion} onChange={(e) => { setSeleccion(e.target.value); setBloqueo(null); setError(null); }}>
                <option value="">Seleccione…</option>
                {plantillas.map((x) => (
                  <option key={x.id} value={x.id}>{x.nombre}</option>
                ))}
              </select>
            )}
          </Campo>
          {elegida && (
            <blockquote className="previa-plantilla" aria-label="Vista previa de la plantilla">
              {previaPlantilla(elegida)}
            </blockquote>
          )}
          <MensajeError error={error} />
          {bloqueo && (
            <div role="alert" className="alerta alerta-error">
              <p>La plantilla no se envió por cumplimiento.</p>
              <ul>
                {bloqueo.motivos.map((m) => (
                  <li key={m.codigo}><strong>{m.codigo}</strong>: {m.mensaje}</li>
                ))}
              </ul>
              {bloqueo.proxima_ventana_inicio && <p>Próxima ventana: {conPunto(formatearFechaHora(bloqueo.proxima_ventana_inicio))}</p>}
            </div>
          )}
          <button type="button" className="primario" disabled={!elegida || enviando} onClick={() => void alEnviar()}>
            {enviando ? 'Enviando…' : 'Enviar plantilla'}
          </button>
        </>
      )}
    </section>
  );
}
