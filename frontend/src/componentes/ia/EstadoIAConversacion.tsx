import type { Conversacion } from '../../api/tipos';
import { formatearFechaHora } from '../../utilidades/formato';
import { formatearUSD } from '../../utilidades/ia';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { ETIQUETA_MOTIVO_COLA } from '../../utilidades/whatsapp';

/** Quién atiende la conversación y el estado de la IA en ella (identidad, gestión, coste y último traspaso). */
export function EstadoIAConversacion({ conversacion: c, mostrarCoste }: { conversacion: Conversacion; mostrarCoste: boolean }) {
  const ia = c.ia;
  if (!ia) return null;
  const atiende =
    c.atendida_por === 'ia' ? 'Asistente IA'
      : c.atendida_por === 'humano' ? `Agente humano${c.usuario_asignado ? `: ${c.usuario_asignado.nombre}` : ''}`
        : 'Nadie (en cola de atención)';
  return (
    <section aria-labelledby="t-estado-ia-conv" className={`estado-ia ${c.atendida_por === 'ia' ? 'estado-ia-activa' : ''}`}>
      <h3 id="t-estado-ia-conv">Atención con IA</h3>
      <p>
        <strong>Atiende ahora:</strong>{' '}
        <span className={`insignia ${c.atendida_por === 'ia' ? 'insignia-ia' : ''}`}>{atiende}</span>
      </p>
      <ul className="lista-simple datos-ia">
        <li>Identidad: {ia.identidad_verificada ? 'verificada' : 'sin verificar'}</li>
        <li>
          Gestión registrada:{' '}
          {ia.gestion ? ETIQUETA_RESULTADO[ia.gestion.resultado] : 'ninguna'}
        </li>
        <li>Turnos de la IA: {ia.turnos}</li>
        {mostrarCoste && ia.costo_usd !== null && <li>Coste: {formatearUSD(ia.costo_usd, 4)}</li>}
        {ia.modelo && <li>Modelo: {ia.modelo}</li>}
        <li>Aviso de asistente virtual: {ia.aviso_enviado ? 'enviado' : 'pendiente'}</li>
      </ul>
      {ia.ultimo_traspaso && (
        <div className="resumen-traspaso" role="note" aria-label="Último traspaso desde la IA">
          <p>
            <strong>Traspaso desde la IA</strong> ({formatearFechaHora(ia.ultimo_traspaso.creado_en)}):{' '}
            {ETIQUETA_MOTIVO_COLA[ia.ultimo_traspaso.motivo] ?? ia.ultimo_traspaso.motivo}.
          </p>
          {ia.ultimo_traspaso.resumen && <p className="resumen-texto">{ia.ultimo_traspaso.resumen}</p>}
        </div>
      )}
    </section>
  );
}
