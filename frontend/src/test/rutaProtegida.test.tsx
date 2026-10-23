import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthContext';
import { RutaProtegida } from '../auth/RutaProtegida';
import { iniciarSesionComo, paginaVacia, renderizarApp, respuesta, simularFetch } from './utiles';

function montar(ruta: string, roles?: Parameters<typeof RutaProtegida>[0]['roles']) {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<p>Pantalla de login</p>} />
          <Route path="/secreto" element={<RutaProtegida roles={roles}><p>Contenido secreto</p></RutaProtegida>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('RutaProtegida', () => {
  it('sin sesión redirige a /login', () => {
    montar('/secreto');
    expect(screen.getByText('Pantalla de login')).toBeInTheDocument();
    expect(screen.queryByText('Contenido secreto')).not.toBeInTheDocument();
  });

  it('con sesión y rol permitido muestra el contenido', () => {
    iniciarSesionComo('supervisor');
    montar('/secreto', ['administrador', 'supervisor']);
    expect(screen.getByText('Contenido secreto')).toBeInTheDocument();
  });

  it('un agente en una ruta de administrador ve "No autorizado"', () => {
    iniciarSesionComo('agente');
    montar('/secreto', ['administrador']);
    expect(screen.getByRole('alert')).toHaveTextContent('No autorizado');
    expect(screen.queryByText('Contenido secreto')).not.toBeInTheDocument();
  });

  it('en la app, un agente que abre /usuarios ve "No autorizado" y el menú solo tiene Campañas y Cumplimiento', async () => {
    iniciarSesionComo('agente');
    simularFetch((url) => (url.startsWith('/api/v1/campanas') ? respuesta(200, paginaVacia) : undefined));
    renderizarApp('/usuarios');
    expect(await screen.findByText('No autorizado')).toBeInTheDocument();
    const menu = screen.getByRole('navigation', { name: 'Principal' });
    expect(menu).toHaveTextContent('Campañas');
    expect(menu).toHaveTextContent('Cumplimiento');
    expect(menu).not.toHaveTextContent('Usuarios');
    expect(menu).not.toHaveTextContent('Exclusiones');
  });
});
