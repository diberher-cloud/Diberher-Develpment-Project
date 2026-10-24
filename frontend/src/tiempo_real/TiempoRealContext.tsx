import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { obtenerTicketWs } from '../api/endpoints';
import { leerSesion, limpiarSesion } from '../api/sesion';
import type { EventoTiempoReal } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { conectar, type EstadoConexion } from './conexion';

type TipoEvento = EventoTiempoReal['tipo'];
type Oyente = (evento: EventoTiempoReal) => void;

interface ValorTiempoReal {
  estado: EstadoConexion;
  /** Se incrementa en cada reconexión: los consumidores recargan su estado por REST. */
  reconexiones: number;
  suscribir: (oyente: Oyente) => () => void;
}

const TiempoRealContext = createContext<ValorTiempoReal | null>(null);

/** Abre el WebSocket mientras haya sesión. Debe ir dentro de <AuthProvider>. */
export function TiempoRealProvider({ children }: { children: ReactNode }) {
  const { usuario } = useAuth();
  const [estado, setEstado] = useState<EstadoConexion>('cerrada');
  const [reconexiones, setReconexiones] = useState(0);
  const oyentes = useRef(new Set<Oyente>());
  const usuarioId = usuario?.id;

  useEffect(() => {
    const sesion = leerSesion();
    if (usuarioId === undefined || !sesion) {
      setEstado('cerrada');
      return;
    }
    const conexion = conectar({
      obtenerTicket: obtenerTicketWs,
      alEvento: (e) => oyentes.current.forEach((o) => o(e)),
      alEstado: setEstado,
      alReconectar: () => setReconexiones((n) => n + 1),
      alSesionInvalida: () => limpiarSesion(),
    });
    return () => conexion.cerrar();
  }, [usuarioId]);

  const suscribir = useCallback((o: Oyente) => {
    oyentes.current.add(o);
    return () => {
      oyentes.current.delete(o);
    };
  }, []);
  const valor = useMemo<ValorTiempoReal>(() => ({ estado, reconexiones, suscribir }), [estado, reconexiones, suscribir]);
  return <TiempoRealContext.Provider value={valor}>{children}</TiempoRealContext.Provider>;
}

/** Estado de la conexión y contador de reconexiones (sin proveedor: cerrada). */
export function useConexionTiempoReal(): { estado: EstadoConexion; reconexiones: number } {
  const ctx = useContext(TiempoRealContext);
  return { estado: ctx?.estado ?? 'cerrada', reconexiones: ctx?.reconexiones ?? 0 };
}

/** Ejecuta `manejador` por cada evento de los tipos indicados. Sin proveedor no hace nada. */
export function useEventoTiempoReal(tipos: TipoEvento | TipoEvento[], manejador: (evento: EventoTiempoReal) => void): void {
  const ctx = useContext(TiempoRealContext);
  const ref = useRef(manejador);
  useEffect(() => {
    ref.current = manejador;
  });
  const clave = Array.isArray(tipos) ? tipos.join('|') : tipos;
  const suscribir = ctx?.suscribir;
  useEffect(() => {
    if (!suscribir) return;
    const lista = clave.split('|');
    return suscribir((e) => {
      if (lista.includes(e.tipo)) ref.current(e);
    });
  }, [suscribir, clave]);
}
