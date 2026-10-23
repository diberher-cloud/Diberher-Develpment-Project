import { useId, type ReactNode } from 'react';

interface PropsInput {
  id: string;
  'aria-invalid'?: boolean;
  'aria-describedby'?: string;
}

interface Props {
  etiqueta: string;
  error?: string;
  ayuda?: string;
  children: (props: PropsInput) => ReactNode;
}

/** Etiqueta + control + mensaje de error asociado (role="alert"). */
export function Campo({ etiqueta, error, ayuda, children }: Props) {
  const id = useId();
  const idMsg = `${id}-msg`;
  const idAyuda = `${id}-ayuda`;
  const describedby = [error ? idMsg : '', ayuda ? idAyuda : ''].filter(Boolean).join(' ') || undefined;
  return (
    <div className="campo">
      <label htmlFor={id}>{etiqueta}</label>
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedby })}
      {ayuda && (
        <small id={idAyuda} className="ayuda">
          {ayuda}
        </small>
      )}
      {error && (
        <span id={idMsg} role="alert" className="error-campo">
          {error}
        </span>
      )}
    </div>
  );
}
