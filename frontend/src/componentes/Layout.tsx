import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

export function Layout() {
  const { usuario, logout, tieneRol } = useAuth();
  const navegar = useNavigate();

  function salir() {
    logout();
    navegar('/login', { replace: true });
  }

  return (
    <>
      <a className="saltar" href="#contenido">
        Saltar al contenido
      </a>
      <header className="cabecera">
        <strong className="marca">Campañas outbound</strong>
        <nav aria-label="Principal" className="menu">
          <NavLink to="/campanas">Campañas</NavLink>
          {tieneRol('administrador', 'supervisor') && <NavLink to="/exclusiones">Exclusiones</NavLink>}
          <NavLink to="/cumplimiento">Cumplimiento</NavLink>
          {tieneRol('administrador') && <NavLink to="/usuarios">Usuarios</NavLink>}
        </nav>
        <div className="sesion">
          <span>
            {usuario?.nombre} ({usuario?.rol})
          </span>
          <button type="button" onClick={salir}>
            Cerrar sesión
          </button>
        </div>
      </header>
      <main id="contenido" className="contenido">
        <Outlet />
      </main>
    </>
  );
}
