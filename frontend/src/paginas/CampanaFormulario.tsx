import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { actualizarCampana, crearCampana, listarPlantillas, obtenerCampana } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Campana, Plantilla, TipoCampana } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { aCuerpoCampana, CAMPANA_VACIA, validarCampana, type ValoresCampana } from '../utilidades/campanas';
import { comoErrorApi } from '../utilidades/useCarga';

const CAMPOS = ['nombre', 'tipo', 'descripcion', 'fecha_inicio', 'fecha_fin', 'guion', 'max_intentos', 'intervalo_reintento_minutos',
  'whatsapp_habilitado', 'plantilla_inicial_id'];

function desdeCampana(c: Campana): ValoresCampana {
  return {
    nombre: c.nombre, tipo: c.tipo, descripcion: c.descripcion ?? '', fecha_inicio: c.fecha_inicio ?? '',
    fecha_fin: c.fecha_fin ?? '', guion: c.guion ?? '', max_intentos: String(c.max_intentos),
    intervalo_reintento_minutos: String(c.intervalo_reintento_minutos),
    whatsapp_habilitado: c.whatsapp_habilitado ?? false,
    plantilla_inicial_id: c.plantilla_inicial_id ? String(c.plantilla_inicial_id) : '',
  };
}

export function CampanaFormulario() {
  const { id } = useParams();
  const editando = id !== undefined;
  const navegar = useNavigate();
  const [valores, setValores] = useState<ValoresCampana>(CAMPANA_VACIA);
  const [cargando, setCargando] = useState(editando);
  const [errorCarga, setErrorCarga] = useState<ErrorApi | null>(null);
  const [errores, setErrores] = useState<Record<string, string>>({});
  const [errorApi, setErrorApi] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    if (!editando) return;
    let activo = true;
    obtenerCampana(Number(id)).then(
      (c) => { if (activo) { setValores(desdeCampana(c)); setCargando(false); } },
      (e: unknown) => { if (activo) { setErrorCarga(comoErrorApi(e)); setCargando(false); } },
    );
    return () => { activo = false; };
  }, [editando, id]);

  // Plantillas enviables para la plantilla inicial: solo se piden cuando WhatsApp está habilitado.
  const [plantillas, setPlantillas] = useState<Plantilla[]>([]);
  const habilitado = valores.whatsapp_habilitado;
  useEffect(() => {
    if (!habilitado) return;
    let activo = true;
    listarPlantillas({ enviables: true }).then(
      (l) => { if (activo && Array.isArray(l)) setPlantillas(l); },
      () => { if (activo) setPlantillas([]); },
    );
    return () => { activo = false; };
  }, [habilitado]);
  const plantillasCompatibles = plantillas.filter(
    (p) => p.enviable && (!valores.tipo || p.finalidad === 'todas' || p.finalidad === valores.tipo),
  );

  function cambiar<K extends keyof ValoresCampana>(k: K, v: ValoresCampana[K]) {
    setValores((prev) => ({ ...prev, [k]: v }));
  }

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setErrorApi(null);
    const locales = validarCampana(valores, editando);
    setErrores(locales);
    if (Object.keys(locales).length > 0) return;
    setEnviando(true);
    try {
      const cuerpo = aCuerpoCampana(valores);
      const guardada = editando
        ? await actualizarCampana(Number(id), cuerpo)
        : await crearCampana({ ...cuerpo, tipo: valores.tipo as TipoCampana });
      navegar(`/campanas/${guardada.id}`);
    } catch (err) {
      setErrorApi(comoErrorApi(err));
      setEnviando(false);
    }
  }

  const msg = (campo: string) => errores[campo] ?? errorApi?.detalleDe(campo);

  if (cargando) return <Cargando />;
  if (errorCarga) return <MensajeError error={errorCarga} />;

  return (
    <section aria-labelledby="t-form">
      <h1 id="t-form">{editando ? 'Editar campaña' : 'Nueva campaña'}</h1>
      <form onSubmit={enviar} noValidate className="formulario">
        <Campo etiqueta="Nombre" error={msg('nombre')}>
          {(p) => <input {...p} value={valores.nombre} maxLength={120} onChange={(e) => cambiar('nombre', e.target.value)} required />}
        </Campo>
        <Campo etiqueta="Tipo" error={msg('tipo')} ayuda={editando ? 'El tipo no se puede modificar.' : undefined}>
          {(p) => (
            <select {...p} value={valores.tipo} disabled={editando} onChange={(e) => cambiar('tipo', e.target.value as TipoCampana | '')}>
              <option value="">Seleccione…</option>
              <option value="venta">Venta</option>
              <option value="cobranza">Cobranza</option>
            </select>
          )}
        </Campo>
        <Campo etiqueta="Descripción" error={msg('descripcion')}>
          {(p) => <textarea {...p} rows={3} value={valores.descripcion} onChange={(e) => cambiar('descripcion', e.target.value)} />}
        </Campo>
        <div className="fila-campos">
          <Campo etiqueta="Fecha de inicio" error={msg('fecha_inicio')}>
            {(p) => <input {...p} type="date" value={valores.fecha_inicio} onChange={(e) => cambiar('fecha_inicio', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Fecha de fin" error={msg('fecha_fin')}>
            {(p) => <input {...p} type="date" value={valores.fecha_fin} onChange={(e) => cambiar('fecha_fin', e.target.value)} />}
          </Campo>
        </div>
        <div className="fila-campos">
          <Campo etiqueta="Máximo de intentos (1 a 10)" error={msg('max_intentos')}>
            {(p) => <input {...p} type="number" min={1} max={10} value={valores.max_intentos} onChange={(e) => cambiar('max_intentos', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Intervalo entre reintentos en minutos (5 a 10080)" error={msg('intervalo_reintento_minutos')}>
            {(p) => <input {...p} type="number" min={5} max={10080} value={valores.intervalo_reintento_minutos} onChange={(e) => cambiar('intervalo_reintento_minutos', e.target.value)} />}
          </Campo>
        </div>
        <Campo etiqueta="Guion" error={msg('guion')} ayuda="Admite variables como {{nombre}}. Máximo 20000 caracteres.">
          {(p) => <textarea {...p} rows={8} value={valores.guion} onChange={(e) => cambiar('guion', e.target.value)} />}
        </Campo>
        <fieldset>
          <legend>WhatsApp</legend>
          <div className="campo">
            <label>
              <input
                type="checkbox"
                checked={valores.whatsapp_habilitado}
                onChange={(e) => cambiar('whatsapp_habilitado', e.target.checked)}
              />{' '}
              Habilitar WhatsApp en esta campaña
            </label>
            <small className="ayuda">Permite enviar plantillas desde la ficha y atender conversaciones de esta campaña en la bandeja.</small>
          </div>
          {valores.whatsapp_habilitado && (
            <Campo etiqueta="Plantilla inicial (opcional)" error={msg('plantilla_inicial_id')} ayuda="Sugerida en la ficha del cliente. Solo plantillas activas y compatibles con el tipo de campaña.">
              {(p) => (
                <select {...p} value={valores.plantilla_inicial_id} onChange={(e) => cambiar('plantilla_inicial_id', e.target.value)}>
                  <option value="">Ninguna</option>
                  {plantillasCompatibles.map((x) => (
                    <option key={x.id} value={x.id}>{x.nombre}</option>
                  ))}
                  {valores.plantilla_inicial_id && !plantillasCompatibles.some((x) => String(x.id) === valores.plantilla_inicial_id) && (
                    <option value={valores.plantilla_inicial_id}>Plantilla #{valores.plantilla_inicial_id} (actual)</option>
                  )}
                </select>
              )}
            </Campo>
          )}
        </fieldset>
        <MensajeError error={errorApi} camposMostrados={CAMPOS} />
        <div className="acciones">
          <button type="submit" className="primario" disabled={enviando}>
            {enviando ? 'Guardando…' : 'Guardar'}
          </button>
          <Link to={editando ? `/campanas/${id}` : '/campanas'} className="boton">
            Cancelar
          </Link>
        </div>
      </form>
    </section>
  );
}
