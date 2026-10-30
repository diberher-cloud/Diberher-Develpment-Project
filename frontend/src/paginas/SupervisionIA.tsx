import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import type { Conversacion } from '../api/tipos';
import { VistaConversacion } from '../componentes/bandeja/VistaConversacion';
import { useWhatsApp } from '../componentes/ContextoWhatsApp';
import { InterruptorGlobalIA } from '../componentes/ia/InterruptorGlobalIA';
import { InstruirIA } from '../componentes/ia/InstruirIA';
import { ListaConversacionesIA } from '../componentes/ia/ListaConversacionesIA';
import { MetricasIA } from '../componentes/ia/MetricasIA';
import { PanelUsoIA } from '../componentes/ia/PanelUsoIA';
import { useConexionTiempoReal } from '../tiempo_real/TiempoRealContext';

const TEXTO_CONEXION = {
  conectando: 'conectando…', conectada: 'conectado', reconectando: 'reconectando…', cerrada: 'sin conexión',
} as const;

/** Supervisión en vivo de las conversaciones atendidas por la IA (A, S). */
export function SupervisionIA() {
  const { usuario } = useAuth();
  const { configuracion } = useWhatsApp();
  const { estado: conexion } = useConexionTiempoReal();
  const [params, setParams] = useSearchParams();
  const [version, setVersion] = useState(0);
  const [convSel, setConvSel] = useState<Conversacion | null>(null);
  const sel = Number(params.get('conversacion'));
  const seleccionada = Number.isInteger(sel) && sel > 0 ? sel : null;

  const alCambiar = useCallback(() => setVersion((v) => v + 1), []);
  const seleccionar = useCallback((id: number) => setParams({ conversacion: String(id) }), [setParams]);
  const alConversacion = useCallback((c: Conversacion) => setConvSel(c), []);

  if (!usuario) return null;
  const detalle = convSel !== null && convSel.id === seleccionada ? convSel : null;
  return (
    <section aria-labelledby="t-sup-ia">
      <div className="barra-titulo">
        <h1 id="t-sup-ia">Supervisión de la IA</h1>
        <span className="ayuda">
          <Link to="/ia/evaluaciones">Evaluaciones de la IA</Link> · Tiempo real: {TEXTO_CONEXION[conexion]}
        </span>
      </div>
      <InterruptorGlobalIA />
      <MetricasIA />
      <div className="bandeja">
        <aside className="bandeja-lateral" aria-label="Conversaciones con IA">
          <ListaConversacionesIA usuario={usuario} seleccionada={seleccionada} onSeleccionar={seleccionar} version={version} />
        </aside>
        <div className="bandeja-principal">
          {seleccionada === null ? (
            <p className="tarjeta">Seleccione una conversación para ver sus mensajes, acciones y coste, e instruir a la IA.</p>
          ) : (
            <>
              <VistaConversacion
                key={seleccionada}
                conversacionId={seleccionada}
                usuario={usuario}
                configuracion={configuracion}
                soloLectura
                onCambio={alCambiar}
                onConversacion={alConversacion}
              />
              <PanelUsoIA key={`uso-${seleccionada}`} conversacionId={seleccionada} version={detalle?.ia?.turnos ?? 0} />
              <InstruirIA
                key={`instr-${seleccionada}`}
                conversacionId={seleccionada}
                habilitada={detalle !== null && detalle.estado === 'abierta' && detalle.atendida_por === 'ia'}
              />
            </>
          )}
        </div>
      </div>
    </section>
  );
}
