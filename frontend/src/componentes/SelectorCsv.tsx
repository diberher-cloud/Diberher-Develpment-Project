import { useState, type ChangeEvent } from 'react';
import { Campo } from './Campo';
import { validarArchivoCsv } from '../utilidades/formato';

interface Props {
  etiqueta: string;
  archivo: File | null;
  onCambiar: (archivo: File | null) => void;
  /** Se cambia para forzar el vaciado del input tras un envío correcto. */
  clave?: number;
}

/** Input de archivo .csv; valida extensión y tamaño (10 MiB) antes de aceptar el archivo. */
export function SelectorCsv({ etiqueta, archivo, onCambiar, clave }: Props) {
  const [error, setError] = useState<string | undefined>();

  function alCambiar(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setError(undefined);
      onCambiar(null);
      return;
    }
    const msg = validarArchivoCsv(f);
    setError(msg ?? undefined);
    onCambiar(msg ? null : f);
  }

  return (
    <Campo etiqueta={etiqueta} error={error} ayuda="Archivo .csv de hasta 10 MiB.">
      {(p) => <input {...p} key={clave} type="file" accept=".csv" onChange={alCambiar} data-seleccionado={archivo ? archivo.name : ''} />}
    </Campo>
  );
}
