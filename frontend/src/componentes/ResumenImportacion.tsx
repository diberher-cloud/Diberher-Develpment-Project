import type { ErrorImportacion } from '../api/tipos';

interface Contadores {
  total_filas: number;
  filas_importadas?: number;
  creadas?: number;
  filas_duplicadas?: number;
  duplicadas?: number;
  filas_invalidas?: number;
  invalidas?: number;
  filas_excluidas?: number;
}

export function Contador({ etiqueta, valor }: { etiqueta: string; valor: number }) {
  return (
    <div className="contador">
      <dt>{etiqueta}</dt>
      <dd>{valor}</dd>
    </div>
  );
}

/** Los 5 contadores de una importación de clientes. */
export function ContadoresImportacion({ i }: { i: Contadores }) {
  return (
    <dl className="contadores" aria-label="Resumen de la importación">
      <Contador etiqueta="Total de filas" valor={i.total_filas} />
      <Contador etiqueta="Importadas" valor={i.filas_importadas ?? 0} />
      <Contador etiqueta="Duplicadas" valor={i.filas_duplicadas ?? 0} />
      <Contador etiqueta="Inválidas" valor={i.filas_invalidas ?? 0} />
      <Contador etiqueta="Excluidas" valor={i.filas_excluidas ?? 0} />
    </dl>
  );
}

export function TablaErroresImportacion({ errores }: { errores: ErrorImportacion[] }) {
  if (errores.length === 0) return <p>Sin errores ni advertencias.</p>;
  return (
    <div className="tabla-scroll">
      <table>
        <caption className="solo-lectura">Errores y advertencias de la importación</caption>
        <thead>
          <tr>
            <th scope="col">Fila</th>
            <th scope="col">Severidad</th>
            <th scope="col">Campo</th>
            <th scope="col">Código</th>
            <th scope="col">Mensaje</th>
          </tr>
        </thead>
        <tbody>
          {errores.map((e, idx) => (
            <tr key={idx}>
              <th scope="row">{e.fila}</th>
              <td>
                <span className={`insignia insignia-${e.severidad}`}>{e.severidad === 'error' ? 'Error' : 'Advertencia'}</span>
              </td>
              <td>{e.campo ?? '—'}</td>
              <td>{e.codigo}</td>
              <td>{e.mensaje}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

