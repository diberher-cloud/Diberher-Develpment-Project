import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { listarConversaciones, obtenerConfiguracionWhatsApp } from '../api/endpoints';
import type { ConfiguracionWhatsApp } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { useConexionTiempoReal, useEventoTiempoReal, useTiempoRealMontado } from '../tiempo_real/TiempoRealContext';

interface ValorWhatsApp {
  /** `null` mientras carga o si no está disponible. */
  configuracion: ConfiguracionWhatsApp | null;
  /** Mensajes sin leer de mis conversaciones abiertas. */
  noLeidos: number;
  refrescarNoLeidos: () => void;
}

const Contexto = createContext<ValorWhatsApp>({ configuracion: null, noLeidos: 0, refrescarNoLeidos: () => {} });

/** Configuración de WhatsApp y contador global de no leídos (menú "Bandeja (n)"). Va dentro de <Layout>. */
export function WhatsAppProvider({ children }: { children: ReactNode }) {
  const [configuracion, setConfiguracion] = useState<ConfiguracionWhatsApp | null>(null);
  const [noLeidos, setNoLeidos] = useState(0);
  const [version, setVersion] = useState(0);
  const refrescarNoLeidos = useCallback(() => setVersion((v) => v + 1), []);
  const valor = useMemo(() => ({ configuracion, noLeidos, refrescarNoLeidos }), [configuracion, noLeidos, refrescarNoLeidos]);
  return (
    <Contexto.Provider value={valor}>
      <SondaWhatsApp version={version} alConfiguracion={setConfiguracion} alNoLeidos={setNoLeidos} alEvento={refrescarNoLeidos} />
      {children}
    </Contexto.Provider>
  );
}

export function useWhatsApp(): ValorWhatsApp {
  return useContext(Contexto);
}

interface PropsSonda {
  version: number;
  alConfiguracion: (c: ConfiguracionWhatsApp | null) => void;
  alNoLeidos: (n: number) => void;
  alEvento: () => void;
}

/**
 * Hace las peticiones del contexto. Se monta antes que el contenido de la página para que sus llamadas queden
 * antes que las de la página. Los fallos son silenciosos: es información secundaria del menú.
 */
function SondaWhatsApp({ version, alConfiguracion, alNoLeidos, alEvento }: PropsSonda) {
  const { usuario } = useAuth();
  const { reconexiones } = useConexionTiempoReal();
  // Datos secundarios del menú: solo se piden en la aplicación completa (con tiempo real), no en páginas aisladas.
  const activo = useTiempoRealMontado();
  const usuarioId = usuario?.id;
  const temporizador = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    if (!activo) return;
    let cancelado = false;
    obtenerConfiguracionWhatsApp().then(
      (c) => {
        if (!cancelado && c && typeof c === 'object' && 'proveedor' in c) alConfiguracion(c);
      },
      () => {},
    );
    return () => {
      cancelado = true;
    };
  }, [alConfiguracion, usuarioId, activo]);

  useEffect(() => {
    if (!activo || usuarioId === undefined) return;
    let cancelado = false;
    listarConversaciones({ estado: 'abierta', page_size: 100 }).then(
      (p) => {
        if (cancelado || !p || !Array.isArray(p.items)) return;
        // El agente solo recibe las suyas; administradores y supervisores ven todas, pero solo cuentan las propias.
        alNoLeidos(p.items.filter((c) => c.usuario_asignado?.id === usuarioId).reduce((n, c) => n + c.mensajes_sin_leer, 0));
      },
      () => {},
    );
    return () => {
      cancelado = true;
    };
  }, [alNoLeidos, usuarioId, version, reconexiones, activo]);

  // Varios eventos seguidos se agrupan en una sola recarga.
  useEventoTiempoReal(['conversacion.mensaje', 'conversacion.estado'], () => {
    clearTimeout(temporizador.current);
    temporizador.current = setTimeout(alEvento, 300);
  });
  useEffect(() => () => clearTimeout(temporizador.current), []);
  return null;
}
