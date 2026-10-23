import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { iniciarSesion } from '../api/endpoints';
import { alLimpiarSesion, guardarSesion, leerSesion, limpiarSesion, type Sesion } from '../api/sesion';
import type { Rol, Usuario } from '../api/tipos';

interface ValorAuth {
  usuario: Usuario | null;
  login: (email: string, password: string) => Promise<Usuario>;
  logout: () => void;
  tieneRol: (...roles: Rol[]) => boolean;
}

const AuthContext = createContext<ValorAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [sesion, setSesion] = useState<Sesion | null>(() => leerSesion());

  // Cualquier 401 (o logout) limpia sessionStorage y notifica aquí.
  useEffect(() => alLimpiarSesion(() => setSesion(null)), []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await iniciarSesion(email, password);
    const nueva = { token: r.access_token, usuario: r.usuario };
    guardarSesion(nueva);
    setSesion(nueva);
    return r.usuario;
  }, []);

  const logout = useCallback(() => limpiarSesion(), []);

  const valor = useMemo<ValorAuth>(() => {
    const usuario = sesion?.usuario ?? null;
    return { usuario, login, logout, tieneRol: (...roles) => !!usuario && roles.includes(usuario.rol) };
  }, [sesion, login, logout]);

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): ValorAuth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth debe usarse dentro de <AuthProvider>.');
  return ctx;
}
