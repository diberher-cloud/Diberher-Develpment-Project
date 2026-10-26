import { useCallback, useState, type FormEvent } from 'react';
import { actualizarPlantilla, listarPlantillas, sincronizarPlantillas } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { CampoPlantilla, Finalidad, Plantilla, ResultadoSincronizacion } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { formatearFechaHora } from '../utilidades/formato';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';
import { CAMPOS_PLANTILLA, ETIQUETA_CAMPO_PLANTILLA, ETIQUETA_FINALIDAD, previaPlantilla } from '../utilidades/whatsapp';

const ETIQUETA_APROBACION: Record<Plantilla['estado_aprobacion'], string> = {
  aprobada: 'Aprobada', pendiente: 'Pendiente', rechazada: 'Rechazada', pausada: 'Pausada', deshabilitada: 'Deshabilitada',
  eliminada: 'Eliminada', desconocido: 'Desconocido',
};
const ETIQUETA_CATEGORIA: Record<Plantilla['categoria'], string> = {
  marketing: 'Marketing', utility: 'Utilidad', authentication: 'Autenticación', desconocida: 'Desconocida',
};

export function PlantillasWhatsApp() {
  const { tieneRol } = useAuth();
  const cargador = useCallback(() => listarPlantillas(), []);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const [editando, setEditando] = useState<number | null>(null);
  const [sincronizando, setSincronizando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoSincronizacion | null>(null);
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);

  async function sincronizar() {
    setErrorAccion(null);
    setResultado(null);
    setSincronizando(true);
    try {
      setResultado(await sincronizarPlantillas());
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    } finally {
      setSincronizando(false);
    }
  }

  const lista = datos ?? [];
  return (
    <section aria-labelledby="t-plantillas">
      <div className="barra-titulo">
        <h1 id="t-plantillas">Plantillas de WhatsApp</h1>
        {tieneRol('administrador') && (
          <button type="button" className="primario" disabled={sincronizando} onClick={() => void sincronizar()}>
            {sincronizando ? 'Sincronizando…' : 'Sincronizar'}
          </button>
        )}
      </div>
      <p className="ayuda">
        Las plantillas se aprueban en Meta/Twilio. Aquí se define su finalidad, el mapeo de variables a datos del
        registro (solo campos permitidos, nunca montos) y si están activas.
      </p>
      <MensajeError error={errorAccion} />
      {resultado && (
        <p role="status" className="alerta alerta-ok">
          Sincronización completa: {resultado.creadas} creadas, {resultado.actualizadas} actualizadas, {resultado.desactivadas} desactivadas.
        </p>
      )}
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && lista.length === 0 && !error && <p>No hay plantillas. {tieneRol('administrador') ? 'Use "Sincronizar" para traerlas.' : ''}</p>}
      {lista.length > 0 && (
        <div className="tabla-scroll" aria-busy={cargando}>
          <table>
            <caption className="solo-lectura">Plantillas de WhatsApp</caption>
            <thead>
              <tr>
                <th scope="col">Nombre</th><th scope="col">Categoría</th><th scope="col">Aprobación</th>
                <th scope="col">Finalidad</th><th scope="col">Estado</th><th scope="col">Sincronizada</th><th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((p) => (
                <tr key={p.id}>
                  <th scope="row">
                    {p.nombre} <span className="ayuda">({p.idioma})</span>
                    {p.motivo_rechazo && <div className="error-campo">Rechazo: {p.motivo_rechazo}</div>}
                  </th>
                  <td>{ETIQUETA_CATEGORIA[p.categoria]}{p.categoria === 'marketing' && !p.tiene_boton_baja ? ' (sin botón de baja)' : ''}</td>
                  <td>{ETIQUETA_APROBACION[p.estado_aprobacion]}</td>
                  <td>{p.finalidad ? ETIQUETA_FINALIDAD[p.finalidad] : '—'}</td>
                  <td>
                    {p.activa ? <span className="insignia estado-activa">Activa</span> : <span className="insignia">Inactiva</span>}
                    {p.enviable && <span className="insignia estado-activa"> Enviable</span>}
                  </td>
                  <td>{formatearFechaHora(p.sincronizada_en)}</td>
                  <td>
                    <button type="button" aria-expanded={editando === p.id} onClick={() => setEditando((x) => (x === p.id ? null : p.id))}>
                      Editar<span className="solo-lectura"> {p.nombre}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editando !== null && lista.find((p) => p.id === editando) && (
        <EditorPlantilla
          key={editando}
          plantilla={lista.find((p) => p.id === editando)!}
          onGuardada={() => { setEditando(null); recargar(); }}
          onCancelar={() => setEditando(null)}
        />
      )}
    </section>
  );
}

function EditorPlantilla({ plantilla: p, onGuardada, onCancelar }: { plantilla: Plantilla; onGuardada: () => void; onCancelar: () => void }) {
  const [finalidad, setFinalidad] = useState<Finalidad | ''>(p.finalidad ?? '');
  const [mapeo, setMapeo] = useState<Record<string, CampoPlantilla | ''>>(
    Object.fromEntries(p.variables.map((v) => [v, p.mapeo_variables[v] ?? ''])),
  );
  const [activa, setActiva] = useState(p.activa);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);

  const completo = p.variables.every((v) => mapeo[v]);
  const camposMapeo = p.variables.map((v) => `mapeo_variables.${v}`);

  async function guardar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(false);
    setEnviando(true);
    try {
      const cuerpo: Parameters<typeof actualizarPlantilla>[1] = { activa };
      if (finalidad) cuerpo.finalidad = finalidad;
      if (completo) cuerpo.mapeo_variables = mapeo as Record<string, CampoPlantilla>;
      await actualizarPlantilla(p.id, cuerpo);
      setOk(true);
      onGuardada();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={guardar} noValidate className="tarjeta formulario" aria-label={`Editar la plantilla ${p.nombre}`}>
      <h2>Editar: {p.nombre}</h2>
      <blockquote className="previa-plantilla" aria-label="Vista previa de la plantilla">
        {previaPlantilla({ cuerpo: p.cuerpo, mapeo_variables: Object.fromEntries(Object.entries(mapeo).filter(([, v]) => v)) as Record<string, CampoPlantilla> })}
      </blockquote>
      <Campo etiqueta="Finalidad" error={error?.detalleDe('finalidad')}>
        {(a) => (
          <select {...a} value={finalidad} onChange={(e) => setFinalidad(e.target.value as Finalidad | '')}>
            <option value="">Sin definir</option>
            {(Object.keys(ETIQUETA_FINALIDAD) as Finalidad[]).map((f) => (
              <option key={f} value={f}>{ETIQUETA_FINALIDAD[f]}</option>
            ))}
          </select>
        )}
      </Campo>
      {p.variables.length > 0 && (
        <fieldset>
          <legend>Variables de la plantilla</legend>
          {p.variables.map((v) => (
            <Campo key={v} etiqueta={`Variable {{${v}}}`} error={error?.detalleDe(`mapeo_variables.${v}`)}>
              {(a) => (
                <select {...a} value={mapeo[v]} onChange={(e) => setMapeo((m) => ({ ...m, [v]: e.target.value as CampoPlantilla | '' }))}>
                  <option value="">Seleccione un campo…</option>
                  {CAMPOS_PLANTILLA.map((c) => (
                    <option key={c} value={c}>{ETIQUETA_CAMPO_PLANTILLA[c]}</option>
                  ))}
                </select>
              )}
            </Campo>
          ))}
        </fieldset>
      )}
      <div className="campo">
        <label>
          <input type="checkbox" checked={activa} onChange={(e) => setActiva(e.target.checked)} /> Plantilla activa (enviable por los agentes)
        </label>
        <small className="ayuda">Requiere estar aprobada, con finalidad y todas las variables mapeadas; las de marketing, además, un botón de baja.</small>
      </div>
      <MensajeError error={error} camposMostrados={['finalidad', ...camposMapeo]} />
      {ok && <p role="status" className="alerta alerta-ok">Plantilla guardada.</p>}
      <div className="acciones">
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Guardando…' : 'Guardar'}</button>
        <button type="button" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}
