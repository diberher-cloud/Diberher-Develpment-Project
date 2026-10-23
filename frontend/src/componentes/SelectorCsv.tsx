import { useState, type ChangeEvent } from 'react';
import { Campo } from './Campo';
import { validarArchivoTabla } from '../utilidades/formato';

interface Props {
  etiqueta: string;
  archivo: File | null;
  onCambiar: (archivo: File | null) => void;
  /** Se cambia para forzar el vaciado del input tras un envío correcto. */
  clave?: number;
}

/** Input de archivo .csv o .xlsx; valida extensión y tamaño (10 MiB) antes de aceptar el archivo. */
export function SelectorCsv({ etiqueta, archivo, onCambiar, clave }: Props) {
  const [error, setError] = useState<string | undefined>();

  function alCambiar(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setError(undefined);
      onCambiar(null);
      return;
    }
    const msg = validarArchivoTabla(f);
    setError(msg ?? undefined);
    onCambiar(msg ? null : f);
  }

  return (
    <Campo etiqueta={etiqueta} error={error} ayuda="Archivo .csv o .xlsx de hasta 10 MiB.">
      {(p) => <input {...p} key={clave} type="file" accept=".csv,.xlsx" onChange={alCambiar} data-seleccionado={archivo ? archivo.name : ''} />}
    </Campo>
  );
}
