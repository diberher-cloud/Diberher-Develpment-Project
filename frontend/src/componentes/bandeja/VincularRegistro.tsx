import { useCallback, useState } from 'react';
import { listarRegistrosCandidatos, vincularRegistro } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Conversacion } from '../../api/tipos';
import { ETIQUETA_TIPO } from '../../utilidades/campanas';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

interface Props {
  conversacion: Conversacion;
  onVinculada: (c: Conversacion) => void;
  onCancelar: () => void;
}

/** Vincula una conversación sin registro a uno de los registros candidatos (mismo número, campañas con WhatsApp). */
export function VincularRegistro({ conversacion: c, onVinculada, onCancelar }: Props) {
  const cargador = useCallback(() => listarRegistrosCandidatos(c.id), [c.id]);
  const { datos, cargando, error: errorCarga, recargar } = useCarga(cargador);
  const [seleccion, setSeleccion] = useState<number | null>(null);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function vincular() {
    if (seleccion === null) return;
    setError(null);
    setEnviando(true);
    try {
      onVinculada(await vincularRegistro(c.id, seleccion));
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-vincular" className="tarjeta">
      <h3 id="t-vincular">Vincular a un registro de campaña</h3>
      {cargando && !datos && <Cargando />}
      <MensajeError error={errorCarga} onReintentar={recargar} />
      {datos && datos.length === 0 && <p>No hay registros candidatos para este número.</p>}
      {datos && datos.length > 0 && (
        <fieldset>
          <legend>Registros candidatos</legend>
          {datos.map((r) => (
            <div key={r.campana_cliente_id}>
              <label>
                <input
                  type="radio"
                  name="registro-candidato"
                  checked={seleccion === r.campana_cliente_id}
                  onChange={() => setSeleccion(r.campana_cliente_id)}
                />{' '}
                {r.cliente_nombre} — {r.campana.nombre} ({ETIQUETA_TIPO[r.campana.tipo]}), estado {r.estado}
              </label>
            </div>
          ))}
        </fieldset>
      )}
      <MensajeError error={error} />
      <div className="acciones">
        <button type="button" className="primario" disabled={seleccion === null || enviando} onClick={() => void vincular()}>
          {enviando ? 'Vinculando…' : 'Vincular registro'}
        </button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </section>
  );
}
