import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useWhatsApp, WhatsAppProvider } from './ContextoWhatsApp';
import { AvisosIA } from './ia/AvisosIA';

export function Layout() {
  return (
    <WhatsAppProvider>
      <Estructura />
    </WhatsAppProvider>
  );
}

function Estructura() {
  const { configuracion, noLeidos } = useWhatsApp();
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
          {tieneRol('agente') && <NavLink to="/consola">Consola</NavLink>}
          <NavLink to="/bandeja">{noLeidos > 0 ? `Bandeja (${noLeidos})` : 'Bandeja'}</NavLink>
          {tieneRol('administrador', 'supervisor') && <NavLink to="/supervision/agentes">Supervisión</NavLink>}
          {tieneRol('administrador', 'supervisor') && <NavLink to="/supervision/ia">Supervisión IA</NavLink>}
          {tieneRol('administrador', 'supervisor') && <NavLink to="/ia/evaluaciones">Evaluaciones IA</NavLink>}
          {tieneRol('administrador', 'supervisor') && <NavLink to="/exclusiones">Exclusiones</NavLink>}
          {tieneRol('administrador', 'supervisor') && <NavLink to="/whatsapp/plantillas">Plantillas</NavLink>}
          {tieneRol('administrador', 'supervisor') && <NavLink to="/autorizaciones">Autorizaciones</NavLink>}
          {configuracion?.simulacion === true && <NavLink to="/whatsapp/simulador">Simulador WhatsApp</NavLink>}
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
      <AvisosIA />
      <main id="contenido" className="contenido">
        <Outlet />
      </main>
    </>
  );
}
