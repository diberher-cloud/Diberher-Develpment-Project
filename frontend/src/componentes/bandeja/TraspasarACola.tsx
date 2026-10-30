import { useState, type FormEvent } from 'react';
import { traspasarConversacion } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Conversacion } from '../../api/tipos';
import { traducirErrorIA } from '../../utilidades/ia';
import { comoErrorApi } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { MensajeError } from '../MensajeError';

const MAX = 500;

interface Props {
  conversacionId: number;
  onTraspasada: (c: Conversacion) => void;
  onCancelar: () => void;
}

/** Traspasa una conversación de la IA a la cola humana (motivo "supervisor"), con resumen opcional. */
export function TraspasarACola({ conversacionId, onTraspasada, onCancelar }: Props) {
  const [resumen, setResumen] = useState('');
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const r = resumen.trim();
    if (r.length > MAX) {
      setErrLocal(`El resumen no puede superar ${MAX} caracteres.`);
      return;
    }
    setErrLocal(undefined);
    setEnviando(true);
    try {
      onTraspasada(await traspasarConversacion(conversacionId, r || undefined));
    } catch (err) {
      setError(traducirErrorIA(comoErrorApi(err)));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} noValidate className="tarjeta formulario" aria-label="Traspasar la conversación a la cola">
      <h3>Traspasar a la cola de atención</h3>
      <p>La IA deja de atender la conversación y queda en la cola para que un asesor la tome. No se envía ningún mensaje al cliente.</p>
      <Campo etiqueta="Resumen para el asesor (opcional)" ayuda={`${resumen.length}/${MAX} caracteres`} error={errLocal ?? error?.detalleDe('resumen')}>
        {(p) => <textarea {...p} rows={3} maxLength={MAX} value={resumen} onChange={(e) => setResumen(e.target.value)} />}
      </Campo>
      <MensajeError error={error} camposMostrados={['resumen']} />
      <div className="acciones">
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Traspasando…' : 'Confirmar traspaso'}</button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}
