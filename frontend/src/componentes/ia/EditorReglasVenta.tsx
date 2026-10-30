import { Campo } from '../Campo';
import type { FormVenta } from '../../utilidades/ia';

interface Props {
  valor: FormVenta;
  onCambio: (v: FormVenta) => void;
  error: (campo: string) => string | undefined;
  deshabilitado: boolean;
}

export function EditorReglasVenta({ valor, onCambio, error, deshabilitado }: Props) {
  return (
    <fieldset disabled={deshabilitado}>
      <legend>Reglas de venta</legend>
      <Campo etiqueta="Unidades máximas por venta" error={error('reglas.max_unidades_por_venta')}>
        {(p) => (
          <input {...p} type="number" min={1} max={100} inputMode="numeric" value={valor.max_unidades_por_venta}
            onChange={(e) => onCambio({ ...valor, max_unidades_por_venta: e.target.value })} />
        )}
      </Campo>
      <label>
        <input type="checkbox" checked={valor.requiere_aceptacion_terminos}
          onChange={(e) => onCambio({ ...valor, requiere_aceptacion_terminos: e.target.checked })} />{' '}
        Exigir aceptación expresa de los términos antes de registrar la venta
      </label>
    </fieldset>
  );
}
