import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  activarIA, desactivarIA, guardarConfiguracionIA, obtenerConfiguracionGlobalIA, obtenerConfiguracionIA,
} from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Campana, ConfiguracionGlobalIA, ConfiguracionIA, EsfuerzoIA } from '../../api/tipos';
import { useConexionTiempoReal, useEventoTiempoReal } from '../../tiempo_real/TiempoRealContext';
import { formatearFechaHora } from '../../utilidades/formato';
import {
  AYUDA_ESFUERZO, ETIQUETA_DESACTIVADA, ETIQUETA_ESFUERZO, ETIQUETA_TRATAMIENTO, MAX_INSTRUCCIONES, construirActualizacion,
  formatearUSD, formDesdeConfig, porcentajeGasto, traducirErrorIA, validarFormIA, type FormIA,
} from '../../utilidades/ia';
import { comoErrorApi } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';
import { ConfirmacionIA } from './ConfirmacionIA';
import { EditorReglasCobranza } from './EditorReglasCobranza';
import { EditorReglasVenta } from './EditorReglasVenta';
import { OfertasCampana } from './OfertasCampana';
import { RequisitosActivacion } from './RequisitosActivacion';

const ESFUERZOS: EsfuerzoIA[] = ['low', 'medium', 'high', 'xhigh', 'max'];
const CAMPOS_BASE = [
  'modelo', 'esfuerzo', 'prompt_version', 'tratamiento', 'instrucciones', 'verificacion.max_intentos', 'presupuesto_usd_mensual',
  'max_costo_conversacion_usd', 'max_turnos_conversacion', 'reglas.max_unidades_por_venta', 'reglas.base_descuento',
  'reglas.descuento_max_pct', 'reglas.monto_minimo_promesa', 'reglas.monto_minimo_cuota', 'reglas.max_cuotas',
  'reglas.plazo_max_dias_primer_pago', 'reglas.plazo_max_dias_total', 'reglas.periodicidades', 'version_esperada',
];

function ayudaModelo(m: string): string {
  if (/opus/i.test(m)) return 'Mayor capacidad y mayor coste por conversación.';
  if (/sonnet/i.test(m)) return 'Equilibrio entre capacidad y coste.';
  if (/haiku/i.test(m)) return 'El más rápido y económico; menos capacidad.';
  return 'Coste orientativo no disponible para este modelo.';
}

interface Props {
  campana: Campana;
  /** Cambia de pestaña en el detalle de la campaña (enlace desde los requisitos). */
  onIrAPestana?: (pestana: 'agentes') => void;
}

/** Pestaña "Agente IA" del detalle de campaña (A, S): configuración, requisitos, activación/kill switch y ofertas. */
export function ConfiguracionIACampana({ campana, onIrAPestana }: Props) {
  const id = campana.id;
  const finalizada = campana.estado === 'finalizada';
  const { reconexiones } = useConexionTiempoReal();
  const [config, setConfig] = useState<ConfiguracionIA | null>(null);
  const [global, setGlobal] = useState<ConfiguracionGlobalIA | null>(null);
  const [form, setForm] = useState<FormIA | null>(null);
  const [base, setBase] = useState('');
  const [versionBase, setVersionBase] = useState(0);
  const [cargando, setCargando] = useState(true);
  const [errorCarga, setErrorCarga] = useState<ErrorApi | null>(null);
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});
  const [errApi, setErrApi] = useState<ErrorApi | null>(null);
  const [conflicto, setConflicto] = useState<number | null>(null);
  const [cambioExterno, setCambioExterno] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState<'activar' | 'desactivar' | null>(null);
  const [ocupadoAccion, setOcupadoAccion] = useState(false);
  const [errAccion, setErrAccion] = useState<ErrorApi | null>(null);

  const formRef = useRef(form);
  const baseRef = useRef(base);
  const versionRef = useRef(versionBase);
  useEffect(() => {
    formRef.current = form;
    baseRef.current = base;
    versionRef.current = versionBase;
  });

  /** Aplica la configuración del servidor. Sin `forzar`, un formulario con cambios sin guardar no se pisa. */
  const sincronizar = useCallback((c: ConfiguracionIA, forzar: boolean) => {
    setConfig(c);
    const sucio = formRef.current !== null && JSON.stringify(formRef.current) !== baseRef.current;
    if (forzar || !sucio) {
      const f = formDesdeConfig(c);
      setForm(f);
      setBase(JSON.stringify(f));
      setVersionBase(c.version);
      setCambioExterno(false);
    } else if (c.version !== versionRef.current) {
      setCambioExterno(true);
    }
  }, []);

  const cargar = useCallback(async (forzar = false) => {
    try {
      sincronizar(await obtenerConfiguracionIA(id), forzar);
      setErrorCarga(null);
    } catch (e) {
      setErrorCarga(comoErrorApi(e));
    } finally {
      setCargando(false);
    }
  }, [id, sincronizar]);

  useEffect(() => {
    void cargar();
  }, [cargar, reconexiones]);
  useEffect(() => {
    let cancelado = false;
    obtenerConfiguracionGlobalIA().then(
      (g) => { if (!cancelado && g && typeof g === 'object') setGlobal(g); },
      () => {},
    );
    return () => { cancelado = true; };
  }, []);

  useEventoTiempoReal('ia.configuracion', (e) => {
    if (e.tipo !== 'ia.configuracion') return;
    if (e.datos.campana_id === id || e.datos.campana_id === null) void cargar();
  });

  async function guardar(ev: FormEvent) {
    ev.preventDefault();
    if (!form || !config) return;
    setOk(null);
    setErrApi(null);
    setConflicto(null);
    const e = validarFormIA(form, campana.tipo);
    setErrLocal(e);
    if (Object.keys(e).length > 0) return;
    setGuardando(true);
    try {
      const c = await guardarConfiguracionIA(id, construirActualizacion(form, campana.tipo, versionBase));
      sincronizar(c, true);
      setOk(`Configuración guardada (versión ${c.version}).`);
    } catch (err) {
      const ea = comoErrorApi(err);
      if (ea.codigo === 'IA_VERSION_CONFLICTO') setConflicto(versionBase);
      else setErrApi(traducirErrorIA(ea));
    } finally {
      setGuardando(false);
    }
  }

  async function ejecutarAccion() {
    if (!confirmando) return;
    setErrAccion(null);
    setOk(null);
    setOcupadoAccion(true);
    try {
      const c = confirmando === 'activar' ? await activarIA(id) : await desactivarIA(id);
      sincronizar(c, false);
      setOk(confirmando === 'activar' ? 'Agente IA activado.' : 'Agente IA desactivado: sus conversaciones pasan a la cola de atención humana.');
    } catch (err) {
      setErrAccion(traducirErrorIA(comoErrorApi(err)));
      void cargar(); // refresca los requisitos pendientes
    } finally {
      setOcupadoAccion(false);
      setConfirmando(null);
    }
  }

  if (cargando && !config) return <Cargando />;
  if (errorCarga && !config) return <MensajeError error={errorCarga} onReintentar={() => void cargar(true)} />;
  if (!config || !form) return null;

  const sucio = JSON.stringify(form) !== base;
  const tipo = campana.tipo;
  const err = (campo: string) => errLocal[campo] ?? errApi?.detalleDe(campo);
  const camposMostrados = [...CAMPOS_BASE, ...form.cobranza.tramos.flatMap((_, i) => [
    `reglas.descuento_max_pct_por_cuotas.${i}.max_cuotas`, `reglas.descuento_max_pct_por_cuotas.${i}.descuento_max_pct`,
  ])];
  const modelos = !global ? [form.modelo]
    : global.modelos_permitidos.includes(form.modelo) ? global.modelos_permitidos : [form.modelo, ...global.modelos_permitidos];
  const esfuerzos = global?.esfuerzos ?? ESFUERZOS;
  const vp = Number(form.prompt_version);
  const prompts = !global ? [vp] : global.prompts.chat.includes(vp) ? global.prompts.chat : [vp, ...global.prompts.chat];
  const pct = porcentajeGasto(config.gasto_mes_usd, config.presupuesto_usd_mensual);
  const cambiar = <K extends keyof FormIA>(k: K, v: FormIA[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));

  return (
    <section aria-labelledby="t-ia">
      <h2 id="t-ia">Agente IA</h2>
      <p className="ayuda">
        La IA atiende los chats de WhatsApp de esta campaña dentro de las reglas definidas aquí. Los cambios de reglas aplican de
        inmediato; modelo, esfuerzo y versión de prompt solo a conversaciones nuevas.
      </p>

      <section aria-labelledby="t-estado-ia" className="tarjeta">
        <h3 id="t-estado-ia">Estado</h3>
        <p>
          <span className={`insignia ${config.activa ? 'estado-activa' : 'insignia-advertencia'}`}>{config.activa ? 'IA activa' : 'IA inactiva'}</span>
          {!config.activa && config.desactivada_motivo && (
            <> Motivo: {ETIQUETA_DESACTIVADA[config.desactivada_motivo]}{config.desactivada_en ? ` (${formatearFechaHora(config.desactivada_en)})` : ''}.</>
          )}
          {config.activa && config.activada_en && <> Desde {formatearFechaHora(config.activada_en)}.</>}
        </p>
        {!config.configurada && <p className="ayuda">Aún no hay una configuración guardada: guárdela para poder activar la IA.</p>}
        {global && (!global.ia_habilitada_entorno || !global.ia_activa) && (
          <p className="alerta alerta-error" role="status">
            {!global.ia_habilitada_entorno
              ? 'La IA está deshabilitada por configuración del entorno.'
              : 'La IA está desactivada globalmente (kill switch global).'}
          </p>
        )}
        <div>
          <label htmlFor="gasto-ia">
            Gasto del mes: {formatearUSD(config.gasto_mes_usd)} de {formatearUSD(config.presupuesto_usd_mensual)}
            {pct !== null ? ` (${pct} %)` : ' (sin presupuesto)'}
          </label>
          {pct !== null && <progress id="gasto-ia" className="progreso" max={100} value={pct} />}
        </div>
        {config.actualizado_por && (
          <p className="ayuda">Versión {config.version}, actualizada por {config.actualizado_por.nombre}{config.actualizado_en ? ` el ${formatearFechaHora(config.actualizado_en)}` : ''}.</p>
        )}
        <div className="acciones" role="group" aria-label="Activación de la IA">
          {!config.activa ? (
            <button type="button" className="primario" disabled={finalizada || confirmando !== null} onClick={() => { setErrAccion(null); setConfirmando('activar'); }}>
              Activar IA
            </button>
          ) : (
            <button type="button" className="peligro" disabled={confirmando !== null} onClick={() => { setErrAccion(null); setConfirmando('desactivar'); }}>
              Desactivar IA (kill switch)
            </button>
          )}
        </div>
        {confirmando === 'activar' && (
          <ConfirmacionIA titulo="¿Activar el agente IA?" textoConfirmar="Confirmar activación" ocupado={ocupadoAccion} onConfirmar={() => void ejecutarAccion()} onCancelar={() => setConfirmando(null)}>
            <p>La IA empezará a atender los chats entrantes de esta campaña (cuando la campaña esté activa). Se comprobarán los requisitos de activación.</p>
          </ConfirmacionIA>
        )}
        {confirmando === 'desactivar' && (
          <ConfirmacionIA titulo="¿Desactivar el agente IA?" textoConfirmar="Confirmar desactivación" peligro ocupado={ocupadoAccion} onConfirmar={() => void ejecutarAccion()} onCancelar={() => setConfirmando(null)}>
            <p>Todas las conversaciones que atiende la IA en esta campaña pasarán a la cola de atención humana y las nuevas nacerán sin asignar.</p>
          </ConfirmacionIA>
        )}
        <MensajeError error={errAccion} />
        {ok && <p role="status" className="alerta alerta-ok">{ok}</p>}
      </section>

      {!config.activa && <RequisitosActivacion campanaId={id} faltantes={config.requisitos.faltantes} onIrAPestana={onIrAPestana} />}

      {conflicto !== null && (
        <div role="alert" className="alerta alerta-error">
          <p>
            <strong>La configuración cambió mientras la editaba.</strong> Otra persona (u otra sesión) guardó una versión nueva después de
            la versión {conflicto} en la que usted se basó, así que sus cambios no se guardaron para no pisar los de la otra persona.
          </p>
          <p>Recargue la configuración vigente y vuelva a aplicar sus cambios.</p>
          <button type="button" className="primario" onClick={() => { setConflicto(null); void cargar(true); }}>Recargar configuración vigente</button>
        </div>
      )}
      {cambioExterno && conflicto === null && (
        <div role="status" className="alerta alerta-error">
          <p>Otra persona guardó una versión nueva de la configuración. Si guarda ahora se le pedirá recargar.</p>
          <button type="button" onClick={() => void cargar(true)}>Descartar mis cambios y recargar</button>
        </div>
      )}

      <form onSubmit={guardar} noValidate className="formulario" aria-label="Configuración del agente IA">
        <fieldset disabled={finalizada || guardando}>
          <legend>Modelo y estilo</legend>
          <div className="fila-campos">
            <Campo etiqueta="Modelo" ayuda={ayudaModelo(form.modelo)} error={err('modelo')}>
              {(p) => (
                <select {...p} value={form.modelo} onChange={(e) => cambiar('modelo', e.target.value)}>
                  {modelos.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Esfuerzo de razonamiento" ayuda={AYUDA_ESFUERZO[form.esfuerzo]} error={err('esfuerzo')}>
              {(p) => (
                <select {...p} value={form.esfuerzo} onChange={(e) => cambiar('esfuerzo', e.target.value as EsfuerzoIA)}>
                  {esfuerzos.map((x) => <option key={x} value={x}>{ETIQUETA_ESFUERZO[x]}</option>)}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Versión del prompt" error={err('prompt_version')}>
              {(p) => (
                <select {...p} value={form.prompt_version} onChange={(e) => cambiar('prompt_version', e.target.value)}>
                  {prompts.map((v) => <option key={v} value={String(v)}>Versión {v}</option>)}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Trato al cliente" error={err('tratamiento')}>
              {(p) => (
                <select {...p} value={form.tratamiento} onChange={(e) => cambiar('tratamiento', e.target.value as FormIA['tratamiento'])}>
                  {(Object.keys(ETIQUETA_TRATAMIENTO) as (keyof typeof ETIQUETA_TRATAMIENTO)[]).map((t) => <option key={t} value={t}>{ETIQUETA_TRATAMIENTO[t]}</option>)}
                </select>
              )}
            </Campo>
          </div>
          <Campo
            etiqueta="Instrucciones de la campaña para la IA"
            ayuda={`${form.instrucciones.length}/${MAX_INSTRUCCIONES} caracteres. Orientan a la IA; no reemplazan las reglas de negocio.`}
            error={err('instrucciones')}
          >
            {(p) => <textarea {...p} rows={4} value={form.instrucciones} onChange={(e) => cambiar('instrucciones', e.target.value)} />}
          </Campo>
        </fieldset>

        <fieldset disabled={finalizada || guardando}>
          <legend>Verificación de identidad</legend>
          <Campo etiqueta="Intentos máximos de verificación" ayuda="La IA verifica el número de documento del cliente; agotados los intentos, traspasa a un asesor." error={err('verificacion.max_intentos')}>
            {(p) => <input {...p} type="number" min={1} max={5} inputMode="numeric" value={form.max_intentos} onChange={(e) => cambiar('max_intentos', e.target.value)} />}
          </Campo>
        </fieldset>

        {tipo === 'cobranza' ? (
          <EditorReglasCobranza valor={form.cobranza} onCambio={(v) => cambiar('cobranza', v)} error={err} deshabilitado={finalizada || guardando} />
        ) : (
          <EditorReglasVenta valor={form.venta} onCambio={(v) => cambiar('venta', v)} error={err} deshabilitado={finalizada || guardando} />
        )}

        <fieldset disabled={finalizada || guardando}>
          <legend>Presupuesto y límites</legend>
          <div className="fila-campos">
            <Campo etiqueta="Presupuesto mensual (USD)" ayuda="Al agotarse, la IA se desactiva y sus conversaciones pasan a humanos." error={err('presupuesto_usd_mensual')}>
              {(p) => <input {...p} type="text" inputMode="decimal" value={form.presupuesto_usd_mensual} onChange={(e) => cambiar('presupuesto_usd_mensual', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Coste máximo por conversación (USD)" error={err('max_costo_conversacion_usd')}>
              {(p) => <input {...p} type="text" inputMode="decimal" value={form.max_costo_conversacion_usd} onChange={(e) => cambiar('max_costo_conversacion_usd', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Turnos máximos por conversación" error={err('max_turnos_conversacion')}>
              {(p) => <input {...p} type="number" min={1} max={200} inputMode="numeric" value={form.max_turnos_conversacion} onChange={(e) => cambiar('max_turnos_conversacion', e.target.value)} />}
            </Campo>
          </div>
        </fieldset>

        {Object.keys(errLocal).length > 0 && (
          <p role="alert" className="alerta alerta-error">Corrija los campos marcados antes de guardar.</p>
        )}
        <MensajeError error={errApi} camposMostrados={camposMostrados} />
        {finalizada && <p className="ayuda">La campaña está finalizada: la configuración de IA no se puede modificar.</p>}
        {sucio && <p className="ayuda" role="status">Hay cambios sin guardar.</p>}
        <button type="submit" className="primario" disabled={finalizada || guardando}>
          {guardando ? 'Guardando…' : 'Guardar configuración'}
        </button>
      </form>

      {tipo === 'venta' && <OfertasCampana campana={campana} onCambio={() => void cargar()} />}
    </section>
  );
}
