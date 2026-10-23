import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { listarAgentesCampana, listarAgentesSupervision, reemplazarAgentesCampana } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Campana } from '../api/tipos';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';
import { Cargando } from './Cargando';
import { MensajeError } from './MensajeError';

interface Candidato { id: number; nombre: string; activo: boolean }

/** Pestaña "Agentes" del detalle de campaña (administrador y supervisor). */
export function CampanaAgentes({ campana }: { campana: Campana }) {
  const finalizada = campana.estado === 'finalizada';
  const cargadorAsignados = useCallback(() => listarAgentesCampana(campana.id), [campana.id]);
  // GET /usuarios es solo de administrador; la supervisión lista a todos los agentes activos (A y S).
  const cargadorActivos = useCallback(() => listarAgentesSupervision(), []);
  const asignados = useCarga(cargadorAsignados);
  const activos = useCarga(cargadorActivos);

  const [seleccion, setSeleccion] = useState<Set<number>>(new Set());
  const [error, setError] = useState<ErrorApi | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    if (asignados.datos) setSeleccion(new Set(asignados.datos.map((a) => a.usuario_id)));
  }, [asignados.datos]);

  const candidatos = useMemo<Candidato[]>(() => {
    const mapa = new Map<number, Candidato>();
    for (const a of activos.datos ?? []) mapa.set(a.usuario_id, { id: a.usuario_id, nombre: a.nombre, activo: true });
    for (const a of asignados.datos ?? []) {
      if (!mapa.has(a.usuario_id)) mapa.set(a.usuario_id, { id: a.usuario_id, nombre: a.nombre, activo: a.activo });
    }
    return [...mapa.values()].sort((x, y) => x.nombre.localeCompare(y.nombre, 'es'));
  }, [activos.datos, asignados.datos]);

  // Los ids se envían en el orden de la lista: el índice del error 422 (`usuario_ids.N`) identifica al agente.
  const idsEnviados = candidatos.filter((c) => seleccion.has(c.id)).map((c) => c.id);
  const campoDe = (id: number) => `usuario_ids.${idsEnviados.indexOf(id)}`;
  const camposError = idsEnviados.map((_, i) => `usuario_ids.${i}`);

  function alternar(id: number) {
    setOk(false);
    setError(null);
    setSeleccion((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(false);
    setGuardando(true);
    try {
      const r = await reemplazarAgentesCampana(campana.id, idsEnviados);
      setSeleccion(new Set(r.map((a) => a.usuario_id)));
      setOk(true);
      asignados.recargar();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setGuardando(false);
    }
  }

  const cargando = (asignados.cargando && !asignados.datos) || (activos.cargando && !activos.datos);
  return (
    <section aria-labelledby="t-agentes">
      <h2 id="t-agentes">Agentes asignados</h2>
      <p>Solo los agentes asignados a una campaña activa ven sus registros en la consola.</p>
      <MensajeError error={asignados.error} onReintentar={asignados.recargar} />
      <MensajeError error={activos.error} onReintentar={activos.recargar} />
      {cargando && <Cargando />}
      {!cargando && asignados.datos && activos.datos && (
        <form onSubmit={guardar} className="formulario" noValidate>
          {candidatos.length === 0 ? (
            <p>No hay agentes activos. Cree usuarios con rol agente para asignarlos.</p>
          ) : (
            <fieldset disabled={finalizada || guardando}>
              <legend>Seleccione los agentes de la campaña</legend>
              <ul className="lista-simple">
                {candidatos.map((c) => {
                  const err = seleccion.has(c.id) && error ? error.detalleDe(campoDe(c.id)) : undefined;
                  return (
                    <li key={c.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={seleccion.has(c.id)}
                          onChange={() => alternar(c.id)}
                          aria-invalid={err ? true : undefined}
                        />{' '}
                        {c.nombre}
                        {!c.activo && ' (inactivo)'}
                      </label>
                      {err && <span role="alert" className="error-campo"> {err}</span>}
                    </li>
                  );
                })}
              </ul>
            </fieldset>
          )}
          {finalizada && <p className="ayuda">La campaña está finalizada: no se pueden modificar sus agentes.</p>}
          <MensajeError error={error} camposMostrados={camposError} />
          {ok && <p role="status" className="alerta alerta-ok">Agentes guardados.</p>}
          <button type="submit" className="primario" disabled={finalizada || guardando || candidatos.length === 0}>
            {guardando ? 'Guardando…' : 'Guardar agentes'}
          </button>
        </form>
      )}
    </section>
  );
}
