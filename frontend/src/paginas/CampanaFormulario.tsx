import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { actualizarCampana, crearCampana, obtenerCampana } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Campana, TipoCampana } from '../api/tipos';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { aCuerpoCampana, CAMPANA_VACIA, validarCampana, type ValoresCampana } from '../utilidades/campanas';
import { comoErrorApi } from '../utilidades/useCarga';

const CAMPOS = ['nombre', 'tipo', 'descripcion', 'fecha_inicio', 'fecha_fin', 'guion', 'max_intentos', 'intervalo_reintento_minutos'];

function desdeCampana(c: Campana): ValoresCampana {
  return {
    nombre: c.nombre, tipo: c.tipo, descripcion: c.descripcion ?? '', fecha_inicio: c.fecha_inicio ?? '',
    fecha_fin: c.fecha_fin ?? '', guion: c.guion ?? '', max_intentos: String(c.max_intentos),
    intervalo_reintento_minutos: String(c.intervalo_reintento_minutos),
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
