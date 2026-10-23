import { useCallback, useState, type FormEvent } from 'react';
import {
  actualizarFestivo, crearFestivo, evaluarCumplimiento, generarFestivos, listarFestivos, listarPoliticas,
} from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { DiaSemana, Politica, ResultadoEvaluacion, TipoCampana } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { ETIQUETA_TIPO } from '../utilidades/campanas';
import {
  anioActualBogota, formatearFecha, formatearFechaHora, momentoBogota, ZONA,
} from '../utilidades/formato';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';

const DIAS: [DiaSemana, string][] = [
  ['lunes', 'Lunes'], ['martes', 'Martes'], ['miercoles', 'Miércoles'], ['jueves', 'Jueves'],
  ['viernes', 'Viernes'], ['sabado', 'Sábado'], ['domingo', 'Domingo'],
];
const SEMANA = { calendario: 'Semana calendario', movil_7_dias: '7 días móviles' } as const;

export function Cumplimiento() {
  return (
    <section aria-labelledby="t-cumpl">
      <h1 id="t-cumpl">Cumplimiento</h1>
      <p>Todas las horas se muestran en la zona horaria {ZONA} (UTC-05:00).</p>
      <Politicas />
      <Festivos />
      <Evaluador />
    </section>
  );
}

function Politicas() {
  const cargador = useCallback(() => listarPoliticas(), []);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  return (
    <section aria-labelledby="t-pol">
      <h2 id="t-pol">Políticas activas</h2>
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.length === 0 && <p>No hay políticas activas.</p>}
      {datos?.map((p) => <TablaPolitica key={p.id} politica={p} />)}
    </section>
  );
}

function TablaPolitica({ politica: p }: { politica: Politica }) {
  const c = p.configuracion;
  return (
    <article className="tarjeta" aria-label={`Política de ${ETIQUETA_TIPO[p.tipo_campana]}`}>
      <h3>
        {ETIQUETA_TIPO[p.tipo_campana]} · versión {p.version}
      </h3>
      <div className="tabla-scroll">
        <table>
          <caption className="solo-lectura">Franjas horarias de {ETIQUETA_TIPO[p.tipo_campana]}</caption>
          <thead>
            <tr><th scope="col">Día</th><th scope="col">Franjas permitidas</th></tr>
          </thead>
          <tbody>
            {DIAS.map(([d, nombre]) => (
              <tr key={d}>
                <th scope="row">{nombre}</th>
                <td>{c.franjas[d]?.length ? c.franjas[d].map((f) => `${f.inicio} - ${f.fin}`).join(', ') : 'Sin llamadas'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="lista-simple">
        <li>Festivos: {c.permitir_festivos ? 'se permite llamar' : 'no se llama'}.</li>
        <li>
          Frecuencia (solo informativa en esta fase): {c.frecuencia.max_contactos_dia} contacto(s) por día,{' '}
          {c.frecuencia.max_canales_semana} canal(es) por semana ({SEMANA[c.frecuencia.semana]})
          {c.frecuencia.solo_tras_contacto_directo ? ', solo tras contacto directo' : ''}.
        </li>
      </ul>
    </article>
  );
}

function Festivos() {
  const { tieneRol } = useAuth();
  const admin = tieneRol('administrador');
  const [anio, setAnio] = useState(anioActualBogota());
  const [entradaAnio, setEntradaAnio] = useState(String(anio));
  const [errorAnio, setErrorAnio] = useState<string | undefined>();
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const cargador = useCallback(() => listarFestivos(anio), [anio]);
  const { datos, cargando, error, recargar } = useCarga(cargador);

  function consultar(e: FormEvent) {
    e.preventDefault();
    const n = Number(entradaAnio);
    if (!Number.isInteger(n) || n < 1984 || n > 2100) {
      setErrorAnio('Ingrese un año entre 1984 y 2100.');
      return;
    }
    setErrorAnio(undefined);
    setAnio(n);
  }

  async function generar() {
    setErrorAccion(null);
    setInfo(null);
    try {
      const r = await generarFestivos(anio);
      setInfo(`Año ${r.anio}: ${r.creados} festivos creados, ${r.existentes} ya existían.`);
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
  }

  async function alternar(id: number, activo: boolean) {
    setErrorAccion(null);
    try {
      await actualizarFestivo(id, { activo });
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
    }
  }

  return (
    <section aria-labelledby="t-fest">
      <h2 id="t-fest">Festivos</h2>
      <form className="filtros" onSubmit={consultar} noValidate>
        <Campo etiqueta="Año" error={errorAnio}>
          {(p) => <input {...p} type="number" min={1984} max={2100} value={entradaAnio} onChange={(e) => setEntradaAnio(e.target.value)} />}
        </Campo>
        <button type="submit">Consultar</button>
        {admin && <button type="button" onClick={generar}>Generar festivos de {anio}</button>}
      </form>
      {info && <p role="status" className="alerta alerta-ok">{info}</p>}
      <MensajeError error={errorAccion} />
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.length === 0 && !error && <p>No hay festivos registrados para {anio}.</p>}
      {datos && datos.length > 0 && (
        <div className="tabla-scroll" aria-busy={cargando}>
          <table>
            <caption className="solo-lectura">Festivos de {anio}</caption>
            <thead>
              <tr>
                <th scope="col">Fecha</th><th scope="col">Nombre</th><th scope="col">Origen</th>
                <th scope="col">Estado</th>{admin && <th scope="col">Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {datos.map((f) => (
                <tr key={f.id}>
                  <th scope="row">{formatearFecha(f.fecha)}</th>
                  <td>{f.nombre}</td><td>{f.origen}</td><td>{f.activo ? 'Activo' : 'Inactivo'}</td>
                  {admin && (
                    <td>
                      <button type="button" onClick={() => alternar(f.id, !f.activo)}>
                        {f.activo ? 'Desactivar' : 'Activar'}<span className="solo-lectura"> {f.nombre}</span>
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {admin && <FestivoManual onCreado={recargar} />}
    </section>
  );
}

function FestivoManual({ onCreado }: { onCreado: () => void }) {
  const [fecha, setFecha] = useState('');
  const [nombre, setNombre] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const l: Record<string, string> = {};
    if (!fecha) l.fecha = 'Seleccione una fecha.';
    if (!nombre.trim()) l.nombre = 'Ingrese el nombre del festivo.';
    setErrLocal(l);
    if (Object.keys(l).length) return;
    try {
      await crearFestivo({ fecha, nombre: nombre.trim() });
      setFecha('');
      setNombre('');
      onCreado();
    } catch (err) {
      setError(comoErrorApi(err));
    }
  }
  const msg = (c: string) => errLocal[c] ?? error?.detalleDe(c);

  return (
    <form onSubmit={enviar} noValidate className="formulario" aria-label="Agregar festivo manual">
      <h3>Agregar festivo manual</h3>
      <div className="fila-campos">
        <Campo etiqueta="Fecha del festivo" error={msg('fecha')}>
          {(p) => <input {...p} type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Nombre del festivo" error={msg('nombre')}>
          {(p) => <input {...p} value={nombre} onChange={(e) => setNombre(e.target.value)} />}
        </Campo>
      </div>
      <MensajeError error={error} camposMostrados={['fecha', 'nombre']} />
      <button type="submit">Agregar festivo</button>
    </form>
  );
}

function Evaluador() {
  const [tipo, setTipo] = useState<TipoCampana>('cobranza');
  const [momento, setMomento] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [resultado, setResultado] = useState<ResultadoEvaluacion | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function evaluar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setResultado(null);
    setEnviando(true);
    try {
      // La hora ingresada se interpreta SIEMPRE como hora de Bogotá (-05:00), sin importar la zona del navegador.
      const cuerpo = momento ? { tipo_campana: tipo, momento: momentoBogota(momento) } : { tipo_campana: tipo };
      setResultado(await evaluarCumplimiento(cuerpo));
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-eval">
      <h2 id="t-eval">Evaluador de horario</h2>
      <form onSubmit={evaluar} noValidate className="formulario">
        <div className="fila-campos">
          <Campo etiqueta="Tipo de campaña">
            {(p) => (
              <select {...p} value={tipo} onChange={(e) => setTipo(e.target.value as TipoCampana)}>
                <option value="venta">Venta</option>
                <option value="cobranza">Cobranza</option>
              </select>
            )}
          </Campo>
          <Campo etiqueta="Fecha y hora (hora de Bogotá)" error={error?.detalleDe('momento')} ayuda="Si lo deja vacío se evalúa el momento actual.">
            {(p) => <input {...p} type="datetime-local" value={momento} onChange={(e) => setMomento(e.target.value)} />}
          </Campo>
        </div>
        <MensajeError error={error} camposMostrados={['momento']} />
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Evaluando…' : 'Evaluar'}</button>
      </form>
      {resultado && (
        <div role="status" className={`alerta ${resultado.permitido ? 'alerta-ok' : 'alerta-error'}`}>
          <h3>{resultado.permitido ? 'Llamada permitida' : 'Llamada no permitida'}</h3>
          <p>Momento evaluado: {formatearFechaHora(resultado.momento_local)} (hora de Bogotá). Política versión {resultado.politica_version}.</p>
          {resultado.motivos.length > 0 && (
            <ul>
              {resultado.motivos.map((m) => (
                <li key={m.codigo}><strong>{m.codigo}</strong>: {m.mensaje}</li>
              ))}
            </ul>
          )}
          {resultado.proxima_ventana_inicio && (
            <p>Próxima ventana: {formatearFechaHora(resultado.proxima_ventana_inicio)} (hora de Bogotá).</p>
          )}
          {!resultado.permitido && !resultado.proxima_ventana_inicio && <p>No hay ventana disponible en los próximos 14 días.</p>}
        </div>
      )}
    </section>
  );
}
