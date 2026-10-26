import { useState, type FormEvent } from 'react';
import { listarMensajes, simularEntranteWhatsApp, simularEstadoMensaje } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Mensaje, SimulacionEntrante } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { useWhatsApp } from '../componentes/ContextoWhatsApp';
import { MensajeError } from '../componentes/MensajeError';
import { comoErrorApi } from '../utilidades/useCarga';
import { textoEstadoMensaje } from '../utilidades/whatsapp';

const ADJUNTOS = [
  { valor: '', texto: 'Sin adjunto' },
  { valor: 'image/png', texto: 'Imagen (PNG)' },
  { valor: 'audio/ogg', texto: 'Audio (OGG)' },
  { valor: 'application/pdf', texto: 'Documento (PDF)' },
  { valor: 'video/mp4', texto: 'Vídeo (no soportado)' },
];
const ESTADOS = [
  { valor: 'delivered', texto: 'Entregado' },
  { valor: 'read', texto: 'Leído' },
  { valor: 'failed', texto: 'Fallido' },
  { valor: 'undelivered', texto: 'No entregado' },
] as const;
type EstadoSim = (typeof ESTADOS)[number]['valor'];

/** Simulador de WhatsApp: solo está disponible cuando el servidor expone la simulación (proveedor falso, no producción). */
export function SimuladorWhatsApp() {
  const { configuracion } = useWhatsApp();
  if (!configuracion) {
    return (
      <section aria-labelledby="t-sim">
        <h1 id="t-sim">Simulador de WhatsApp</h1>
        <p role="status">Cargando la configuración…</p>
      </section>
    );
  }
  if (!configuracion.simulacion) {
    return (
      <section aria-labelledby="t-sim">
        <h1 id="t-sim">Simulador de WhatsApp</h1>
        <p role="alert" className="alerta alerta-error">
          La simulación no está habilitada en este entorno (solo con el proveedor falso y fuera de producción).
        </p>
      </section>
    );
  }
  return (
    <section aria-labelledby="t-sim">
      <h1 id="t-sim">Simulador de WhatsApp</h1>
      <p className="ayuda">
        Entorno de pruebas sin Twilio. Los mensajes simulados los procesa el worker, que debe estar en ejecución.
        Número de la empresa: {configuracion.numero_empresa_mascara}.
      </p>
      <EntranteSimulado />
      <EstadosSimulados />
    </section>
  );
}

const CAMPOS_ENTRANTE = ['numero', 'texto', 'nombre_perfil', 'media', 'boton_payload'];

function EntranteSimulado() {
  const [numero, setNumero] = useState('');
  const [texto, setTexto] = useState('');
  const [perfil, setPerfil] = useState('');
  const [adjunto, setAdjunto] = useState('');
  const [baja, setBaja] = useState(false);
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    if (!numero.trim()) {
      setErrLocal('Ingrese el número del cliente.');
      return;
    }
    setErrLocal(undefined);
    const cuerpo: SimulacionEntrante = { numero: numero.trim(), texto: texto || null, nombre_perfil: perfil.trim() || null };
    if (adjunto) cuerpo.media = [{ tipo_contenido: adjunto }];
    if (baja) {
      cuerpo.boton_payload = 'BAJA';
      cuerpo.boton_texto = 'Darme de baja';
    }
    setEnviando(true);
    try {
      const r = await simularEntranteWhatsApp(cuerpo);
      setOk(`Mensaje simulado recibido (id ${r.mensaje_id}). Lo procesará el worker.`);
      setTexto('');
      setAdjunto('');
      setBaja(false);
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-sim-entrante">
      <h2 id="t-sim-entrante">Enviar como cliente</h2>
      <form onSubmit={enviar} noValidate className="formulario">
        <div className="fila-campos">
          <Campo etiqueta="Número del cliente" error={errLocal ?? error?.detalleDe('numero')} ayuda="Cualquier formato, p. ej. 300 123 4567.">
            {(p) => <input {...p} value={numero} onChange={(e) => setNumero(e.target.value)} inputMode="tel" required />}
          </Campo>
          <Campo etiqueta="Nombre de perfil (opcional)" error={error?.detalleDe('nombre_perfil')}>
            {(p) => <input {...p} value={perfil} maxLength={100} onChange={(e) => setPerfil(e.target.value)} />}
          </Campo>
        </div>
        <Campo etiqueta="Texto del mensaje" error={error?.detalleDe('texto')}>
          {(p) => <textarea {...p} rows={3} value={texto} onChange={(e) => setTexto(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Adjunto simulado" error={error?.detalleDe('media')}>
          {(p) => (
            <select {...p} value={adjunto} onChange={(e) => setAdjunto(e.target.value)}>
              {ADJUNTOS.map((a) => (
                <option key={a.valor} value={a.valor}>{a.texto}</option>
              ))}
            </select>
          )}
        </Campo>
        <div className="campo">
          <label>
            <input type="checkbox" checked={baja} onChange={(e) => setBaja(e.target.checked)} /> Pulsar el botón «Darme de baja»
          </label>
        </div>
        <MensajeError error={error} camposMostrados={CAMPOS_ENTRANTE} />
        {ok && <p role="status" className="alerta alerta-ok">{ok}</p>}
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Enviando…' : 'Enviar mensaje del cliente'}</button>
      </form>
    </section>
  );
}

function EstadosSimulados() {
  const [conversacion, setConversacion] = useState('');
  const [salientes, setSalientes] = useState<Mensaje[] | null>(null);
  const [errorCarga, setErrorCarga] = useState<ErrorApi | null>(null);
  const [cargando, setCargando] = useState(false);

  async function cargar(e: FormEvent) {
    e.preventDefault();
    const id = Number(conversacion);
    if (!Number.isInteger(id) || id <= 0) {
      setErrorCarga(null);
      setSalientes(null);
      return;
    }
    setErrorCarga(null);
    setCargando(true);
    try {
      const p = await listarMensajes(id, { limite: 100 });
      setSalientes(p.items.filter((m) => m.direccion === 'saliente'));
    } catch (err) {
      setErrorCarga(comoErrorApi(err));
      setSalientes(null);
    } finally {
      setCargando(false);
    }
  }

  return (
    <section aria-labelledby="t-sim-estado">
      <h2 id="t-sim-estado">Cambiar el estado de los mensajes salientes</h2>
      <p className="ayuda">Solo se pueden cargar conversaciones que usted atiende (o que puede ver como administrador o supervisor).</p>
      <form onSubmit={cargar} className="filtros">
        <Campo etiqueta="Número de la conversación">
          {(p) => <input {...p} inputMode="numeric" value={conversacion} onChange={(e) => setConversacion(e.target.value)} />}
        </Campo>
        <button type="submit" disabled={cargando}>{cargando ? 'Cargando…' : 'Cargar salientes'}</button>
      </form>
      <MensajeError error={errorCarga} />
      {salientes && salientes.length === 0 && <p>La conversación no tiene mensajes salientes.</p>}
      {salientes && salientes.length > 0 && (
        <ul className="lista-simple">
          {salientes.map((m) => (
            <FilaSaliente key={m.id} mensaje={m} />
          ))}
        </ul>
      )}
    </section>
  );
}

function FilaSaliente({ mensaje: m }: { mensaje: Mensaje }) {
  const [estado, setEstado] = useState<EstadoSim>('delivered');
  const [codigo, setCodigo] = useState('63016');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const falla = estado === 'failed' || estado === 'undelivered';

  async function aplicar() {
    setError(null);
    setOk(false);
    setEnviando(true);
    try {
      await simularEstadoMensaje(m.id, { estado, ...(falla ? { error_codigo: codigo.trim() || null } : {}) });
      setOk(true);
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  const resumen = m.cuerpo ? `${m.cuerpo.slice(0, 60)}${m.cuerpo.length > 60 ? '…' : ''}` : m.plantilla?.nombre ?? '(sin texto)';
  return (
    <li className="tarjeta">
      <p>
        <strong>Mensaje {m.id}</strong>: {resumen} — {textoEstadoMensaje(m)}
      </p>
      <div className="filtros">
        <Campo etiqueta={`Nuevo estado del mensaje ${m.id}`}>
          {(p) => (
            <select {...p} value={estado} onChange={(e) => setEstado(e.target.value as EstadoSim)}>
              {ESTADOS.map((x) => (
                <option key={x.valor} value={x.valor}>{x.texto}</option>
              ))}
            </select>
          )}
        </Campo>
        {falla && (
          <Campo etiqueta={`Código de error del mensaje ${m.id}`}>
            {(p) => <input {...p} value={codigo} maxLength={30} onChange={(e) => setCodigo(e.target.value)} />}
          </Campo>
        )}
        <button type="button" disabled={enviando} onClick={() => void aplicar()}>
          Aplicar estado<span className="solo-lectura"> al mensaje {m.id}</span>
        </button>
      </div>
      <MensajeError error={error} />
      {ok && <p role="status" className="alerta alerta-ok">Estado aplicado.</p>}
    </li>
  );
}
