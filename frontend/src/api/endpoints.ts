import { solicitar } from './cliente';
import type {
  AplicaA, Campana, CampanaActualizar, CampanaCliente, CampanaCrear, ErrorImportacion, EstadoCampana,
  Exclusion, Festivo, Importacion, MotivoExclusion, Pagina, Politica, RespuestaLogin,
  ResultadoEvaluacion, ResultadoImportacionExclusiones, Rol, Severidad, TipoCampana, Usuario,
  ConfiguracionPolitica,
} from './tipos';

export interface ParamsPagina { page?: number; page_size?: number }

// Autenticación
export const iniciarSesion = (email: string, password: string) =>
  solicitar<RespuestaLogin>('POST', '/auth/login', { cuerpo: { email, password } });
export const obtenerYo = () => solicitar<Usuario>('GET', '/auth/me');

// Usuarios
export const listarUsuarios = (p: ParamsPagina & { rol?: Rol | ''; activo?: boolean | '' }) =>
  solicitar<Pagina<Usuario>>('GET', '/usuarios', { params: { ...p } });
export const crearUsuario = (c: { email: string; nombre: string; rol: Rol; password: string }) =>
  solicitar<Usuario>('POST', '/usuarios', { cuerpo: c });
export const actualizarUsuario = (id: number, c: { nombre?: string; rol?: Rol; activo?: boolean; password?: string }) =>
  solicitar<Usuario>('PATCH', `/usuarios/${id}`, { cuerpo: c });

// Campañas
export const listarCampanas = (p: ParamsPagina & { estado?: EstadoCampana | ''; tipo?: TipoCampana | ''; q?: string }) =>
  solicitar<Pagina<Campana>>('GET', '/campanas', { params: { ...p } });
export const obtenerCampana = (id: number) => solicitar<Campana>('GET', `/campanas/${id}`);
export const crearCampana = (c: CampanaCrear) => solicitar<Campana>('POST', '/campanas', { cuerpo: c });
export const actualizarCampana = (id: number, c: CampanaActualizar) =>
  solicitar<Campana>('PATCH', `/campanas/${id}`, { cuerpo: c });
export const eliminarCampana = (id: number) => solicitar<void>('DELETE', `/campanas/${id}`);

// Importaciones y clientes
export const subirImportacion = (campanaId: number, archivo: File) => {
  const f = new FormData();
  f.append('archivo', archivo);
  return solicitar<Importacion>('POST', `/campanas/${campanaId}/importaciones`, { formulario: f });
};
export const listarImportaciones = (campanaId: number, p: ParamsPagina) =>
  solicitar<Pagina<Importacion>>('GET', `/campanas/${campanaId}/importaciones`, { params: { ...p } });
export const obtenerImportacion = (id: number) => solicitar<Importacion>('GET', `/importaciones/${id}`);
export const listarErroresImportacion = (id: number, p: ParamsPagina & { severidad?: Severidad | '' }) =>
  solicitar<Pagina<ErrorImportacion>>('GET', `/importaciones/${id}/errores`, { params: { ...p } });
export const listarClientesCampana = (campanaId: number, p: ParamsPagina & { q?: string; estado?: string }) =>
  solicitar<Pagina<CampanaCliente>>('GET', `/campanas/${campanaId}/clientes`, { params: { ...p } });

// Exclusiones
export const listarExclusiones = (p: ParamsPagina & { q?: string; motivo?: MotivoExclusion | ''; aplica_a?: AplicaA | '' }) =>
  solicitar<Pagina<Exclusion>>('GET', '/exclusiones', { params: { ...p } });
export const crearExclusion = (c: { telefono: string; motivo: MotivoExclusion; aplica_a?: AplicaA; observacion?: string | null }) =>
  solicitar<Exclusion>('POST', '/exclusiones', { cuerpo: c });
export const eliminarExclusion = (id: number) => solicitar<void>('DELETE', `/exclusiones/${id}`);
export const importarExclusiones = (archivo: File, motivo: MotivoExclusion, aplicaA: AplicaA) => {
  const f = new FormData();
  f.append('archivo', archivo);
  f.append('motivo', motivo);
  f.append('aplica_a', aplicaA);
  return solicitar<ResultadoImportacionExclusiones>('POST', '/exclusiones/importar', { formulario: f });
};

// Cumplimiento
export const listarPoliticas = () => solicitar<Politica[]>('GET', '/cumplimiento/politicas');
export const listarVersionesPolitica = (tipo: TipoCampana) =>
  solicitar<Politica[]>('GET', `/cumplimiento/politicas/${tipo}/versiones`);
export const guardarPolitica = (tipo: TipoCampana, configuracion: ConfiguracionPolitica) =>
  solicitar<Politica>('PUT', `/cumplimiento/politicas/${tipo}`, { cuerpo: configuracion });
export const listarFestivos = (anio: number) => solicitar<Festivo[]>('GET', '/festivos', { params: { anio } });
export const generarFestivos = (anio: number) =>
  solicitar<{ anio: number; creados: number; existentes: number }>('POST', '/festivos/generar', { cuerpo: { anio } });
export const crearFestivo = (c: { fecha: string; nombre: string }) => solicitar<Festivo>('POST', '/festivos', { cuerpo: c });
export const actualizarFestivo = (id: number, c: { activo?: boolean; nombre?: string }) =>
  solicitar<Festivo>('PATCH', `/festivos/${id}`, { cuerpo: c });
export const evaluarCumplimiento = (c: { tipo_campana: TipoCampana; momento?: string }) =>
  solicitar<ResultadoEvaluacion>('POST', '/cumplimiento/evaluar', { cuerpo: c });
