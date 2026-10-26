import { useCallback, useState, type FormEvent } from 'react';
import { crearAutorizacion, listarAutorizaciones, revocarAutorizacion } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Finalidad } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { formatearFechaHora, momentoBogota } from '../utilidades/formato';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';
import { ETIQUETA_FINALIDAD } from '../utilidades/whatsapp';

const ORIGEN = { importacion: 'Importación', cliente: 'Cliente (chat)', agente: 'Alta manual', agente_ia: 'Agente IA' } as const;
const MOTIVO = { opt_out: 'Baja del cliente', manual: 'Manual', importacion: 'Importación' } as const;

export function Autorizaciones() {
  const [busqueda, setBusqueda] = useState('');
  const [numero, setNumero] = useState('');
  const [finalidad, setFinalidad] = useState<Finalidad | ''>('');
  const [vigentes, setVigentes] = useState(true);
  const [page, setPage] = useState(1);
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);

  const cargador = useCallback(
    () => listarAutorizaciones({ numero, finalidad, vigentes: vigentes ? true : '', page, page_size: 20 }),
    [numero, finalidad, vigentes, page],
  );
  const { datos, cargando, error, recargar } = useCarga(cargador);

  async function revocar(id: number, numeroTxt: string) {
    if (!window.confirm(`¿Revocar la autorización de WhatsApp de ${numeroTxt}?`)) return;
    setErrorAccion(null);
    try {
      await revocarAutorizacion(id);
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
  }

  return (
    <section aria-labelledby="t-autorizaciones">
      <h1 id="t-autorizaciones">Autorizaciones de WhatsApp (opt-in)</h1>
      <p className="ayuda">Sin una autorización vigente para la finalidad no se pueden enviar plantillas al número. Los datos de evidencia no deben incluir datos personales.</p>
      <FormularioAlta onCreada={recargar} />

      <h2>Listado</h2>
      <form className="filtros" role="search" onSubmit={(e) => { e.preventDefault(); setPage(1); setNumero(busqueda.trim()); }}>
        <Campo etiqueta="Buscar por teléfono">
          {(p) => <input {...p} type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Filtrar por finalidad">
          {(p) => (
            <select {...p} value={finalidad} onChange={(e) => { setPage(1); setFinalidad(e.target.value as Finalidad | ''); }}>
              <option value="">Todas</option>
              {(Object.keys(ETIQUETA_FINALIDAD) as Finalidad[]).map((f) => (
                <option key={f} value={f}>{ETIQUETA_FINALIDAD[f]}</option>
              ))}
            </select>
          )}
        </Campo>
        <div className="campo">
          <label>
            <input type="checkbox" checked={vigentes} onChange={(e) => { setPage(1); setVigentes(e.target.checked); }} /> Solo vigentes
          </label>
        </div>
        <button type="submit">Buscar</button>
      </form>

      <MensajeError error={errorAccion} />
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay autorizaciones que coincidan.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Autorizaciones de WhatsApp</caption>
              <thead>
                <tr>
                  <th scope="col">Teléfono</th><th scope="col">Finalidad</th><th scope="col">Origen</th><th scope="col">Evidencia</th>
                  <th scope="col">Otorgada</th><th scope="col">Estado</th><th scope="col">Registrada por</th><th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((a) => {
                  const num = a.numero_e164 ?? a.numero_mascara;
                  return (
                    <tr key={a.id}>
                      <th scope="row">{num}</th>
                      <td>{ETIQUETA_FINALIDAD[a.finalidad]}</td>
                      <td>{ORIGEN[a.origen]}</td>
                      <td>{a.evidencia}</td>
                      <td>{formatearFechaHora(a.otorgada_en)}</td>
                      <td>
                        {a.vigente ? (
                          <span className="insignia estado-activa">Vigente</span>
                        ) : (
                          <span className="insignia insignia-error">
                            Revocada{a.motivo_revocacion ? ` (${MOTIVO[a.motivo_revocacion]})` : ''}
                          </span>
                        )}
                      </td>
                      <td>{a.registrada_por?.nombre ?? '—'}</td>
                      <td>
                        {a.vigente && (
                          <button type="button" className="peligro" onClick={() => void revocar(a.id, num)}>
                            Revocar<span className="solo-lectura"> autorización de {num}</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
        </>
      )}
    </section>
  );
}

const CAMPOS_ALTA = ['telefono', 'finalidad', 'evidencia', 'otorgada_en'];

function FormularioAlta({ onCreada }: { onCreada: () => void }) {
  const [telefono, setTelefono] = useState('');
  const [finalidad, setFinalidad] = useState<Finalidad>('cobranza');
  const [evidencia, setEvidencia] = useState('');
  const [otorgada, setOtorgada] = useState('');
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});
  const [error, setError] = useState<ErrorApi | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const msg = (c: string) => errLocal[c] ?? error?.detalleDe(c);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    const l: Record<string, string> = {};
    if (!telefono.trim()) l.telefono = 'Ingrese el teléfono.';
    const ev = evidencia.trim();
    if (ev.length < 5 || ev.length > 500) l.evidencia = 'La evidencia debe tener entre 5 y 500 caracteres.';
    setErrLocal(l);
    if (Object.keys(l).length) return;
    setEnviando(true);
    try {
      const a = await crearAutorizacion({
        telefono: telefono.trim(), finalidad, evidencia: ev, ...(otorgada ? { otorgada_en: momentoBogota(otorgada) } : {}),
      });
      setOk(`Autorización registrada para ${a.numero_e164 ?? a.numero_mascara}.`);
      setTelefono('');
      setEvidencia('');
      setOtorgada('');
      onCreada();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-alta-aut">
      <h2 id="t-alta-aut">Registrar autorización</h2>
      <form onSubmit={enviar} noValidate className="formulario">
        <div className="fila-campos">
          <Campo etiqueta="Teléfono" error={msg('telefono')} ayuda="Cualquier formato, p. ej. 300 123 4567.">
            {(p) => <input {...p} value={telefono} onChange={(e) => setTelefono(e.target.value)} inputMode="tel" required />}
          </Campo>
          <Campo etiqueta="Finalidad" error={msg('finalidad')}>
            {(p) => (
              <select {...p} value={finalidad} onChange={(e) => setFinalidad(e.target.value as Finalidad)}>
                {(Object.keys(ETIQUETA_FINALIDAD) as Finalidad[]).map((f) => (
                  <option key={f} value={f}>{ETIQUETA_FINALIDAD[f]}</option>
                ))}
              </select>
            )}
          </Campo>
        </div>
        <Campo etiqueta="Evidencia" error={msg('evidencia')} ayuda="Referencia al soporte (p. ej. «Formulario firmado F-123»). De 5 a 500 caracteres.">
          {(p) => <textarea {...p} rows={2} maxLength={500} value={evidencia} onChange={(e) => setEvidencia(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Fecha en que se otorgó (opcional, hora de Bogotá)" error={msg('otorgada_en')} ayuda="Si se omite, se usa el momento actual. No puede ser futura.">
          {(p) => <input {...p} type="datetime-local" value={otorgada} onChange={(e) => setOtorgada(e.target.value)} />}
        </Campo>
        <MensajeError error={error} camposMostrados={CAMPOS_ALTA} />
        {ok && <p role="status" className="alerta alerta-ok">{ok}</p>}
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Registrando…' : 'Registrar'}</button>
      </form>
    </section>
  );
}
