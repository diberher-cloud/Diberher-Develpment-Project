import type { FichaCliente as Ficha } from '../../api/tipos';
import { ETIQUETA_TIPO } from '../../utilidades/campanas';
import { ETIQUETA_RESULTADO } from '../../utilidades/tipificacion';
import { conPunto, formatearCOP, formatearFecha, formatearFechaHora } from '../../utilidades/formato';
import { WhatsAppTelefonoFicha } from './WhatsAppTelefonoFicha';

/**
 * Datos del cliente y de la obligación. Los teléfonos se muestran siempre enmascarados. `permitirPlantilla` habilita el
 * envío de plantillas de WhatsApp (consola del agente con el registro reservado).
 */
export function FichaCliente({ ficha: f, permitirPlantilla = false }: { ficha: Ficha; permitirPlantilla?: boolean }) {
  const cobranza = f.campana.tipo === 'cobranza';
  const c = f.cumplimiento;
  return (
    <section aria-labelledby="t-ficha" className="tarjeta">
      <h2 id="t-ficha">Ficha del cliente: {f.cliente.nombre}</h2>
      <dl className="datos">
        <div><dt>Campaña</dt><dd>{f.campana.nombre} ({ETIQUETA_TIPO[f.campana.tipo]})</dd></div>
        <div><dt>Documento</dt><dd>{f.cliente.tipo_documento} {f.cliente.numero_documento}</dd></div>
        <div><dt>Ciudad</dt><dd>{f.cliente.ciudad ?? '—'}</dd></div>
        <div><dt>Correo</dt><dd>{f.cliente.email ?? '—'}</dd></div>
        <div><dt>Intentos</dt><dd>{f.intentos} de {f.max_intentos}</dd></div>
        <div><dt>Último resultado</dt><dd>{f.ultimo_resultado ? ETIQUETA_RESULTADO[f.ultimo_resultado] : '—'}</dd></div>
        <div><dt>Reservado hasta</dt><dd>{formatearFechaHora(f.reservado_hasta)}</dd></div>
        {cobranza ? (
          <>
            <div><dt>Obligación</dt><dd>{f.numero_obligacion ?? '—'}</dd></div>
            <div><dt>Saldo total</dt><dd>{formatearCOP(f.saldo_total)}</dd></div>
            <div><dt>Saldo en mora</dt><dd>{formatearCOP(f.saldo_mora)}</dd></div>
            <div><dt>Días de mora</dt><dd>{f.dias_mora ?? '—'}</dd></div>
            <div><dt>Vencimiento</dt><dd>{formatearFecha(f.fecha_vencimiento)}</dd></div>
          </>
        ) : (
          <>
            <div><dt>Producto</dt><dd>{f.producto ?? '—'}</dd></div>
            <div><dt>Oferta</dt><dd>{f.oferta ?? '—'}</dd></div>
          </>
        )}
        {Object.entries(f.datos_adicionales).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>

      <h3>Teléfonos</h3>
      <ul className="lista-simple" aria-label="Teléfonos del cliente">
        {f.telefonos.map((t) => (
          <li key={t.id}>
            <span>{t.numero_mascara}</span> ({t.tipo_linea === 'movil' ? 'móvil' : 'fijo'}){' '}
            {t.llamable ? (
              <span className="insignia estado-activa">Llamable</span>
            ) : (
              <span className="insignia insignia-error">No llamable</span>
            )}
            {t.excluido && <span className="insignia insignia-error"> Excluido</span>}
            {t.motivos.length > 0 && (
              <ul>
                {t.motivos.map((m) => (
                  <li key={m.codigo}>{m.mensaje}</li>
                ))}
              </ul>
            )}
            <WhatsAppTelefonoFicha ficha={f} telefono={t} permitirEnvio={permitirPlantilla} />
          </li>
        ))}
      </ul>

      <h3>Cumplimiento ahora</h3>
      <div className={`alerta ${c.permitido ? 'alerta-ok' : 'alerta-error'}`}>
        <p>
          {c.permitido ? 'Se puede contactar al cliente ahora.' : 'No se puede contactar al cliente ahora.'}{' '}
          Hora de Bogotá: {conPunto(formatearFechaHora(c.momento_local))}
        </p>
        {c.motivos.length > 0 && (
          <ul>
            {c.motivos.map((m) => (
              <li key={m.codigo}><strong>{m.codigo}</strong>: {m.mensaje}</li>
            ))}
          </ul>
        )}
        {c.proxima_ventana_inicio && <p>Próxima ventana: {conPunto(formatearFechaHora(c.proxima_ventana_inicio))}</p>}
      </div>
    </section>
  );
}
