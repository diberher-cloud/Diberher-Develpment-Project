import type { ReactNode } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import type { Rol } from '../api/tipos';
import { useAuth } from './AuthContext';

interface Props {
  roles?: Rol[];
  children?: ReactNode;
}

/** Exige sesión (si no, /login) y, opcionalmente, uno de los roles indicados. */
export function RutaProtegida({ roles, children }: Props) {
  const { usuario } = useAuth();
  const ubicacion = useLocation();

  if (!usuario) return <Navigate to="/login" replace state={{ desde: ubicacion.pathname }} />;
  if (roles && !roles.includes(usuario.rol)) {
    return (
      <div role="alert" className="alerta alerta-error">
        <h2>No autorizado</h2>
        <p>Su rol ({usuario.rol}) no tiene permiso para ver esta sección.</p>
      </div>
    );
  }
  return <>{children ?? <Outlet />}</>;
}
