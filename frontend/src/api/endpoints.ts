import { solicitar } from './cliente';
import type {
  AplicaA, Campana, CampanaActualizar, CampanaCliente, CampanaCrear, ErrorImportacion, EstadoCampana,
  Exclusion, Festivo, Importacion, MotivoExclusion, Pagina, Politica, RespuestaLogin,
  ResultadoEvaluacion, ResultadoImportacionExclusiones, Rol, Severidad, TipoCampana, Usuario,
  ConfiguracionPolitica, AgenteAsignado, AgenteSupervision, CambioEstadoAgente, Canal, CampanaConsola,
  EstadoAgente, EventoSimulacion, FichaCliente, Llamada, OrigenGestion, RegistroTrabajo, ResultadoSimulacion,
  ResultadoTipificacion, TipificacionCrear, Tipificacion, TokenTelefonia,
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
export const evaluarCumplimiento = (c: { tipo_campana: TipoCampana; momento?: string; canal?: Canal; cliente_id?: number }) =>
  solicitar<ResultadoEvaluacion>('POST', '/cumplimiento/evaluar', { cuerpo: c });

// Fase 2A: asignación de agentes (A, S)
export const listarAgentesCampana = (campanaId: number) =>
  solicitar<AgenteAsignado[]>('GET', `/campanas/${campanaId}/agentes`);
export const reemplazarAgentesCampana = (campanaId: number, usuarioIds: number[]) =>
  solicitar<AgenteAsignado[]>('PUT', `/campanas/${campanaId}/agentes`, { cuerpo: { usuario_ids: usuarioIds } });

// Fase 2A: tipificaciones de campaña y supervisión (A, S)
export const listarTipificacionesCampana = (
  campanaId: number,
  p: ParamsPagina & { resultado?: ResultadoTipificacion | ''; origen?: OrigenGestion | ''; desde?: string; hasta?: string },
) => solicitar<Pagina<Tipificacion>>('GET', `/campanas/${campanaId}/tipificaciones`, { params: { ...p } });
export const listarAgentesSupervision = () => solicitar<AgenteSupervision[]>('GET', '/supervision/agentes');

// Fase 2A: consola del agente (G)
export const obtenerEstadoAgente = () => solicitar<EstadoAgente>('GET', '/consola/estado');
export const cambiarEstadoAgente = (c: CambioEstadoAgente) => solicitar<EstadoAgente>('PUT', '/consola/estado', { cuerpo: c });
export const listarCampanasConsola = () => solicitar<CampanaConsola[]>('GET', '/consola/campanas');
export const listarRegistrosConsola = (p: ParamsPagina & { campana_id?: number | '' }) =>
  solicitar<Pagina<RegistroTrabajo>>('GET', '/consola/registros', { params: { ...p } });
export const tomarRegistro = (id: number) => solicitar<FichaCliente>('POST', `/consola/registros/${id}/tomar`);
export const soltarRegistro = (id: number) => solicitar<void>('POST', `/consola/registros/${id}/soltar`);
export const obtenerFicha = (id: number) => solicitar<FichaCliente>('GET', `/consola/registros/${id}`);
export const obtenerLlamada = (id: number) => solicitar<Llamada>('GET', `/consola/llamadas/${id}`);
export const crearTipificacion = (c: TipificacionCrear) => solicitar<Tipificacion>('POST', '/consola/tipificaciones', { cuerpo: c });

// Fase 2A: telefonía
export const obtenerTokenTelefonia = () => solicitar<TokenTelefonia>('POST', '/telefonia/token');
export const simularLlamada = (c: { campana_cliente_id: number; telefono_id: number }) =>
  solicitar<ResultadoSimulacion>('POST', '/telefonia/simulacion/llamadas', { cuerpo: c });
export const simularEventoLlamada = (llamadaId: number, e: EventoSimulacion) =>
  solicitar<void>('POST', `/telefonia/simulacion/llamadas/${llamadaId}/eventos`, { cuerpo: e });
