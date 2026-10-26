import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './componentes/Layout';
import { RutaProtegida } from './auth/RutaProtegida';
import { Login } from './paginas/Login';
import { Campanas } from './paginas/Campanas';
import { CampanaFormulario } from './paginas/CampanaFormulario';
import { CampanaDetalle } from './paginas/CampanaDetalle';
import { ImportacionDetalle } from './paginas/ImportacionDetalle';
import { Exclusiones } from './paginas/Exclusiones';
import { Cumplimiento } from './paginas/Cumplimiento';
import { Usuarios } from './paginas/Usuarios';
import { Consola } from './paginas/Consola';
import { SupervisionAgentes } from './paginas/SupervisionAgentes';
import { Bandeja } from './paginas/Bandeja';
import { PlantillasWhatsApp } from './paginas/PlantillasWhatsApp';
import { Autorizaciones } from './paginas/Autorizaciones';
import { SimuladorWhatsApp } from './paginas/SimuladorWhatsApp';

const GESTION = ['administrador', 'supervisor'] as const;

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RutaProtegida>
            <Layout />
          </RutaProtegida>
        }
      >
        <Route path="/campanas" element={<Campanas />} />
        <Route
          path="/campanas/nueva"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <CampanaFormulario />
            </RutaProtegida>
          }
        />
        <Route path="/campanas/:id" element={<CampanaDetalle />} />
        <Route
          path="/campanas/:id/editar"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <CampanaFormulario />
            </RutaProtegida>
          }
        />
        <Route
          path="/importaciones/:id"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <ImportacionDetalle />
            </RutaProtegida>
          }
        />
        <Route
          path="/exclusiones"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <Exclusiones />
            </RutaProtegida>
          }
        />
        <Route
          path="/consola"
          element={
            <RutaProtegida roles={['agente']}>
              <Consola />
            </RutaProtegida>
          }
        />
        <Route
          path="/supervision/agentes"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <SupervisionAgentes />
            </RutaProtegida>
          }
        />
        <Route path="/bandeja" element={<Bandeja />} />
        <Route
          path="/whatsapp/plantillas"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <PlantillasWhatsApp />
            </RutaProtegida>
          }
        />
        <Route
          path="/autorizaciones"
          element={
            <RutaProtegida roles={[...GESTION]}>
              <Autorizaciones />
            </RutaProtegida>
          }
        />
        <Route path="/whatsapp/simulador" element={<SimuladorWhatsApp />} />
        <Route path="/cumplimiento" element={<Cumplimiento />} />
        <Route
          path="/usuarios"
          element={
            <RutaProtegida roles={['administrador']}>
              <Usuarios />
            </RutaProtegida>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/campanas" replace />} />
    </Routes>
  );
}
