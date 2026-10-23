import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { AuthProvider } from './auth/AuthContext';
import { TiempoRealProvider } from './tiempo_real/TiempoRealContext';
import './estilos.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <TiempoRealProvider>
          <App />
        </TiempoRealProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
