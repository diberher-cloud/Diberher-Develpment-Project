import { Campo } from '../Campo';
import { MAX_TEXTO_RETRACTO, type FormVenta } from '../../utilidades/ia';

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
      <Campo
        etiqueta="Texto de retracto"
        ayuda={`Texto legal del derecho de retracto que se incluirá en la constancia de cada venta. Si lo deja vacío se usa el texto global del servidor. ${valor.texto_retracto.length}/${MAX_TEXTO_RETRACTO} caracteres.`}
        error={error('reglas.texto_retracto')}
      >
        {(p) => (
          <textarea {...p} name="texto_retracto" rows={3} value={valor.texto_retracto}
            onChange={(e) => onCambio({ ...valor, texto_retracto: e.target.value })} />
        )}
      </Campo>
    </fieldset>
  );
}
