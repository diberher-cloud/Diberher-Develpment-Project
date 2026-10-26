import { useState } from 'react';
import { Link } from 'react-router-dom';
import { enviarPlantillaConsola } from '../../api/endpoints';
import type { FichaCliente, TelefonoFicha } from '../../api/tipos';
import { SelectorPlantilla } from '../bandeja/SelectorPlantilla';

interface Props {
  ficha: FichaCliente;
  telefono: TelefonoFicha;
  /** Muestra el botón "Enviar plantilla" (solo en la consola del agente, con el registro reservado). */
  permitirEnvio: boolean;
}

/** Estado de WhatsApp de un teléfono de la ficha y envío de plantilla (fase-2b.md §4.6 y §4.13). */
export function WhatsAppTelefonoFicha({ ficha, telefono: t, permitirEnvio }: Props) {
  const [abierto, setAbierto] = useState(false);
  const [enviada, setEnviada] = useState<number | null>(null);
  const w = t.whatsapp;
  if (!w) return null;
  const conv = w.conversacion_abierta;
  const motivos = w.motivos;
  return (
    <div className="whatsapp-telefono">
      <p>
        <span className="insignia">WhatsApp</span>{' '}
        {w.autorizado ? <span className="insignia estado-activa">Autorizado</span> : <span className="insignia insignia-advertencia">Sin autorización</span>}
        {w.excluido && <span className="insignia insignia-error"> Excluido de WhatsApp</span>}
        {conv && (
          <span className="insignia">
            {' '}Conversación abierta ({conv.ventana_abierta ? 'ventana abierta' : 'ventana cerrada'})
          </span>
        )}
      </p>
      {conv && (
        <p>
          <Link to={`/bandeja?conversacion=${conv.id}`}>
            Ir a la conversación<span className="solo-lectura"> de {ficha.cliente.nombre} ({t.numero_mascara})</span>
          </Link>
        </p>
      )}
      {permitirEnvio && (
        <>
          <button
            type="button"
            disabled={!w.enviable}
            aria-expanded={abierto}
            aria-describedby={!w.enviable && motivos.length > 0 ? `wa-motivos-${t.id}` : undefined}
            onClick={() => setAbierto((v) => !v)}
          >
            Enviar plantilla<span className="solo-lectura"> a {t.numero_mascara}</span>
          </button>
          {!w.enviable && motivos.length > 0 && (
            <ul id={`wa-motivos-${t.id}`} className="ayuda">
              {motivos.map((m) => (
                <li key={m.codigo}>{m.mensaje}</li>
              ))}
            </ul>
          )}
          {abierto && w.enviable && (
            <SelectorPlantilla
              campanaId={ficha.campana.id}
              enviar={(plantillaId, clave) =>
                enviarPlantillaConsola(ficha.id, { telefono_id: t.id, plantilla_id: plantillaId, idempotencia_clave: clave })}
              onEnviada={(r) => {
                setAbierto(false);
                setEnviada(r.conversacion_id);
              }}
            />
          )}
          {enviada !== null && (
            <p role="status" className="alerta alerta-ok">
              Plantilla enviada.{' '}
              <Link to={`/bandeja?conversacion=${enviada}`}>
                Ver la conversación en la bandeja<span className="solo-lectura"> ({t.numero_mascara})</span>
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  );
}
