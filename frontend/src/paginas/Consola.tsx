import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cambiarEstadoAgente, listarCampanasConsola, obtenerEstadoAgente, obtenerFicha, obtenerLlamada, soltarRegistro,
  tomarRegistro,
} from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type {
  CambioEstadoAgente, EstadoAgente, FichaCliente as Ficha, Llamada, Motivo, Tipificacion,
} from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { BarraLlamada } from '../componentes/consola/BarraLlamada';
import { FichaCliente } from '../componentes/consola/FichaCliente';
import { FormularioTipificacion } from '../componentes/consola/FormularioTipificacion';
import { Guion } from '../componentes/consola/Guion';
import { HistorialGestiones } from '../componentes/consola/HistorialGestiones';
import { ListaTrabajo } from '../componentes/consola/ListaTrabajo';
import { SelectorEstado } from '../componentes/consola/SelectorEstado';
import { MensajeError } from '../componentes/MensajeError';
import { crearSoftphone } from '../telefonia/crearSoftphone';
import { esSimulable, type EstadoSoftphone, type Softphone } from '../telefonia/softphone';
import { useConexionTiempoReal, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { useCarga, comoErrorApi } from '../utilidades/useCarga';
import { ETIQUETA_RESULTADO } from '../utilidades/tipificacion';

const REINTENTOS_ESTADO = 10;
const ESPERA_REINTENTO_MS = 1000;

const TEXTO_CONEXION = {
  conectando: 'conectando…', conectada: 'conectado', reconectando: 'reconectando…', cerrada: 'sin conexión',
} as const;

export function Consola() {
  const { usuario } = useAuth();
  const usuarioId = usuario?.id;
  const { estado: conexion, reconexiones } = useConexionTiempoReal();

  const [estadoAgente, setEstadoAgente] = useState<EstadoAgente | null>(null);
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [llamadaPendiente, setLlamadaPendiente] = useState<Llamada | null>(null);
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);
  const [errorFicha, setErrorFicha] = useState<ErrorApi | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const [softphone, setSoftphone] = useState<Softphone | null>(null);
  const [estadoSoftphone, setEstadoSoftphone] = useState<EstadoSoftphone>('inactivo');
  const [detalleSoftphone, setDetalleSoftphone] = useState<string | undefined>();
  const [errorSoftphone, setErrorSoftphone] = useState<string | null>(null);
  const [motivosWs, setMotivosWs] = useState<Motivo[]>([]);

  const temporizador = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const montado = useRef(true);
  const refrescarLista = useCallback(() => setVersion((v) => v + 1), []);

  const refrescarEstado = useCallback(async (): Promise<EstadoAgente | null> => {
    try {
      const e = await obtenerEstadoAgente();
      if (montado.current) setEstadoAgente(e);
      return e;
    } catch (err) {
      if (montado.current) setErrorAccion(comoErrorApi(err));
      return null;
    }
  }, []);

  // Al terminar una llamada, el servidor puede tardar en pasar al agente a `tipificando` (webhooks de Twilio).
  const sincronizarTrasLlamada = useCallback(() => {
    clearTimeout(temporizador.current);
    const ciclo = async (n: number) => {
      const e = await refrescarEstado();
      if (e?.estado === 'en_llamada' && n < REINTENTOS_ESTADO && montado.current) {
        temporizador.current = setTimeout(() => void ciclo(n + 1), ESPERA_REINTENTO_MS);
      }
    };
    void ciclo(1);
  }, [refrescarEstado]);

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      clearTimeout(temporizador.current);
    };
  }, []);

  // Estado inicial y recarga tras reconexión del WebSocket.
  useEffect(() => {
    void refrescarEstado();
    refrescarLista();
  }, [refrescarEstado, refrescarLista, reconexiones]);

  // Softphone según el proveedor del token.
  useEffect(() => {
    let cancelado = false;
    let sp: Softphone | null = null;
    let baja = () => {};
    crearSoftphone()
      .then(async (s) => {
        if (cancelado) {
          s.destruir();
          return;
        }
        sp = s;
        baja = s.onEstado((estado, detalle) => {
          setEstadoSoftphone(estado);
          setDetalleSoftphone(detalle);
          if (estado === 'finalizada') sincronizarTrasLlamada();
        });
        setSoftphone(s);
        await s.iniciar();
      })
      .catch((e: unknown) => {
        if (!cancelado) setErrorSoftphone(comoErrorApi(e).message);
      });
    return () => {
      cancelado = true;
      baja();
      sp?.destruir();
    };
  }, [sincronizarTrasLlamada]);

  const pendiente = estadoAgente?.tipificacion_pendiente ?? null;
  const pendienteRegistro = pendiente?.campana_cliente_id ?? null;
  const pendienteLlamada = pendiente?.llamada_id ?? null;

  // Con una llamada por tipificar se recupera la ficha del registro (reserva propia) y la llamada.
  useEffect(() => {
    if (pendienteRegistro === null) return;
    let cancelado = false;
    obtenerFicha(pendienteRegistro).then(
      (f) => {
        if (!cancelado) {
          setFicha(f);
          setErrorFicha(null);
        }
      },
      (e: unknown) => {
        if (!cancelado) setErrorFicha(comoErrorApi(e));
      },
    );
    return () => {
      cancelado = true;
    };
  }, [pendienteRegistro]);

  useEffect(() => {
    if (pendienteLlamada === null) {
      setLlamadaPendiente(null);
      return;
    }
    let cancelado = false;
    obtenerLlamada(pendienteLlamada).then(
      (l) => {
        if (!cancelado) setLlamadaPendiente(l);
      },
      () => {
        if (!cancelado) setLlamadaPendiente(null);
      },
    );
    return () => {
      cancelado = true;
    };
  }, [pendienteLlamada]);

  const cargadorCampanas = useCallback(() => {
    void version;
    return listarCampanasConsola();
  }, [version]);
  const { datos: campanas, error: errorCampanas, recargar: recargarCampanas } = useCarga(cargadorCampanas);

  useEventoTiempoReal('agente.estado', (e) => {
    if (e.tipo !== 'agente.estado' || e.datos.usuario_id !== usuarioId) return;
    if (e.datos.estado === 'tipificando') {
      void refrescarEstado();
      return;
    }
    setEstadoAgente({
      estado: e.datos.estado, desde: e.datos.desde, motivo_pausa: e.datos.motivo_pausa,
      llamada_id: e.datos.llamada_id, tipificacion_pendiente: null,
    });
  });
  useEventoTiempoReal('llamada.estado', (e) => {
    if (e.tipo !== 'llamada.estado' || e.datos.usuario_id !== usuarioId) return;
    setMotivosWs(e.datos.estado === 'bloqueada' ? e.datos.motivos : []);
  });
  useEventoTiempoReal('consola.registro', refrescarLista);

  async function cambiarEstado(cambio: CambioEstadoAgente) {
    setErrorAccion(null);
    setAviso(null);
    try {
      setEstadoAgente(await cambiarEstadoAgente(cambio));
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
  }

  async function tomar(id: number) {
    setErrorAccion(null);
    setAviso(null);
    try {
      const f = await tomarRegistro(id);
      setFicha(f);
      setMotivosWs([]);
      setEstadoSoftphone((s) => (s === 'finalizada' || s === 'error' ? 'listo' : s));
      setDetalleSoftphone(undefined);
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
    refrescarLista();
  }

  async function soltar() {
    if (!ficha) return;
    setErrorAccion(null);
    try {
      await soltarRegistro(ficha.id);
      setFicha(null);
      setAviso('Registro liberado.');
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
    refrescarLista();
  }

  function alTipificar(t: Tipificacion) {
    setAviso(
      `Tipificación registrada: ${ETIQUETA_RESULTADO[t.resultado]}.` +
        (t.registro ? ` El registro quedó en estado "${t.registro.estado}".` : ''),
    );
    setFicha(null);
    setLlamadaPendiente(null);
    setMotivosWs([]);
    setEstadoAgente((a) => (a ? { ...a, estado: 'disponible', desde: new Date().toISOString(), llamada_id: null, tipificacion_pendiente: null } : a));
    setEstadoSoftphone((s) => (s === 'finalizada' || s === 'error' ? 'listo' : s));
    void refrescarEstado();
    refrescarLista();
  }

  function llamar(telefonoId: number) {
    if (!ficha || !softphone) return;
    setErrorAccion(null);
    setMotivosWs([]);
    void softphone.llamar({ campana_cliente_id: ficha.id, telefono_id: telefonoId });
  }

  const tipificando = estadoAgente?.estado === 'tipificando' && pendiente !== null;
  const enLlamada = estadoAgente?.estado === 'en_llamada' || estadoSoftphone === 'conectando' || estadoSoftphone === 'en_curso';
  const motivosBloqueo = motivosWs.length ? motivosWs : esSimulable(softphone) ? softphone.motivosBloqueo : [];

  return (
    <section aria-labelledby="t-consola">
      <div className="barra-titulo">
        <h1 id="t-consola">Consola del agente</h1>
        <span className="ayuda">Tiempo real: {TEXTO_CONEXION[conexion]}</span>
      </div>

      <SelectorEstado estado={estadoAgente} onCambiar={cambiarEstado} />
      <MensajeError error={errorAccion} />
      {errorSoftphone && <p role="alert" className="alerta alerta-error">No se pudo iniciar el softphone: {errorSoftphone}</p>}
      {aviso && <p role="status" className="alerta alerta-ok">{aviso}</p>}

      {tipificando && !ficha && (
        <div role="alert" className="alerta alerta-error">
          <p>Tiene una llamada pendiente por tipificar{errorFicha ? ', pero no se pudo cargar la ficha del cliente.' : '. Cargando la ficha…'}</p>
          {errorFicha && (
            <>
              <p>{errorFicha.message}</p>
              <button type="button" onClick={() => pendienteRegistro !== null && void obtenerFicha(pendienteRegistro).then(setFicha, (e: unknown) => setErrorFicha(comoErrorApi(e)))}>
                Reintentar
              </button>
            </>
          )}
        </div>
      )}

      {ficha ? (
        <>
          <div className="acciones">
            <button type="button" disabled={enLlamada || tipificando} onClick={() => void soltar()}>
              Soltar registro<span className="solo-lectura"> de {ficha.cliente.nombre}</span>
            </button>
          </div>
          {tipificando && pendiente ? (
            <FormularioTipificacion
              key={pendiente.llamada_id}
              llamadaId={pendiente.llamada_id}
              tipoCampana={ficha.campana.tipo}
              saldoTotal={ficha.saldo_total}
              estadoLlamada={llamadaPendiente?.estado ?? null}
              onCreada={alTipificar}
            />
          ) : (
            <BarraLlamada
              telefonos={ficha.telefonos}
              softphone={softphone}
              estado={estadoSoftphone}
              detalle={detalleSoftphone}
              agenteDisponible={estadoAgente?.estado === 'disponible'}
              motivosBloqueo={motivosBloqueo}
              onLlamar={llamar}
            />
          )}
          <FichaCliente ficha={ficha} permitirPlantilla={!enLlamada && !tipificando} />
          <Guion guion={ficha.guion} />
          <HistorialGestiones historial={ficha.historial} />
        </>
      ) : (
        <>
          <MensajeError error={errorCampanas} onReintentar={recargarCampanas} />
          <ListaTrabajo campanas={campanas ?? []} version={version} bloqueado={tipificando || enLlamada} onTomar={(id) => void tomar(id)} />
        </>
      )}
    </section>
  );
}
