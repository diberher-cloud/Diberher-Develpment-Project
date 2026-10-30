import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  listarMensajes, marcarLeida, obtenerConversacion, obtenerFichaConversacion,
} from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { CierreConversacion, Conversacion, ConfiguracionWhatsApp, Mensaje, Usuario } from '../../api/tipos';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { useAgrupador } from '../../utilidades/useAgrupador';
import { ETIQUETA_TIPO } from '../../utilidades/campanas';
import { conPunto, formatearFechaHora } from '../../utilidades/formato';
import { useAhora } from '../../utilidades/useAhora';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import {
  ETIQUETA_ATENDIDA_POR, ETIQUETA_MOTIVO_CIERRE, formatearRestante, fusionarMensajes, numeroVisible,
} from '../../utilidades/whatsapp';
import { Cargando } from '../Cargando';
import { FichaCliente } from '../consola/FichaCliente';
import { EstadoIAConversacion } from '../ia/EstadoIAConversacion';
import { PanelAccionesIA } from '../ia/PanelAccionesIA';
import { MensajeError } from '../MensajeError';
import { AccionesConversacion } from './AccionesConversacion';
import { BurbujaMensaje } from './BurbujaMensaje';
import { CompositorMensaje } from './CompositorMensaje';

const LIMITE = 50;

interface Props {
  conversacionId: number;
  usuario: Usuario;
  configuracion: ConfiguracionWhatsApp | null;
  /** La conversación cambió (cola, listas y contador de no leídos deben refrescarse). */
  onCambio: () => void;
  /** Se incrementa cuando una acción externa (cola) cambió esta conversación: fuerza la recarga. */
  recarga?: number;
  /** Supervisión: sin compositor ni marca de lectura (las acciones de gestión siguen disponibles). */
  soloLectura?: boolean;
  /** Se invoca con la conversación cada vez que se carga o se recarga. */
  onConversacion?: (c: Conversacion) => void;
}

export function VistaConversacion({ conversacionId: id, usuario, configuracion, onCambio, recarga = 0, soloLectura = false, onConversacion }: Props) {
  const { reconexiones } = useConexionTiempoReal();
  const [conv, setConv] = useState<Conversacion | null>(null);
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [hayMas, setHayMas] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [cargandoMas, setCargandoMas] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [errorMas, setErrorMas] = useState<ErrorApi | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [fichaVisible, setFichaVisible] = useState(false);
  const contenedor = useRef<HTMLDivElement>(null);
  const cercaDelFondo = useRef(true);
  const alturaPrevia = useRef<number | null>(null);
  const primeraCarga = useRef(true);
  // `apertura=true` (auditoría de la visita) se envía una sola vez por conversación abierta.
  const aperturaPendiente = useRef(true);

  // Carga inicial y recarga tras reconexión del WebSocket (se fusiona con lo ya cargado).
  const cargar = useCallback(async () => {
    const apertura = aperturaPendiente.current;
    aperturaPendiente.current = false;
    try {
      const [c, p] = await Promise.all([obtenerConversacion(id, apertura), listarMensajes(id, { limite: LIMITE })]);
      setConv(c);
      setMensajes((prev) => fusionarMensajes(prev, p.items));
      if (primeraCarga.current) setHayMas(p.hay_mas);
      primeraCarga.current = false;
      setError(null);
    } catch (e) {
      setError(comoErrorApi(e));
    } finally {
      setCargando(false);
    }
  }, [id]);
  useEffect(() => {
    void cargar();
  }, [cargar, reconexiones, recarga]);

  const recargarConversacion = useCallback(async () => {
    try {
      setConv(await obtenerConversacion(id));
    } catch (e) {
      setError(comoErrorApi(e));
    }
  }, [id]);

  const traerRecientes = useCallback(async () => {
    try {
      const p = await listarMensajes(id, { limite: LIMITE });
      setMensajes((prev) => fusionarMensajes(prev, p.items));
    } catch {
      /* el siguiente evento o la reconexión lo recuperan */
    }
  }, [id]);

  // Solo los eventos de ESTA conversación alteran la vista; los demás los atienden las listas.
  // Los eventos se agrupan: una ráfaga produce a lo sumo una recarga de mensajes y una de la conversación.
  const idsCargados = useRef(new Set<number>());
  useEffect(() => {
    idsCargados.current = new Set(mensajes.map((m) => m.id));
  }, [mensajes]);
  const programar = useAgrupador<'conversacion' | 'mensajes'>(600, (claves) => {
    if (claves.has('mensajes')) void traerRecientes();
    if (claves.has('conversacion')) void recargarConversacion();
  });
  useEventoTiempoReal('conversacion.mensaje', (e) => {
    if (e.tipo !== 'conversacion.mensaje' || e.datos.conversacion_id !== id) return;
    programar('mensajes');
    // Un cambio de estado (enviado/entregado/leído) de un mensaje ya cargado no altera la conversación.
    const soloEstado = e.datos.accion === 'estado' && idsCargados.current.has(e.datos.mensaje_id);
    if (!soloEstado) programar('conversacion');
  });
  useEventoTiempoReal('conversacion.estado', (e) => {
    if (e.tipo !== 'conversacion.estado' || e.datos.conversacion_id !== id) return;
    programar('conversacion');
  });
  // Una acción de la IA puede cambiar la gestión, la identidad o el dueño: se recarga la conversación (agrupado).
  useEventoTiempoReal('ia.accion', (e) => {
    if (e.tipo === 'ia.accion' && e.datos.conversacion_id === id) programar('conversacion');
  });
  useEffect(() => {
    if (conv) onConversacion?.(conv);
  }, [conv, onConversacion]);

  const esDueno = !!conv && conv.estado === 'abierta' && conv.atendida_por === 'humano' && conv.usuario_asignado?.id === usuario.id;
  const sinLeer = conv?.mensajes_sin_leer ?? 0;
  useEffect(() => {
    if (soloLectura || !esDueno || sinLeer === 0) return;
    let cancelado = false;
    marcarLeida(id).then(
      () => {
        if (cancelado) return;
        setConv((c) => (c ? { ...c, mensajes_sin_leer: 0 } : c));
        onCambio();
      },
      () => {},
    );
    return () => {
      cancelado = true;
    };
  }, [soloLectura, esDueno, sinLeer, id, onCambio]);

  useLayoutEffect(() => {
    const el = contenedor.current;
    if (!el) return;
    if (alturaPrevia.current !== null) {
      el.scrollTop = el.scrollHeight - alturaPrevia.current;
      alturaPrevia.current = null;
    } else if (cercaDelFondo.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [mensajes]);

  async function cargarAnteriores() {
    if (cargandoMas || !hayMas || mensajes.length === 0) return;
    setErrorMas(null);
    setCargandoMas(true);
    try {
      const p = await listarMensajes(id, { antes_de: mensajes[0].id, limite: LIMITE });
      alturaPrevia.current = contenedor.current?.scrollHeight ?? null;
      setMensajes((prev) => fusionarMensajes(prev, p.items));
      setHayMas(p.hay_mas);
    } catch (e) {
      setErrorMas(comoErrorApi(e));
    } finally {
      setCargandoMas(false);
    }
  }

  function alDesplazar() {
    const el = contenedor.current;
    if (!el) return;
    cercaDelFondo.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (el.scrollTop <= 0 && hayMas) void cargarAnteriores();
  }

  function alActualizar(c: Conversacion) {
    setConv(c);
    onCambio();
  }
  function alCerrar(r: CierreConversacion) {
    setConv(r.conversacion);
    onCambio();
  }
  function alEnviado(m: Mensaje) {
    cercaDelFondo.current = true;
    setMensajes((prev) => fusionarMensajes(prev, [m]));
    onCambio();
  }

  if (cargando) return <Cargando texto="Cargando la conversación…" />;
  if (error && !conv) return <MensajeError error={error} onReintentar={() => { setCargando(true); void cargar(); }} />;
  if (!conv) return null;

  const nombre = conv.cliente_nombre ?? conv.nombre_perfil ?? 'Cliente sin identificar';
  const retenidos = mensajes.filter((m) => m.estado === 'retenido').length;
  return (
    <section aria-labelledby="t-conv" className="vista-conversacion">
      <header>
        <h2 id="t-conv">{nombre}</h2>
        <p className="ayuda">
          {numeroVisible(conv, usuario.rol)}
          {conv.nombre_perfil && conv.cliente_nombre ? ` · perfil de WhatsApp: ${conv.nombre_perfil}` : ''}
          {' · '}
          {conv.campana ? `${conv.campana.nombre} (${ETIQUETA_TIPO[conv.campana.tipo]})` : 'Sin campaña'}
          {' · '}
          {ETIQUETA_ATENDIDA_POR[conv.atendida_por]}
          {conv.usuario_asignado ? `: ${conv.usuario_asignado.nombre}` : ''}
        </p>
        {conv.estado === 'cerrada' && (
          <p className="alerta" role="status">
            {conPunto(
              `Conversación cerrada${conv.motivo_cierre ? ` (${ETIQUETA_MOTIVO_CIERRE[conv.motivo_cierre]})` : ''}` +
                (conv.cerrada_en ? ` el ${formatearFechaHora(conv.cerrada_en)}` : ''),
            )}
          </p>
        )}
      </header>

      <BannerVentana conv={conv} margenSegundos={configuracion?.margen_ventana_segundos ?? 60} retenidos={retenidos} onVencida={() => void recargarConversacion()} />
      {conv.alertas.length > 0 && (
        <ul className="alertas-conversacion" aria-label="Alertas de la conversación">
          {conv.alertas.map((a) => (
            <li key={a.codigo} className="alerta alerta-error">{a.mensaje}</li>
          ))}
        </ul>
      )}
      {aviso && <p role="status" className="alerta alerta-ok">{aviso}</p>}
      <MensajeError error={error} />
      {conv.ia && <EstadoIAConversacion conversacion={conv} mostrarCoste={usuario.rol !== 'agente'} />}
      {soloLectura && esDueno && (
        <p role="status" className="alerta alerta-ok">
          Ahora la atiende usted. <Link to={`/bandeja?conversacion=${conv.id}`}>Abrir en la bandeja</Link> para responder.
        </p>
      )}

      <AccionesConversacion
        conversacion={conv}
        usuario={usuario}
        fichaVisible={fichaVisible}
        onAlternarFicha={() => setFichaVisible((v) => !v)}
        onActualizada={alActualizar}
        onCerrada={alCerrar}
        onAviso={setAviso}
      />
      {fichaVisible && <FichaConversacion id={conv.id} />}
      {conv.ia && (usuario.rol !== 'agente' || esDueno) && <PanelAccionesIA conversacionId={conv.id} abierto={soloLectura} />}

      <div className="mensajes" ref={contenedor} onScroll={alDesplazar} role="log" aria-live="polite" aria-label="Mensajes de la conversación" tabIndex={0}>
        {hayMas && (
          <button type="button" className="cargar-anteriores" disabled={cargandoMas} onClick={() => void cargarAnteriores()}>
            {cargandoMas ? 'Cargando…' : 'Cargar mensajes anteriores'}
          </button>
        )}
        <MensajeError error={errorMas} />
        {mensajes.length === 0 ? (
          <p>Aún no hay mensajes.</p>
        ) : (
          <ul className="lista-simple">
            {mensajes.map((m) => (
              <BurbujaMensaje key={m.id} mensaje={m} />
            ))}
          </ul>
        )}
      </div>

      {conv.estado === 'abierta' && !soloLectura && (
        <CompositorMensaje
          conversacion={conv}
          maxCaracteres={configuracion?.max_caracteres_texto}
          onEnviado={alEnviado}
          onRecargar={() => void recargarConversacion()}
        />
      )}
    </section>
  );
}

function FichaConversacion({ id }: { id: number }) {
  const cargador = useCallback(() => obtenerFichaConversacion(id), [id]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  return (
    <div className="panel-ficha">
      {cargando && !datos && <Cargando texto="Cargando la ficha…" />}
      <MensajeError error={error} onReintentar={recargar} />
      {datos && <FichaCliente ficha={datos} />}
    </div>
  );
}

interface PropsBanner {
  conv: Conversacion;
  margenSegundos: number;
  retenidos: number;
  /** La cuenta atrás local llegó a cero mientras el servidor la daba por abierta: hay que preguntar de nuevo. */
  onVencida: () => void;
}

/** Indicador de la ventana de 24 h. La decisión de responder la toma el servidor (`ventana_abierta`). */
function BannerVentana({ conv, margenSegundos, retenidos, onVencida }: PropsBanner) {
  const ahora = useAhora(1000, conv.estado === 'abierta' && conv.ventana_expira_en !== null);
  const restante = conv.ventana_expira_en ? (new Date(conv.ventana_expira_en).getTime() - ahora) / 1000 : null;
  const vencidaLocal = conv.ventana_abierta && restante !== null && restante <= margenSegundos;
  const avisada = useRef<string | null>(null);
  useEffect(() => {
    if (vencidaLocal && avisada.current !== conv.ventana_expira_en) {
      avisada.current = conv.ventana_expira_en;
      onVencida();
    }
  }, [vencidaLocal, conv.ventana_expira_en, onVencida]);

  if (conv.estado === 'cerrada') return null;
  let texto: string;
  let clase = 'alerta alerta-ok';
  if (conv.ventana_abierta && !vencidaLocal && restante !== null) {
    texto = `Ventana de 24 h abierta: quedan ${formatearRestante(restante)}.`;
  } else if (conv.ventana_abierta && !vencidaLocal) {
    texto = 'Ventana de 24 h abierta.';
  } else {
    clase = 'alerta alerta-error';
    texto = conv.ventana_expira_en === null
      ? 'El cliente aún no ha escrito: solo se pueden enviar plantillas.'
      : 'Ventana de 24 h cerrada: solo plantillas.';
  }
  return (
    <div className={clase}>
      <p>{texto}</p>
      {retenidos > 0 && <p>{retenidos === 1 ? '1 mensaje retenido' : `${retenidos} mensajes retenidos`} hasta la próxima franja permitida.</p>}
    </div>
  );
}
