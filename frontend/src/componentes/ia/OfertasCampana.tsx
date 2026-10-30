import { useCallback, useState, type FormEvent } from 'react';
import { actualizarOferta, crearOferta, listarOfertas } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { Campana, Oferta, OfertaCrear } from '../../api/tipos';
import { formatearCOP } from '../../utilidades/formato';
import { esDecimal, traducirErrorIA } from '../../utilidades/ia';
import { comoErrorApi, useCarga } from '../../utilidades/useCarga';
import { Campo } from '../Campo';
import { Cargando } from '../Cargando';
import { MensajeError } from '../MensajeError';

interface FormOferta {
  codigo: string; nombre: string; descripcion: string; precio: string; descuento_max_pct: string; max_unidades: string; condiciones: string;
}
const VACIA: FormOferta = { codigo: '', nombre: '', descripcion: '', precio: '', descuento_max_pct: '0', max_unidades: '1', condiciones: '' };
const CAMPOS = ['codigo', 'nombre', 'descripcion', 'precio', 'descuento_max_pct', 'max_unidades', 'condiciones'];
const norm = (s: string) => s.trim().replace(',', '.');

function validar(f: FormOferta, editando: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  if (!editando && !/^[A-Za-z0-9_-]{2,30}$/.test(f.codigo.trim())) e.codigo = 'El código debe tener de 2 a 30 caracteres: letras, números, guion o guion bajo.';
  if (f.nombre.trim().length < 2 || f.nombre.trim().length > 120) e.nombre = 'El nombre debe tener entre 2 y 120 caracteres.';
  if (f.descripcion.length > 500) e.descripcion = 'La descripción no puede superar 500 caracteres.';
  if (!esDecimal(f.precio, 2) || Number(norm(f.precio)) <= 0) e.precio = 'El precio debe ser un número mayor que 0 (COP), con hasta 2 decimales.';
  if (!esDecimal(f.descuento_max_pct, 2) || Number(norm(f.descuento_max_pct)) > 100) e.descuento_max_pct = 'El descuento máximo debe estar entre 0 y 100.';
  if (!/^\d+$/.test(f.max_unidades) || Number(f.max_unidades) < 1 || Number(f.max_unidades) > 100) e.max_unidades = 'Las unidades máximas deben ser un entero entre 1 y 100.';
  if (f.condiciones.length > 1000) e.condiciones = 'Las condiciones no pueden superar 1000 caracteres.';
  return e;
}

function desdeOferta(o: Oferta): FormOferta {
  return {
    codigo: o.codigo, nombre: o.nombre, descripcion: o.descripcion ?? '', precio: o.precio, descuento_max_pct: o.descuento_max_pct,
    max_unidades: String(o.max_unidades), condiciones: o.condiciones ?? '',
  };
}

/** Ofertas/productos de una campaña de venta que la IA puede cotizar (precio en COP, descuento máximo). */
export function OfertasCampana({ campana, onCambio }: { campana: Campana; onCambio?: () => void }) {
  const finalizada = campana.estado === 'finalizada';
  const cargador = useCallback(() => listarOfertas(campana.id), [campana.id]);
  const { datos, cargando, error, recargar } = useCarga(cargador);
  const [editando, setEditando] = useState<Oferta | 'nueva' | null>(null);
  const [form, setForm] = useState<FormOferta>(VACIA);
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});
  const [errApi, setErrApi] = useState<ErrorApi | null>(null);
  const [errAccion, setErrAccion] = useState<ErrorApi | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);

  function abrir(o: Oferta | 'nueva') {
    setEditando(o);
    setForm(o === 'nueva' ? VACIA : desdeOferta(o));
    setErrLocal({});
    setErrApi(null);
    setAviso(null);
  }

  async function guardar(ev: FormEvent) {
    ev.preventDefault();
    setErrApi(null);
    const esNueva = editando === 'nueva';
    const e = validar(form, !esNueva);
    setErrLocal(e);
    if (Object.keys(e).length > 0) return;
    const comun = {
      nombre: form.nombre.trim(), descripcion: form.descripcion.trim() || null, precio: Number(norm(form.precio)).toFixed(2),
      descuento_max_pct: Number(norm(form.descuento_max_pct)).toFixed(2), max_unidades: Number(form.max_unidades),
      condiciones: form.condiciones.trim() || null,
    };
    setEnviando(true);
    try {
      if (esNueva) {
        const cuerpo: OfertaCrear = { codigo: form.codigo.trim().toUpperCase(), ...comun };
        await crearOferta(campana.id, cuerpo);
        setAviso('Oferta creada.');
      } else if (editando) {
        await actualizarOferta(campana.id, editando.id, comun);
        setAviso('Oferta actualizada.');
      }
      setEditando(null);
      recargar();
      onCambio?.();
    } catch (err) {
      setErrApi(traducirErrorIA(comoErrorApi(err)));
    } finally {
      setEnviando(false);
    }
  }

  async function alternarActiva(o: Oferta) {
    setErrAccion(null);
    setAviso(null);
    try {
      await actualizarOferta(campana.id, o.id, { activa: !o.activa });
      setAviso(o.activa ? `Oferta ${o.codigo} desactivada.` : `Oferta ${o.codigo} activada.`);
      recargar();
      onCambio?.();
    } catch (err) {
      setErrAccion(traducirErrorIA(comoErrorApi(err)));
    }
  }

  const campo = (k: keyof FormOferta) => errLocal[k] ?? errApi?.detalleDe(k);
  const cambiar = (k: keyof FormOferta, v: string) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <section aria-labelledby="t-ofertas">
      <h3 id="t-ofertas" tabIndex={-1}>Ofertas de la campaña</h3>
      <p className="ayuda">Productos que la IA puede cotizar y vender. No se borran: se desactivan.</p>
      <MensajeError error={error} onReintentar={recargar} />
      <MensajeError error={errAccion} />
      {aviso && <p role="status" className="alerta alerta-ok">{aviso}</p>}
      {cargando && !datos && <Cargando />}
      {datos && datos.length === 0 && <p>La campaña aún no tiene ofertas.</p>}
      {datos && datos.length > 0 && (
        <div className="tabla-scroll">
          <table>
            <caption className="solo-lectura">Ofertas de la campaña</caption>
            <thead>
              <tr>
                <th scope="col">Código</th><th scope="col">Nombre</th><th scope="col">Precio</th>
                <th scope="col">Descuento máx.</th><th scope="col">Unidades máx.</th><th scope="col">Estado</th>
                <th scope="col"><span className="solo-lectura">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {datos.map((o) => (
                <tr key={o.id}>
                  <th scope="row">{o.codigo}</th>
                  <td>{o.nombre}</td>
                  <td>{formatearCOP(o.precio)}</td>
                  <td>{o.descuento_max_pct} %</td>
                  <td>{o.max_unidades}</td>
                  <td>{o.activa ? <span className="insignia estado-activa">Activa</span> : <span className="insignia">Inactiva</span>}</td>
                  <td>
                    <div className="acciones">
                      <button type="button" disabled={finalizada} onClick={() => abrir(o)}>
                        Editar<span className="solo-lectura"> oferta {o.codigo}</span>
                      </button>
                      <button type="button" disabled={finalizada} onClick={() => void alternarActiva(o)}>
                        {o.activa ? 'Desactivar' : 'Activar'}<span className="solo-lectura"> oferta {o.codigo}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editando === null && (
        <button type="button" disabled={finalizada} onClick={() => abrir('nueva')}>Nueva oferta</button>
      )}
      {editando !== null && (
        <form onSubmit={guardar} noValidate className="tarjeta formulario" aria-label={editando === 'nueva' ? 'Nueva oferta' : `Editar oferta ${editando.codigo}`}>
          <h4>{editando === 'nueva' ? 'Nueva oferta' : `Editar oferta ${editando.codigo}`}</h4>
          <div className="fila-campos">
            <Campo etiqueta="Código" error={campo('codigo')} ayuda={editando === 'nueva' ? 'Se guarda en mayúsculas y no se puede cambiar después.' : undefined}>
              {(p) => <input {...p} type="text" maxLength={30} value={form.codigo} disabled={editando !== 'nueva'} onChange={(e) => cambiar('codigo', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Nombre" error={campo('nombre')}>
              {(p) => <input {...p} type="text" maxLength={120} value={form.nombre} onChange={(e) => cambiar('nombre', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Precio unitario (COP)" error={campo('precio')}>
              {(p) => <input {...p} type="text" inputMode="decimal" value={form.precio} onChange={(e) => cambiar('precio', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Descuento máximo (%)" error={campo('descuento_max_pct')}>
              {(p) => <input {...p} type="text" inputMode="decimal" value={form.descuento_max_pct} onChange={(e) => cambiar('descuento_max_pct', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Unidades máximas por venta" error={campo('max_unidades')}>
              {(p) => <input {...p} type="number" min={1} max={100} value={form.max_unidades} onChange={(e) => cambiar('max_unidades', e.target.value)} />}
            </Campo>
          </div>
          <Campo etiqueta="Descripción" error={campo('descripcion')}>
            {(p) => <textarea {...p} rows={2} maxLength={500} value={form.descripcion} onChange={(e) => cambiar('descripcion', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Condiciones" error={campo('condiciones')} ayuda="Se envían al modelo y constan en la constancia de la venta.">
            {(p) => <textarea {...p} rows={3} maxLength={1000} value={form.condiciones} onChange={(e) => cambiar('condiciones', e.target.value)} />}
          </Campo>
          <MensajeError error={errApi} camposMostrados={CAMPOS} />
          <div className="acciones">
            <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Guardando…' : 'Guardar oferta'}</button>
            <button type="button" onClick={() => setEditando(null)}>Cancelar</button>
          </div>
        </form>
      )}
    </section>
  );
}
