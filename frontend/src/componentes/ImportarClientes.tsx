import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { subirImportacion } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Importacion } from '../api/tipos';
import { comoErrorApi } from '../utilidades/useCarga';
import { MensajeError } from './MensajeError';
import { ContadoresImportacion, TablaErroresImportacion } from './ResumenImportacion';
import { SelectorCsv } from './SelectorCsv';

interface Props {
  campanaId: number;
  onImportada: () => void;
}

export function ImportarClientes({ campanaId, onImportada }: Props) {
  const [archivo, setArchivo] = useState<File | null>(null);
  const [clave, setClave] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [resultado, setResultado] = useState<Importacion | null>(null);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (!archivo) return;
    setEnviando(true);
    setError(null);
    setResultado(null);
    try {
      const r = await subirImportacion(campanaId, archivo);
      setResultado(r);
      setArchivo(null);
      setClave((c) => c + 1);
      onImportada();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-importar">
      <h2 id="t-importar">Importar clientes desde CSV</h2>
      <form onSubmit={enviar} className="formulario">
        <SelectorCsv etiqueta="Archivo CSV de clientes" archivo={archivo} onCambiar={setArchivo} clave={clave} />
        <MensajeError error={error} />
        <button type="submit" className="primario" disabled={!archivo || enviando}>
          {enviando ? 'Importando…' : 'Importar'}
        </button>
      </form>
      {resultado && (
        <div role="status" className="alerta alerta-ok">
          <h3>Resultado de la importación #{resultado.id}</h3>
          <ContadoresImportacion i={resultado} />
          {resultado.errores_truncados && (
            <p>
              Se muestran solo los primeros 100 errores. <Link to={`/importaciones/${resultado.id}`}>Ver el detalle completo</Link>.
            </p>
          )}
          <TablaErroresImportacion errores={resultado.errores ?? []} />
        </div>
      )}
    </section>
  );
}
