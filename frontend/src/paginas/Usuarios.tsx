import { useCallback, useState, type FormEvent } from 'react';
import { actualizarUsuario, crearUsuario, listarUsuarios } from '../api/endpoints';
import type { ErrorApi } from '../api/cliente';
import type { Rol, Usuario } from '../api/tipos';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { Cargando } from '../componentes/Cargando';
import { MensajeError } from '../componentes/MensajeError';
import { Paginador } from '../componentes/Paginador';
import { comoErrorApi, useCarga } from '../utilidades/useCarga';

const ROLES: Rol[] = ['administrador', 'supervisor', 'agente'];

export function Usuarios() {
  const { usuario: yo } = useAuth();
  const [rol, setRol] = useState<Rol | ''>('');
  const [activo, setActivo] = useState<'' | 'true' | 'false'>('');
  const [page, setPage] = useState(1);
  const [errorAccion, setErrorAccion] = useState<ErrorApi | null>(null);
  const [objetivo, setObjetivo] = useState<Usuario | null>(null);

  const cargador = useCallback(
    () => listarUsuarios({ rol, activo: activo === '' ? '' : activo === 'true', page, page_size: 20 }),
    [rol, activo, page],
  );
  const { datos, cargando, error, recargar } = useCarga(cargador);

  async function modificar(u: Usuario, cambios: { rol?: Rol; activo?: boolean }) {
    setErrorAccion(null);
    try {
      await actualizarUsuario(u.id, cambios);
      recargar();
    } catch (e) {
      setErrorAccion(comoErrorApi(e));
      recargar(); // restaura el valor mostrado en los controles
    }
  }

  return (
    <section aria-labelledby="t-usuarios">
      <h1 id="t-usuarios">Usuarios</h1>
      <FormularioUsuario onCreado={recargar} />

      <h2>Listado</h2>
      <div className="filtros">
        <Campo etiqueta="Filtrar por rol">
          {(p) => (
            <select {...p} value={rol} onChange={(e) => { setPage(1); setRol(e.target.value as Rol | ''); }}>
              <option value="">Todos</option>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Filtrar por estado">
          {(p) => (
            <select {...p} value={activo} onChange={(e) => { setPage(1); setActivo(e.target.value as '' | 'true' | 'false'); }}>
              <option value="">Todos</option>
              <option value="true">Activos</option>
              <option value="false">Inactivos</option>
            </select>
          )}
        </Campo>
      </div>

      <MensajeError error={errorAccion} />
      <MensajeError error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando />}
      {datos && datos.items.length === 0 && !error && <p>No hay usuarios que coincidan.</p>}
      {datos && datos.items.length > 0 && (
        <>
          <div className="tabla-scroll" aria-busy={cargando}>
            <table>
              <caption className="solo-lectura">Usuarios del sistema</caption>
              <thead>
                <tr>
                  <th scope="col">Nombre</th><th scope="col">Correo</th><th scope="col">Rol</th>
                  <th scope="col">Estado</th><th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {datos.items.map((u) => (
                  <tr key={u.id}>
                    <th scope="row">{u.nombre}</th>
                    <td>{u.email}</td>
                    <td>
                      <label className="solo-lectura" htmlFor={`rol-${u.id}`}>Rol de {u.nombre}</label>
                      <select id={`rol-${u.id}`} value={u.rol} disabled={u.id === yo?.id} onChange={(e) => modificar(u, { rol: e.target.value as Rol })}>
                        {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                      </select>
                    </td>
                    <td>{u.activo ? 'Activo' : 'Inactivo'}</td>
                    <td className="acciones">
                      <button type="button" disabled={u.id === yo?.id && u.activo} onClick={() => modificar(u, { activo: !u.activo })}>
                        {u.activo ? 'Desactivar' : 'Activar'}<span className="solo-lectura"> a {u.nombre}</span>
                      </button>
                      <button type="button" onClick={() => setObjetivo(u)}>
                        Restablecer contraseña<span className="solo-lectura"> de {u.nombre}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Paginador page={datos.page} pageSize={datos.page_size} total={datos.total} onCambiar={setPage} />
        </>
      )}
      {objetivo && <RestablecerClave usuario={objetivo} onCerrar={() => setObjetivo(null)} />}
    </section>
  );
}

function FormularioUsuario({ onCreado }: { onCreado: () => void }) {
  const [email, setEmail] = useState('');
  const [nombre, setNombre] = useState('');
  const [rol, setRol] = useState<Rol>('agente');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [errLocal, setErrLocal] = useState<Record<string, string>>({});
  const [ok, setOk] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    const l: Record<string, string> = {};
    if (nombre.trim().length < 2 || nombre.trim().length > 120) l.nombre = 'Debe tener entre 2 y 120 caracteres.';
    if (password.length < 10 || password.length > 128) l.password = 'Debe tener entre 10 y 128 caracteres.';
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) l.email = 'Ingrese un correo válido.';
    setErrLocal(l);
    if (Object.keys(l).length) return;
    setEnviando(true);
    try {
      const u = await crearUsuario({ email: email.trim(), nombre: nombre.trim(), rol, password });
      setOk(`Usuario ${u.email} creado.`);
      setEmail(''); setNombre(''); setPassword(''); setRol('agente');
      onCreado();
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }
  const msg = (c: string) => errLocal[c] ?? error?.detalleDe(c);

  return (
    <section aria-labelledby="t-nuevo-u">
      <h2 id="t-nuevo-u">Crear usuario</h2>
      <form onSubmit={enviar} noValidate className="formulario">
        <Campo etiqueta="Correo electrónico" error={msg('email')}>
          {(p) => <input {...p} type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Nombre" error={msg('nombre')}>
          {(p) => <input {...p} value={nombre} onChange={(e) => setNombre(e.target.value)} />}
        </Campo>
        <Campo etiqueta="Rol" error={msg('rol')}>
          {(p) => (
            <select {...p} value={rol} onChange={(e) => setRol(e.target.value as Rol)}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          )}
        </Campo>
        <Campo etiqueta="Contraseña inicial" error={msg('password')} ayuda="Entre 10 y 128 caracteres.">
          {(p) => <input {...p} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Campo>
        <MensajeError error={error} camposMostrados={['email', 'nombre', 'rol', 'password']} />
        {ok && <p role="status" className="alerta alerta-ok">{ok}</p>}
        <button type="submit" className="primario" disabled={enviando}>{enviando ? 'Creando…' : 'Crear usuario'}</button>
      </form>
    </section>
  );
}

function RestablecerClave({ usuario, onCerrar }: { usuario: Usuario; onCerrar: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<ErrorApi | null>(null);
  const [errLocal, setErrLocal] = useState<string | undefined>();
  const [ok, setOk] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 10 || password.length > 128) {
      setErrLocal('Debe tener entre 10 y 128 caracteres.');
      return;
    }
    setErrLocal(undefined);
    setEnviando(true);
    try {
      await actualizarUsuario(usuario.id, { password });
      setOk(true);
      setPassword('');
    } catch (err) {
      setError(comoErrorApi(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section aria-labelledby="t-reset" className="tarjeta">
      <h2 id="t-reset">Restablecer contraseña de {usuario.nombre}</h2>
      <form onSubmit={enviar} noValidate>
        <Campo etiqueta="Nueva contraseña" error={errLocal ?? error?.detalleDe('password')}>
          {(p) => <input {...p} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Campo>
        <MensajeError error={error} camposMostrados={['password']} />
        {ok && <p role="status" className="alerta alerta-ok">Contraseña actualizada.</p>}
        <div className="acciones">
          <button type="submit" className="primario" disabled={enviando}>Guardar contraseña</button>
          <button type="button" onClick={onCerrar}>Cerrar</button>
        </div>
      </form>
    </section>
  );
}
