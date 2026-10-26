import type { Mensaje } from '../../api/tipos';
import { formatearFechaHora } from '../../utilidades/formato';
import { ETIQUETA_AUTOR, ICONO_ESTADO, textoEstadoMensaje } from '../../utilidades/whatsapp';
import { AdjuntoMedia } from './AdjuntoMedia';

/**
 * Burbuja de un mensaje. El texto del cliente no es confiable: se pinta siempre como texto (React lo escapa) y nunca
 * como HTML.
 */
export function BurbujaMensaje({ mensaje: m }: { mensaje: Mensaje }) {
  const autor = m.autor === 'agente' && m.usuario ? m.usuario.nombre : ETIQUETA_AUTOR[m.autor];
  const saliente = m.direccion === 'saliente';
  const estado = textoEstadoMensaje(m);
  return (
    <li className={`burbuja burbuja-${m.autor} ${saliente ? 'burbuja-saliente' : 'burbuja-entrante'}`}>
      <p className="burbuja-autor">
        <strong>{autor}</strong>
        {m.plantilla && <span className="insignia"> Plantilla: {m.plantilla.nombre}</span>}
      </p>
      {m.tipo === 'no_soportado' && <p className="burbuja-texto">Mensaje de un tipo no soportado.</p>}
      {m.cuerpo && <p className="burbuja-texto">{m.cuerpo}</p>}
      {m.boton && (
        <p className="burbuja-texto">
          Botón: <q>{m.boton.texto ?? m.boton.payload}</q>
        </p>
      )}
      {m.media.map((x) => (
        <AdjuntoMedia key={x.indice} conversacionId={m.conversacion_id} mensajeId={m.id} media={x} />
      ))}
      <p className="burbuja-pie">
        <time dateTime={m.creado_en}>{formatearFechaHora(m.creado_en)}</time>
        {saliente && (
          <span className={m.estado === 'fallido' ? 'estado-fallido' : undefined}>
            {' '}
            <span aria-hidden="true">{ICONO_ESTADO[m.estado]}</span> {estado}
          </span>
        )}
      </p>
    </li>
  );
}
