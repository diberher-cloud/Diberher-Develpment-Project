import { useState, type FormEvent } from 'react';
import {
  autorizarConversacion, liberarConversacion, optOutConversacion, tomarConversacion,
} from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { CierreConversacion, Conversacion, Finalidad, Usuario } from '../../api/tipos';
import { comoErrorApi } from '../../utilidades/useCarga';
import { ETIQUETA_FINALIDAD } from '../../utilidades/whatsapp';
import { Campo } from '../Campo';
import { MensajeError } from '../MensajeError';
import { AsignarA } from './AsignarA';
import { CerrarConversacion } from './CerrarConversacion';
import { VincularRegistro } from './VincularRegistro';

type Panel = null | 'asignar' | 'optout' | 'autorizacion' | 'vincular' | 'cerrar';

interface Props {
  conversacion: Conversacion;
  usuario: Usuario;
  fichaVisible: boolean;
  onAlternarFicha: () => void;
  onActualizada: (c: Conversacion) => void;
  onCerrada: (c: CierreConversacion) => void;
  onAviso: (texto: string) => void;
}

export function AccionesConversacion({ conversacion: c, usuario, fichaVisible, onAlternarFicha, onActualizada, onCerrada, onAviso }: Props) {
  const [panel, setPanel] = useState<Panel>(null);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const gestor = usuario.rol !== 'agente';
  const abierta = c.estado === 'abierta';
  const esDueno = c.atendida_por === 'humano' && c.usuario_asignado?.id === usuario.id;
  const puedeTomar = abierta && c.atendida_por === 'sin_asignar';
  const puedeAsignar = abierta && gestor && c.atendida_por !== 'ia';
  const puedeLiberar = abierta && c.atendida_por === 'humano' && (esDueno || gestor);
  const puedeActuar = abierta && (esDueno || gestor);

  async function ejecutar(accion: () => Promise<Conversacion>, aviso: string) {
    setError(null);
    setOcupado(true);
    try {
      onActualizada(await accion());
      onAviso(aviso);
      setPanel(null);
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setOcupado(false);
    }
  }

  const alternar = (p: Exclude<Panel, null>) => setPanel((x) => (x === p ? null : p));
  return (
    <div className="acciones-conversacion">
      <div className="acciones" role="group" aria-label="Acciones de la conversación">
        {puedeTomar && (
          <button type="button" disabled={ocupado} onClick={() => void ejecutar(() => tomarConversacion(c.id), 'Conversación tomada.')}>
            Tomar
          </button>
        )}
        {puedeAsignar && <button type="button" aria-expanded={panel === 'asignar'} onClick={() => alternar('asignar')}>Asignar a…</button>}
        {puedeLiberar && (
          <button type="button" disabled={ocupado} onClick={() => void ejecutar(() => liberarConversacion(c.id), 'Conversación liberada a la cola.')}>
            Liberar
          </button>
        )}
        {c.campana_cliente_id !== null && (
          <button type="button" aria-pressed={fichaVisible} onClick={onAlternarFicha}>Ver ficha del cliente</button>
        )}
        {abierta && c.campana_cliente_id === null && puedeActuar && (
          <button type="button" aria-expanded={panel === 'vincular'} onClick={() => alternar('vincular')}>Vincular registro</button>
        )}
        {puedeActuar && esDueno && (
          <button type="button" aria-expanded={panel === 'autorizacion'} onClick={() => alternar('autorizacion')}>Registrar autorización</button>
        )}
        {puedeActuar && (
          <button type="button" className="peligro" aria-expanded={panel === 'optout'} onClick={() => alternar('optout')}>
            Registrar baja (opt-out)
          </button>
        )}
        {puedeActuar && <button type="button" aria-expanded={panel === 'cerrar'} onClick={() => alternar('cerrar')}>Cerrar conversación</button>}
      </div>
      <MensajeError error={error} />

      {panel === 'asignar' && (
        <AsignarA
          conversacionId={c.id}
          campanaId={c.campana?.id ?? null}
          onAsignada={(x) => { onActualizada(x); onAviso('Conversación asignada.'); setPanel(null); }}
          onCancelar={() => setPanel(null)}
        />
      )}
      {panel === 'optout' && (
        <OptOut conversacion={c} onHecho={(x) => { onActualizada(x); onAviso('Baja registrada y conversación cerrada.'); setPanel(null); }} onCancelar={() => setPanel(null)} />
      )}
      {panel === 'autorizacion' && (
        <Autorizacion conversacion={c} onHecho={() => { onAviso('Autorización registrada.'); setPanel(null); }} onCancelar={() => setPanel(null)} />
      )}
      {panel === 'vincular' && (
        <VincularRegistro conversacion={c} onVinculada={(x) => { onActualizada(x); onAviso('Registro vinculado.'); setPanel(null); }} onCancelar={() => setPanel(null)} />
      )}
      {panel === 'cerrar' && (
        <CerrarConversacion
          conversacion={c}
          onCerrada={(x) => { onCerrada(x); onAviso('Conversación cerrada.'); setPanel(null); }}
          onCancelar={() => setPanel(null)}
        />
      )}
    </div>
  );
}

function OptOut({ conversacion: c, onHecho, onCancelar }: { conversacion: Conversacion; onHecho: (c: Conversacion) => void; onCancelar: () => void }) {
  const [alcance, setAlcance] = useState<'whatsapp' | 'todos'>('whatsapp');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function confirmar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      onHecho(await optOutConversacion(c.id, alcance));
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }
  return (
    <form onSubmit={confirmar} className="tarjeta formulario" aria-label="Registrar baja del cliente">
      <h3>Registrar baja (opt-out)</h3>
      <p>El cliente pidió no recibir más mensajes. Se excluirá el número, se revocarán sus autorizaciones y se cerrará la conversación.</p>
      <Campo etiqueta="Alcance de la baja">
        {(p) => (
          <select {...p} value={alcance} onChange={(e) => setAlcance(e.target.value as 'whatsapp' | 'todos')}>
            <option value="whatsapp">Solo WhatsApp</option>
            <option value="todos">Todos los canales (también llamadas)</option>
          </select>
        )}
      </Campo>
      <MensajeError error={error} />
      <div className="acciones">
        <button type="submit" className="peligro" disabled={enviando}>{enviando ? 'Registrando…' : 'Confirmar baja'}</button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}

function Autorizacion({ conversacion: c, onHecho, onCancelar }: { conversacion: Conversacion; onHecho: () => void; onCancelar: () => void }) {
  const [finalidad, setFinalidad] = useState<Finalidad>(c.campana?.tipo ?? 'todas');
  const [evidencia, setEvidencia] = useState('');
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const ev = evidencia.trim();
    if (ev.length < 5 || ev.length > 500) {
      setErrLocal('La evidencia debe tener entre 5 y 500 caracteres.');
      return;
    }
    setErrLocal(undefined);
    setEnviando(true);
    try {
      await autorizarConversacion(c.id, { finalidad, evidencia: ev });
      onHecho();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }
  return (
    <form onSubmit={enviar} noValidate className="tarjeta formulario" aria-label="Registrar autorización del cliente">
      <h3>Registrar autorización (opt-in)</h3>
      <p>Registre que el cliente aceptó recibir mensajes por WhatsApp en esta conversación.</p>
      <Campo etiqueta="Finalidad" error={error?.detalleDe('finalidad')}>
        {(p) => (
          <select {...p} value={finalidad} onChange={(e) => setFinalidad(e.target.value as Finalidad)}>
            {(Object.keys(ETIQUETA_FINALIDAD) as Finalidad[]).map((f) => (
              <option key={f} value={f}>{ETIQUETA_FINALIDAD[f]}</option>
            ))}
          </select>
        )}
      </Campo>
      <Campo etiqueta="Evidencia" error={errLocal ?? error?.detalleDe('evidencia')} ayuda="Describa cómo consta la autorización. No incluya datos personales.">
        {(p) => <textarea {...p} rows={2} maxLength={500} value={evidencia} onChange={(e) => setEvidencia(e.target.value)} />}
      </Campo>
      <MensajeError error={error} camposMostrados={['finalidad', 'evidencia']} />
      <div className="acciones">
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Registrando…' : 'Registrar autorización'}</button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}
