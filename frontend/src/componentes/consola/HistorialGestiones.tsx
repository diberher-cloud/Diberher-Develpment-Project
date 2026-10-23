import type { GestionHistorial } from '../../api/tipos';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { formatearCOP, formatearFecha, formatearFechaHora } from '../../utilidades/formato';

export function HistorialGestiones({ historial }: { historial: GestionHistorial[] }) {
  return (
    <section aria-labelledby="t-historial" className="tarjeta">
      <h2 id="t-historial">Historial de gestiones</h2>
      {historial.length === 0 ? (
        <p>Este registro aún no tiene gestiones.</p>
      ) : (
        <div className="tabla-scroll">
          <table>
            <caption className="solo-lectura">Gestiones anteriores del registro</caption>
            <thead>
              <tr>
                <th scope="col">Fecha</th><th scope="col">Agente</th><th scope="col">Resultado</th>
                <th scope="col">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {historial.map((h) => (
                <tr key={h.id}>
                  <th scope="row">{formatearFechaHora(h.creado_en)}</th>
                  <td>{h.agente_nombre ?? (h.origen === 'agente_ia' ? 'Agente IA' : 'Sistema')}</td>
                  <td>{ETIQUETA_RESULTADO[h.resultado]}{h.contacto_directo ? ' (contacto directo)' : ''}</td>
                  <td>
                    {h.promesa && <div>Promesa de {formatearCOP(h.promesa.monto)} para el {formatearFecha(h.promesa.fecha_pago)}</div>}
                    {h.venta && <div>Venta de {h.venta.producto} por {formatearCOP(h.venta.valor)}</div>}
                    {h.volver_a_llamar_en && <div>Volver a llamar: {formatearFechaHora(h.volver_a_llamar_en)}</div>}
                    {h.observacion && <div>{h.observacion}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
