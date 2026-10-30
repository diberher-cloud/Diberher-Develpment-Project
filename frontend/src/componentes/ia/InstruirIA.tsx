import { useCallback, useState, type FormEvent } from 'react';
import { crearInstruccion, listarInstrucciones } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { traducirErrorIA } from '../../utilidades/ia';
import { useAgrupador } from '../../utilidades/useAgrupador';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

const MAX = 1000;

interface Props {
  conversacionId: number;
  /** `false` si la conversación está cerrada o ya no la atiende la IA. */
  habilitada: boolean;
}

/** Instrucciones del supervisor a la IA (se aplican en su siguiente turno; no disparan un turno por sí solas). */
export function InstruirIA({ conversacionId: id, habilitada }: Props) {
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void reconexiones;
    return listarInstrucciones(id);
  }, [id, reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const [texto, setTexto] = useState('');
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [errApi, setErrApi] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [ok, setOk] = useState(false);

  // Una instrucción pasa a "aplicada" cuando la IA completa un turno o ejecuta una acción.
  const programar = useAgrupador<'lista'>(600, () => recargar());
  useEventoTiempoReal(['ia.turno', 'ia.accion'], (e) => {
    if ((e.tipo === 'ia.turno' || e.tipo === 'ia.accion') && e.datos.conversacion_id === id) programar('lista');
  });

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setErrApi(null);
    setOk(false);
    const t = texto.trim();
    if (t.length < 1 || t.length > MAX) {
      setErrLocal(`La instrucción debe tener entre 1 y ${MAX} caracteres.`);
      return;
    }
    setErrLocal(undefined);
    setEnviando(true);
    try {
      await crearInstruccion(id, t);
      setTexto('');
      setOk(true);
      recargar();
    } catch (e) {
      setErrApi(traducirErrorIA(comoErrorApi(e)));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-instruir" className="tarjeta">
      <h3 id="t-instruir">Instruir a la IA</h3>
      <p className="ayuda">La IA la leerá en su siguiente turno. No envía nada al cliente por sí sola.</p>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Instrucción para la IA" ayuda={`${texto.length}/${MAX} caracteres`} error={errLocal ?? errApi?.detalleDe('texto')}>
          {(p) => <textarea {...p} rows={3} maxLength={MAX} value={texto} disabled={!habilitada || enviando} onChange={(e) => setTexto(e.target.value)} />}
        </Campo>
        <MensajeError error={errApi} camposMostrados={['texto']} />
        {!habilitada && <p className="ayuda">Solo se puede instruir a la IA en conversaciones abiertas que ella atiende.</p>}
        {ok && <p role="status" className="alerta alerta-ok">Instrucción enviada: queda pendiente hasta el siguiente turno de la IA.</p>}
        <button type="submit" className="primario" disabled={!habilitada || enviando}>{enviando ? 'Enviando…' : 'Enviar instrucción'}</button>
      </form>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.length > 0 && (
        <ul className="lista-simple lista-instrucciones" aria-label="Instrucciones enviadas">
          {datos.map((i) => (
            <li key={i.id}>
              <p className="texto-instruccion">{i.texto}</p>
              <p className="ayuda">
                {i.usuario.nombre} · {formatearFechaHora(i.creado_en)} ·{' '}
                <span className={`insignia ${i.aplicada_en ? 'estado-activa' : 'insignia-advertencia'}`}>
                  {i.aplicada_en ? `Aplicada el ${formatearFechaHora(i.aplicada_en)}` : 'Pendiente'}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
      {datos && datos.length === 0 && <p>Aún no hay instrucciones en esta conversación.</p>}
    </section>
  );
}
