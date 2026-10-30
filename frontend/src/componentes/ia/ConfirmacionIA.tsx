import { useEffect, useId, useRef, type ReactNode } from 'react';

interface Props {
  titulo: string;
  children: ReactNode;
  textoConfirmar: string;
  peligro?: boolean;
  ocupado?: boolean;
  onConfirmar: () => void;
  onCancelar: () => void;
}

/** Confirmación en la propia página (sin ventana del navegador): recibe el foco al aparecer. */
export function ConfirmacionIA({ titulo, children, textoConfirmar, peligro = false, ocupado = false, onConfirmar, onCancelar }: Props) {
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="group"
      aria-labelledby={`${id}-t`}
      className={`tarjeta confirmacion ${peligro ? 'confirmacion-peligro' : ''}`}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancelar();
      }}
    >
      <h3 id={`${id}-t`}>{titulo}</h3>
      {children}
      <div className="acciones">
        <button type="button" className={peligro ? 'peligro' : 'primario'} disabled={ocupado} onClick={onConfirmar}>
          {ocupado ? 'Procesando…' : textoConfirmar}
        </button>
        <button type="button" disabled={ocupado} onClick={onCancelar}>Cancelar</button>
      </div>
    </div>
  );
}
