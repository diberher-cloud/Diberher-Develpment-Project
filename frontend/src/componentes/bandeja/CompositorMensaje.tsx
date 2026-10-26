import { useId, useRef, useState, type KeyboardEvent } from 'react';
import { enviarPlantillaConversacion, enviarTexto } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Conversacion, Mensaje } from '../../api/tipos';
import { comoErrorApi } from '../../utilidades/useCarga';
import { MAX_TEXTO_POR_DEFECTO, nuevoUuid } from '../../utilidades/whatsapp';
import { MensajeError } from '../MensajeError';
import { SelectorPlantilla } from './SelectorPlantilla';

interface Props {
  conversacion: Conversacion;
  maxCaracteres?: number;
  /** Mensaje aceptado por el servidor (texto 202 o plantilla permitida). */
  onEnviado: (m: Mensaje) => void;
  /** Pide recargar la conversación (p. ej. la ventana se cerró). */
  onRecargar: () => void;
}

const CODIGOS_QUE_RECARGAN = ['VENTANA_CERRADA', 'CLIENTE_OPT_OUT', 'CONVERSACION_CERRADA', 'CONVERSACION_NO_ASIGNADA'];

export function CompositorMensaje({ conversacion: c, maxCaracteres = MAX_TEXTO_POR_DEFECTO, onEnviado, onRecargar }: Props) {
  const [texto, setTexto] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);
  // Intento de envío en curso: se reutiliza la misma clave si se reintenta el mismo texto tras un fallo.
  const intento = useRef<{ texto: string; clave: string } | null>(null);
  const id = useId();

  const codigos = c.motivos_no_responder.map((m) => m.codigo);
  const esDueno = !codigos.includes('NO_ES_DUENO') && !codigos.includes('CONVERSACION_CERRADA');
  const soloPlantillas = esDueno && codigos.includes('VENTANA_CERRADA') && c.campana !== null && c.campana_cliente_id !== null;

  async function enviar() {
    const limpio = texto.trim();
    if (!limpio || limpio.length > maxCaracteres || enviando || !c.puede_responder) return;
    if (!intento.current || intento.current.texto !== limpio) intento.current = { texto: limpio, clave: nuevoUuid() };
    setError(null);
    setEnviando(true);
    try {
      const m = await enviarTexto(c.id, { texto: limpio, idempotencia_clave: intento.current.clave });
      intento.current = null;
      setTexto('');
      onEnviado(m);
    } catch (e) {
      const err = comoErrorApi(e);
      setError(err);
      // Un rechazo definitivo del servidor no es reintentable con la misma clave; un fallo de red o 5xx sí.
      if (err.status >= 400 && err.status < 500) intento.current = null;
      if (CODIGOS_QUE_RECARGAN.includes(err.codigo)) onRecargar();
    } finally {
      setEnviando(false);
    }
  }

  function alTeclear(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void enviar();
    }
  }

  if (soloPlantillas && c.campana) {
    return (
      <div className="compositor">
        <MensajeError error={error} />
        <SelectorPlantilla
          campanaId={c.campana.id}
          introduccion="La ventana de 24 h está cerrada: solo se pueden enviar plantillas aprobadas."
          enviar={(plantillaId, clave) => enviarPlantillaConversacion(c.id, { plantilla_id: plantillaId, idempotencia_clave: clave })}
          onEnviada={(r) => {
            if (r.mensaje) onEnviado(r.mensaje);
            onRecargar();
          }}
        />
      </div>
    );
  }

  const deshabilitado = !c.puede_responder;
  const restantes = maxCaracteres - texto.length;
  const idMotivos = `${id}-motivos`;
  const idContador = `${id}-contador`;
  return (
    <form
      className="compositor"
      aria-label="Redactar mensaje"
      onSubmit={(e) => {
        e.preventDefault();
        void enviar();
      }}
    >
      <label htmlFor={`${id}-texto`}>Mensaje</label>
      <textarea
        id={`${id}-texto`}
        rows={3}
        value={texto}
        disabled={deshabilitado}
        onChange={(e) => setTexto(e.target.value)}
        onKeyDown={alTeclear}
        aria-describedby={[deshabilitado ? idMotivos : '', idContador].filter(Boolean).join(' ')}
        aria-invalid={restantes < 0 ? true : undefined}
      />
      <p id={idContador} className={restantes < 0 ? 'error-campo' : 'ayuda'}>
        {texto.length} / {maxCaracteres} caracteres. Enter envía; Mayús+Enter agrega un salto de línea.
      </p>
      {deshabilitado && (
        <ul id={idMotivos} className="ayuda" aria-label="Por qué no puede responder">
          {c.motivos_no_responder.map((m) => (
            <li key={m.codigo}>{m.mensaje}</li>
          ))}
        </ul>
      )}
      <MensajeError error={error} />
      <button type="submit" className="primario" disabled={deshabilitado || enviando || !texto.trim() || restantes < 0}>
        {enviando ? 'Enviando…' : 'Enviar'}
      </button>
    </form>
  );
}
