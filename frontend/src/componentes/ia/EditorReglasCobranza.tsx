import { Campo } from '../Campo';
import {
  ETIQUETA_PERIODICIDAD, PERIODICIDADES_PLAN, type FormCobranza,
} from '../../utilidades/ia';

interface Props {
  valor: FormCobranza;
  onCambio: (v: FormCobranza) => void;
  /** Mensaje de error de una ruta de campo (`reglas.max_cuotas`, `reglas.descuento_max_pct_por_cuotas.1.max_cuotas`…). */
  error: (campo: string) => string | undefined;
  deshabilitado: boolean;
}

export function EditorReglasCobranza({ valor, onCambio, error, deshabilitado }: Props) {
  const cambiar = <K extends keyof FormCobranza>(k: K, v: FormCobranza[K]) => onCambio({ ...valor, [k]: v });
  const texto = (k: 'descuento_max_pct' | 'monto_minimo_promesa' | 'monto_minimo_cuota', etiqueta: string, ayuda?: string) => (
    <Campo etiqueta={etiqueta} ayuda={ayuda} error={error(`reglas.${k}`)}>
      {(p) => <input {...p} type="text" inputMode="decimal" value={valor[k]} onChange={(e) => cambiar(k, e.target.value)} />}
    </Campo>
  );
  const entero = (k: 'max_cuotas' | 'plazo_max_dias_primer_pago' | 'plazo_max_dias_total', etiqueta: string, ayuda?: string) => (
    <Campo etiqueta={etiqueta} ayuda={ayuda} error={error(`reglas.${k}`)}>
      {(p) => <input {...p} type="number" min={0} inputMode="numeric" value={valor[k]} onChange={(e) => cambiar(k, e.target.value)} />}
    </Campo>
  );

  function cambiarTramo(i: number, campo: 'max_cuotas' | 'descuento_max_pct', v: string) {
    cambiar('tramos', valor.tramos.map((t, j) => (j === i ? { ...t, [campo]: v } : t)));
  }
  function alternarPeriodicidad(p: (typeof PERIODICIDADES_PLAN)[number]) {
    cambiar('periodicidades', valor.periodicidades.includes(p) ? valor.periodicidades.filter((x) => x !== p) : [...valor.periodicidades, p]);
  }

  return (
    <fieldset disabled={deshabilitado}>
      <legend>Reglas de negociación (cobranza)</legend>
      <div className="fila-campos">
        <Campo etiqueta="Base del descuento" ayuda="Valor sobre el que se calcula el descuento ofrecido.">
          {(p) => (
            <select {...p} value={valor.base_descuento} onChange={(e) => cambiar('base_descuento', e.target.value as FormCobranza['base_descuento'])}>
              <option value="saldo_mora">Saldo en mora</option>
              <option value="saldo_total">Saldo total</option>
            </select>
          )}
        </Campo>
        {texto('descuento_max_pct', 'Descuento máximo general (%)', 'Entre 0 y 100, hasta 2 decimales.')}
        {texto('monto_minimo_promesa', 'Monto mínimo de la promesa (COP)')}
        {texto('monto_minimo_cuota', 'Monto mínimo por cuota (COP)')}
        {entero('max_cuotas', 'Máximo de cuotas', 'Entre 1 y 36.')}
        {entero('plazo_max_dias_primer_pago', 'Plazo máximo del primer pago (días)', 'Entre 0 y 90.')}
        {entero('plazo_max_dias_total', 'Plazo máximo total (días)', 'No menor que el del primer pago; hasta 365.')}
      </div>

      <fieldset>
        <legend>Periodicidades permitidas</legend>
        <ul className="lista-simple">
          {PERIODICIDADES_PLAN.map((p) => (
            <li key={p}>
              <label>
                <input type="checkbox" checked={valor.periodicidades.includes(p)} onChange={() => alternarPeriodicidad(p)} />{' '}
                {ETIQUETA_PERIODICIDAD[p]}
              </label>
            </li>
          ))}
        </ul>
        {error('reglas.periodicidades') && <span role="alert" className="error-campo">{error('reglas.periodicidades')}</span>}
      </fieldset>

      <h3>Descuento máximo por número de cuotas</h3>
      <p className="ayuda">
        Opcional. Cada tramo limita el descuento cuando el acuerdo tiene hasta ese número de cuotas. Los tramos deben ir en orden
        creciente de cuotas, sin superar el máximo de cuotas, y su descuento no puede superar el general.
      </p>
      {valor.tramos.length === 0 && <p>Sin tramos: se aplica solo el descuento máximo general.</p>}
      {valor.tramos.length > 0 && (
        <div className="tabla-scroll">
          <table>
            <caption className="solo-lectura">Tramos de descuento por cuotas</caption>
            <thead>
              <tr>
                <th scope="col">Hasta (cuotas)</th><th scope="col">Descuento máximo (%)</th><th scope="col"><span className="solo-lectura">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {valor.tramos.map((t, i) => {
                const eCuotas = error(`reglas.descuento_max_pct_por_cuotas.${i}.max_cuotas`);
                const ePct = error(`reglas.descuento_max_pct_por_cuotas.${i}.descuento_max_pct`);
                return (
                  <tr key={i}>
                    <td>
                      <Campo etiqueta={`Cuotas del tramo ${i + 1}`} error={eCuotas}>
                        {(p) => <input {...p} type="number" min={1} inputMode="numeric" value={t.max_cuotas} onChange={(e) => cambiarTramo(i, 'max_cuotas', e.target.value)} />}
                      </Campo>
                    </td>
                    <td>
                      <Campo etiqueta={`Descuento del tramo ${i + 1} (%)`} error={ePct}>
                        {(p) => <input {...p} type="text" inputMode="decimal" value={t.descuento_max_pct} onChange={(e) => cambiarTramo(i, 'descuento_max_pct', e.target.value)} />}
                      </Campo>
                    </td>
                    <td>
                      <button type="button" className="peligro" onClick={() => cambiar('tramos', valor.tramos.filter((_, j) => j !== i))}>
                        Quitar<span className="solo-lectura"> tramo {i + 1}</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <button
        type="button"
        onClick={() => cambiar('tramos', [...valor.tramos, { max_cuotas: '', descuento_max_pct: valor.descuento_max_pct }])}
      >
        Añadir tramo
      </button>
    </fieldset>
  );
}
