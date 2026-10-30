import { Link } from 'react-router-dom';
import type { CodigoRequisitoIA, Motivo } from '../../api/tipos';

interface Props {
  campanaId: number;
  faltantes: Motivo<CodigoRequisitoIA>[];
  /** Cambia a otra pestaña del detalle de la campaña (p. ej. "agentes"). */
  onIrAPestana?: (pestana: 'agentes') => void;
}

/** Requisitos que faltan para activar la IA, con el enlace a donde se resuelven. */
export function RequisitosActivacion({ campanaId, faltantes, onIrAPestana }: Props) {
  if (faltantes.length === 0) return null;
  return (
    <section aria-labelledby="t-requisitos" className="alerta alerta-error">
      <h3 id="t-requisitos">Requisitos pendientes para activar la IA</h3>
      <ul>
        {faltantes.map((f) => (
          <li key={f.codigo}>
            {f.mensaje}{' '}
            <EnlaceRequisito codigo={f.codigo} campanaId={campanaId} onIrAPestana={onIrAPestana} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function EnlaceRequisito({ codigo, campanaId, onIrAPestana }: { codigo: CodigoRequisitoIA; campanaId: number; onIrAPestana?: Props['onIrAPestana'] }) {
  switch (codigo) {
    case 'EVALUACION_OFFLINE_PENDIENTE':
    case 'EVALUACION_ONLINE_PENDIENTE':
      return <Link to="/ia/evaluaciones">Ir a las evaluaciones</Link>;
    case 'SIN_AGENTES_ASIGNADOS':
      return onIrAPestana ? (
        <button type="button" className="enlace" onClick={() => onIrAPestana('agentes')}>Asignar agentes</button>
      ) : null;
    case 'SIN_OFERTAS_ACTIVAS':
      return (
        <button
          type="button"
          className="enlace"
          onClick={() => {
            const el = document.getElementById('t-ofertas');
            el?.scrollIntoView?.();
            el?.focus();
          }}
        >
          Ir a las ofertas
        </button>
      );
    case 'WHATSAPP_NO_HABILITADO':
      return <Link to={`/campanas/${campanaId}/editar`}>Editar la campaña</Link>;
    case 'IA_GLOBAL_DESACTIVADA':
      return <Link to="/supervision/ia">Ir a la supervisión de IA</Link>;
    default:
      return null;
  }
}
