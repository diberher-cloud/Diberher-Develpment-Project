import { useState } from 'react';
import { cerrarConversacion } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { CierreConversacion, Conversacion } from '../../api/tipos';
import { comoErrorApi } from '../../utilidades/useCarga';
import { huboEntrantes } from '../../utilidades/whatsapp';
import { FormularioTipificacion } from '../consola/FormularioTipificacion';
import { MensajeError } from '../MensajeError';

interface Props {
  conversacion: Conversacion;
  /** Saldo total del registro vinculado, si se conoce (valida el tope de la promesa). */
  saldoTotal?: string | null;
  onCerrada: (c: CierreConversacion) => void;
  onCancelar: () => void;
}

/** Cierra la conversación: con registro vinculado exige tipificación; sin registro se cierra sin tipificar. */
export function CerrarConversacion({ conversacion: c, saldoTotal = null, onCerrada, onCancelar }: Props) {
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function cerrarSinTipificar() {
    setError(null);
    setEnviando(true);
    try {
      onCerrada(await cerrarConversacion(c.id, { tipificacion: null }));
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setEnviando(false);
    }
  }

  if (c.campana_cliente_id !== null && c.campana !== null) {
    return (
      <>
        <FormularioTipificacion
          contexto="conversacion"
          tipoCampana={c.campana.tipo}
          saldoTotal={saldoTotal}
          huboEntrantes={huboEntrantes(c)}
          onEnviar={async (tipificacion) => {
            onCerrada(await cerrarConversacion(c.id, { tipificacion }));
          }}
        />
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </>
    );
  }
  return (
    <section aria-labelledby="t-cerrar" className="tarjeta">
      <h3 id="t-cerrar">Cerrar la conversación</h3>
      <p>La conversación no está vinculada a un registro de campaña: se cierra sin tipificación.</p>
      <MensajeError error={error} />
      <div className="acciones">
        <button type="button" className="primario" disabled={enviando} onClick={() => void cerrarSinTipificar()}>
          {enviando ? 'Cerrando…' : 'Cerrar conversación'}
        </button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </section>
  );
}
