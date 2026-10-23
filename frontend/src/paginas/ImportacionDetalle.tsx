import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { listarErroresImportacion, obtenerImportacion } from '../api/endpoints';
import type { Severidad } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { ContadoresImportacion, TablaErroresImportacion } from '../componentes/ResumenImportacion';
import { formatearFechaHora } from '../utilidades/formato';
import { useCarga } from '../utilidades/useCarga';

const TAM = 50;

export function ImportacionDetalle() {
  const id = Number(useParams().id);
  const [severidad, setSeveridad] = useState<Severidad | ''>('');
  const [page, setPage] = useState(1);

  const cargaImp = useCallback(() => obtenerImportacion(id), [id]);
  const imp = useCarga(cargaImp);
  const cargaErr = useCallback(() => listarErroresImportacion(id, { severidad, page, page_size: TAM }), [id, severidad, page]);
  const errs = useCarga(cargaErr);

  if (imp.cargando && !imp.datos) return <Cargando />;
  if (imp.error) return <MensajeError error={imp.error} onReintentar={imp.recargar} />;
  if (!imp.datos) return null;
  const i = imp.datos;

  return (
    <section aria-labelledby="t-imp">
      <p><Link to={`/campanas/${i.campana_id}`}>← Volver a la campaña</Link></p>
      <h1 id="t-imp">Importación #{i.id}</h1>
      <p>
        Archivo <strong>{i.nombre_archivo}</strong> · {formatearFechaHora(i.creado_en)} · estado {i.estado}
      </p>
      <ContadoresImportacion i={i} />

      <h2>Errores y advertencias</h2>
      <Campo etiqueta="Severidad">
        {(p) => (
          <select {...p} value={severidad} onChange={(e) => { setPage(1); setSeveridad(e.target.value as Severidad | ''); }}>
            <option value="">Todas</option>
            <option value="error">Errores</option>
            <option value="advertencia">Advertencias</option>
          </select>
        )}
      </Campo>
      <MensajeError error={errs.error} onReintentar={errs.recargar} />
      {errs.cargando && !errs.datos && <Cargando />}
      {errs.datos && (
        <>
          <TablaErroresImportacion errores={errs.datos.items} />
          {errs.datos.total > 0 && (
            <Paginador page={errs.datos.page} pageSize={errs.datos.page_size} total={errs.datos.total} onCambiar={setPage} />
          )}
        </>
      )}
    </section>
  );
}
