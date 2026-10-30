import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { ETIQUETA_ALERTA_IA, textoAlertaIA } from '../../utilidades/ia';
import type { TipoAlertaIA } from '../../api/tipos';

interface Aviso {
  clave: string; tipo: TipoAlertaIA; nivel: 'aviso' | 'critico'; campanaId: number | null; conversacionId: number | null;
}

const MAX_AVISOS = 5;

/**
 * Avisos globales de `ia.alerta` para administrador y supervisor (presupuesto, kill switch, errores…). Los eventos no
 * llevan texto: el mensaje se compone aquí. Los críticos se anuncian como alerta; los demás, como estado.
 */
export function AvisosIA() {
  const { tieneRol } = useAuth();
  const gestor = tieneRol('administrador', 'supervisor');
  const [avisos, setAvisos] = useState<Aviso[]>([]);

  useEventoTiempoReal('ia.alerta', (e) => {
    if (e.tipo !== 'ia.alerta' || !gestor) return;
    const d = e.datos;
    const clave = `${d.tipo}:${d.nivel}:${d.campana_id ?? ''}:${d.conversacion_id ?? ''}`;
    setAvisos((lista) => [
      { clave, tipo: d.tipo, nivel: d.nivel, campanaId: d.campana_id, conversacionId: d.conversacion_id },
      ...lista.filter((a) => a.clave !== clave),
    ].slice(0, MAX_AVISOS));
  });

  if (!gestor || avisos.length === 0) return null;
  return (
    <section className="avisos-ia" aria-label="Avisos de la IA">
      {avisos.map((a) => (
        <div key={a.clave} role={a.nivel === 'critico' ? 'alert' : 'status'} className={`alerta ${a.nivel === 'critico' ? 'alerta-error' : 'alerta-aviso'}`}>
          <p>
            <strong>{ETIQUETA_ALERTA_IA[a.tipo]}{a.nivel === 'critico' ? ' (crítico)' : ''}:</strong>{' '}
            {textoAlertaIA(a.tipo, a.nivel, a.campanaId, a.conversacionId)}{' '}
            <Link to={a.tipo === 'evaluacion_fallida' ? '/ia/evaluaciones' : '/supervision/ia'}>Ver</Link>
          </p>
          <button type="button" onClick={() => setAvisos((l) => l.filter((x) => x.clave !== a.clave))}>
            Descartar<span className="solo-lectura"> aviso: {ETIQUETA_ALERTA_IA[a.tipo]}</span>
          </button>
        </div>
      ))}
    </section>
  );
}
