import type { ErrorApi } from '../api/cliente';

interface Props {
  error: ErrorApi | null;
  /** Campos que ya se muestran junto a su input; no se repiten en la lista. */
  camposMostrados?: string[];
  onReintentar?: () => void;
}

export function MensajeError({ error, camposMostrados = [], onReintentar }: Props) {
  if (!error) return null;
  const sueltos = error.detallesSueltos(camposMostrados);
  return (
    <div role="alert" className="alerta alerta-error">
      <p>{error.message}</p>
      {sueltos.length > 0 && (
        <ul>
          {sueltos.map((d, i) => (
            <li key={i}>
              {d.campo ? <strong>{d.campo}: </strong> : null}
              {d.mensaje}
            </li>
          ))}
        </ul>
      )}
      {onReintentar && (
        <button type="button" onClick={onReintentar}>
          Reintentar
        </button>
      )}
    </div>
  );
}
