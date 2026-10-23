import { useState, type FormEvent } from 'react';
import { crearTipificacion } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { EstadoLlamada, ResultadoTipificacion, Tipificacion, TipoCampana } from '../../api/tipos';
import {
  aCuerpoTipificacion, ETIQUETA_RESULTADO, resultadosPermitidos, TIPIFICACION_VACIA, validarTipificacion,
  type ValoresTipificacion,
} from '../../utilidades/tipificacion';
import { formatearCOP } from '../../utilidades/formato';
import { comoErrorApi } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { MensajeError } from '../MensajeError';

interface Props {
  llamadaId: number;
  tipoCampana: TipoCampana;
  saldoTotal: string | null;
  estadoLlamada: EstadoLlamada | null;
  onCreada: (t: Tipificacion) => void;
}

const CAMPOS = ['resultado', 'observacion', 'monto', 'fecha_pago', 'producto', 'valor', 'contacto_directo', 'volver_a_llamar_en'];

export function FormularioTipificacion({ llamadaId, tipoCampana, saldoTotal, estadoLlamada, onCreada }: Props) {
  const [v, setV] = useState<ValoresTipificacion>(TIPIFICACION_VACIA);
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  const permitidos = resultadosPermitidos({ tipoCampana, estadoLlamada });
  const set = <K extends keyof ValoresTipificacion>(k: K, valor: ValoresTipificacion[K]) => setV((x) => ({ ...x, [k]: valor }));
  const msg = (c: string) => errLocal[c] ?? error?.detalleDe(c);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const l = validarTipificacion(v, { tipoCampana, saldoTotal, estadoLlamada });
    setErrLocal(l);
    if (Object.keys(l).length) return;
    setEnviando(true);
    try {
      onCreada(await crearTipificacion(aCuerpoTipificacion(llamadaId, v)));
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  const r: ResultadoTipificacion | '' = v.resultado;
  return (
    <section aria-labelledby="t-tipif" className="tarjeta">
      <h2 id="t-tipif">Tipificar la llamada</h2>
      <p className="alerta alerta-error" role="status">
        Debe tipificar esta llamada antes de tomar otro registro o cambiar de estado.
      </p>
      <form onSubmit={enviar} noValidate className="formulario" aria-label="Formulario de tipificación">
        <Campo etiqueta="Resultado" error={msg('resultado')}>
          {(p) => (
            <select {...p} value={v.resultado} onChange={(e) => set('resultado', e.target.value as ResultadoTipificacion | '')}>
              <option value="">Seleccione…</option>
              {permitidos.map((x) => (
                <option key={x} value={x}>{ETIQUETA_RESULTADO[x]}</option>
              ))}
            </select>
          )}
        </Campo>

        {r === 'promesa_pago' && (
          <div className="fila-campos">
            <Campo
              etiqueta="Monto prometido (COP)"
              error={msg('monto')}
              ayuda={saldoTotal ? `Saldo total de la obligación: ${formatearCOP(saldoTotal)}. Use punto decimal.` : 'Use punto decimal.'}
            >
              {(p) => <input {...p} inputMode="decimal" value={v.montoPromesa} onChange={(e) => set('montoPromesa', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Fecha de pago" error={msg('fecha_pago')}>
              {(p) => <input {...p} type="date" value={v.fechaPago} onChange={(e) => set('fechaPago', e.target.value)} />}
            </Campo>
          </div>
        )}

        {r === 'venta' && (
          <div className="fila-campos">
            <Campo etiqueta="Producto vendido" error={msg('producto')}>
              {(p) => <input {...p} value={v.producto} maxLength={120} onChange={(e) => set('producto', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Valor de la venta (COP)" error={msg('valor')} ayuda="Use punto decimal.">
              {(p) => <input {...p} inputMode="decimal" value={v.valorVenta} onChange={(e) => set('valorVenta', e.target.value)} />}
            </Campo>
          </div>
        )}

        {r === 'volver_a_llamar' && (
          <div className="fila-campos">
            <Campo
              etiqueta="Volver a llamar el (hora de Bogotá)"
              error={msg('volver_a_llamar_en')}
              ayuda="Debe estar dentro de la franja permitida, entre 5 minutos y 30 días desde ahora."
            >
              {(p) => <input {...p} type="datetime-local" value={v.volverALlamarEn} onChange={(e) => set('volverALlamarEn', e.target.value)} />}
            </Campo>
            <Campo etiqueta="¿Hubo contacto directo con el cliente?" error={msg('contacto_directo')}>
              {(p) => (
                <select {...p} value={v.contactoDirecto} onChange={(e) => set('contactoDirecto', e.target.value as ValoresTipificacion['contactoDirecto'])}>
                  <option value="">Seleccione…</option>
                  <option value="si">Sí</option>
                  <option value="no">No</option>
                </select>
              )}
            </Campo>
          </div>
        )}

        <Campo etiqueta="Observación (opcional)" error={msg('observacion')}>
          {(p) => <textarea {...p} rows={3} maxLength={1000} value={v.observacion} onChange={(e) => set('observacion', e.target.value)} />}
        </Campo>
        <MensajeError error={error} camposMostrados={CAMPOS} />
        <button type="submit" className="primario" disabled={enviando}>
          {enviando ? 'Registrando…' : 'Registrar tipificación'}
        </button>
      </form>
    </section>
  );
}
