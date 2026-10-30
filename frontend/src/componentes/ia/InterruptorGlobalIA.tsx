import { useCallback, useState } from 'react';
import { guardarConfiguracionGlobalIA, obtenerConfiguracionGlobalIA } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import { useAuth } from '../../auth/AuthContext';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { ConfirmacionIA } from './ConfirmacionIA';

/** Kill switch global: el administrador lo conmuta (con confirmación); el supervisor solo lo ve. */
export function InterruptorGlobalIA() {
  const { tieneRol } = useAuth();
  const esAdmin = tieneRol('administrador');
  const { reconexiones } = useConexionTiempoReal();
  const cargador = useCallback(() => {
    void reconexiones;
    return obtenerConfiguracionGlobalIA();
  }, [reconexiones]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const [confirmando, setConfirmando] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [errAccion, setErrAccion] = useState<ErrorApi | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [actual, setActual] = useState<boolean | null>(null);

  useEventoTiempoReal('ia.configuracion', (e) => {
    if (e.tipo === 'ia.configuracion' && e.datos.campana_id === null) recargar();
  });

  const activa = actual ?? datos?.ia_activa ?? null;

  async function conmutar() {
    if (activa === null) return;
    setErrAccion(null);
    setOcupado(true);
    try {
      const g = await guardarConfiguracionGlobalIA(!activa);
      setActual(g.ia_activa);
      setAviso(g.ia_activa ? 'IA global activada.' : 'IA global desactivada: las conversaciones atendidas por la IA pasan a la cola humana.');
      recargar();
    } catch (e) {
      setErrAccion(comoErrorApi(e));
    } finally {
      setOcupado(false);
      setConfirmando(false);
    }
  }

  return (
    <section aria-labelledby="t-global-ia" className="tarjeta">
      <h2 id="t-global-ia">Interruptor global de la IA</h2>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && activa !== null && (
        <>
          <p>
            <span className={`insignia ${activa && datos.ia_habilitada_entorno ? 'estado-activa' : 'insignia-error'}`}>
              {!datos.ia_habilitada_entorno ? 'IA deshabilitada por configuración' : activa ? 'IA global activa' : 'IA global desactivada'}
            </span>
            {' '}Proveedor: {datos.proveedor === 'anthropic' ? 'Anthropic' : 'de pruebas (falso)'}.
            {datos.actualizado_por ? ` Último cambio: ${datos.actualizado_por.nombre}, ${formatearFechaHora(datos.actualizado_en)}.` : ''}
          </p>
          {!datos.ia_habilitada_entorno && (
            <p className="ayuda">El entorno del servidor tiene la IA deshabilitada (IA_HABILITADA=false); este interruptor no la reactiva.</p>
          )}
          {esAdmin ? (
            <div className="acciones">
              <button type="button" className={activa ? 'peligro' : 'primario'} disabled={confirmando || ocupado} onClick={() => { setAviso(null); setConfirmando(true); }}>
                {activa ? 'Desactivar la IA en toda la plataforma' : 'Activar la IA global'}
              </button>
            </div>
          ) : (
            <p className="ayuda">Solo un administrador puede cambiar el interruptor global.</p>
          )}
          {confirmando && (
            <ConfirmacionIA
              titulo={activa ? '¿Desactivar la IA en toda la plataforma?' : '¿Activar la IA global?'}
              textoConfirmar={activa ? 'Confirmar desactivación global' : 'Confirmar activación global'}
              peligro={activa}
              ocupado={ocupado}
              onConfirmar={() => void conmutar()}
              onCancelar={() => setConfirmando(false)}
            >
              <p>
                {activa
                  ? 'Todas las conversaciones atendidas por la IA, de todas las campañas, pasarán a la cola de atención humana.'
                  : 'La IA podrá volver a atender las campañas que la tengan activa.'}
              </p>
            </ConfirmacionIA>
          )}
        </>
      )}
      <MensajeError error={errAccion} />
      {aviso && <p role="status" className="alerta alerta-ok">{aviso}</p>}
    </section>
  );
}
