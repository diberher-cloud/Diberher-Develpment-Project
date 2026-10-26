import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { ColaAtencion } from '../componentes/bandeja/ColaAtencion';
import { ListaConversaciones } from '../componentes/bandeja/ListaConversaciones';
import { VistaConversacion } from '../componentes/bandeja/VistaConversacion';
import { useWhatsApp } from '../componentes/ContextoWhatsApp';
import { useConexionTiempoReal } from '../tiempo_real/TiempoRealContext';

const TEXTO_CONEXION = {
  conectando: 'conectando…', conectada: 'conectado', reconectando: 'reconectando…', cerrada: 'sin conexión',
} as const;

/** Bandeja de chat de WhatsApp para agentes humanos: cola, conversaciones y vista de la conversación abierta. */
export function Bandeja() {
  const { usuario } = useAuth();
  const { configuracion, refrescarNoLeidos } = useWhatsApp();
  const { estado: conexion } = useConexionTiempoReal();
  const [params, setParams] = useSearchParams();
  const [version, setVersion] = useState(0);
  const [recarga, setRecarga] = useState(0);
  const seleccion = Number(params.get('conversacion'));
  const seleccionada = Number.isInteger(seleccion) && seleccion > 0 ? seleccion : null;

  const alCambiar = useCallback(() => {
    setVersion((v) => v + 1);
    refrescarNoLeidos();
  }, [refrescarNoLeidos]);
  // Acciones hechas desde la cola (tomar, asignar): la conversación abierta, si es la misma, debe recargarse.
  const alCambiarDesdeCola = useCallback(() => {
    setRecarga((r) => r + 1);
    alCambiar();
  }, [alCambiar]);
  const abrir = useCallback(
    (id: number) => setParams({ conversacion: String(id) }, { replace: false }),
    [setParams],
  );

  if (!usuario) return null;
  return (
    <section aria-labelledby="t-bandeja">
      <div className="barra-titulo">
        <h1 id="t-bandeja">Bandeja de WhatsApp</h1>
        <span className="ayuda">Tiempo real: {TEXTO_CONEXION[conexion]}</span>
      </div>
      <div className="bandeja">
        <aside className="bandeja-lateral" aria-label="Cola y conversaciones">
          <ColaAtencion usuario={usuario} version={version} onAbrir={abrir} onCambio={alCambiarDesdeCola} />
          <ListaConversaciones usuario={usuario} version={version} seleccionada={seleccionada} onAbrir={abrir} />
        </aside>
        <div className="bandeja-principal">
          {seleccionada === null ? (
            <p className="tarjeta">Seleccione una conversación de la cola o de la lista.</p>
          ) : (
            <VistaConversacion
              key={seleccionada}
              conversacionId={seleccionada}
              usuario={usuario}
              configuracion={configuracion}
              recarga={recarga}
              onCambio={alCambiar}
            />
          )}
        </div>
      </div>
    </section>
  );
}
