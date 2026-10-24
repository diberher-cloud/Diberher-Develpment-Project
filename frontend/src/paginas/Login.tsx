import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { Campo } from '../componentes/Campo';
import { MensajeError } from '../componentes/MensajeError';
import { comoErrorApi } from '../utilidades/useCarga';
import type { ErrorApi } from '../api/cliente';

export function Login() {
  const { usuario, login } = useAuth();
  const navegar = useNavigate();
  const ubicacion = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);

  const desde = (ubicacion.state as { desde?: string } | null)?.desde;
  const destinoPara = (rol?: string) => desde ?? (rol === 'agente' ? '/consola' : '/campanas');
  const destino = destinoPara(usuario?.rol);
  if (usuario) return <Navigate to={destino} replace />;

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const u = await login(email.trim(), password);
      navegar(destinoPara(u.rol), { replace: true });
    } catch (err) {
      setError(comoErrorApi(err));
      setEnviando(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={enviar} noValidate aria-labelledby="titulo-login" className="tarjeta">
        <h1 id="titulo-login">Iniciar sesión</h1>
        <Campo etiqueta="Correo electrónico" error={error?.detalleDe('email')}>
          {(p) => (
            <input {...p} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          )}
        </Campo>
        <Campo etiqueta="Contraseña" error={error?.detalleDe('password')}>
          {(p) => (
            <input {...p} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          )}
        </Campo>
        <MensajeError error={error} camposMostrados={['email', 'password']} />
        <button type="submit" className="primario" disabled={enviando}>
          {enviando ? 'Ingresando…' : 'Ingresar'}
        </button>
      </form>
    </main>
  );
}
