import { solicitar, solicitarBlob } from './cliente';
import type {
  AplicaA, Campana, CampanaActualizar, CampanaCliente, CampanaCrear, ErrorImportacion, EstadoCampana,
  Exclusion, Festivo, Importacion, MotivoExclusion, Pagina, Politica, RespuestaLogin,
  ResultadoEvaluacion, ResultadoImportacionExclusiones, Rol, Severidad, TipoCampana, Usuario,
  ConfiguracionPolitica, AgenteAsignado, AgenteSupervision, CambioEstadoAgente, Canal, CampanaConsola,
  EstadoAgente, EventoSimulacion, FichaCliente, Llamada, OrigenGestion, RegistroTrabajo, ResultadoSimulacion,
  ResultadoTipificacion, TipificacionCrear, Tipificacion, TokenTelefonia, TicketWs,
  Autorizacion, AutorizacionConversacionCrear, AutorizacionCrear, AtendidaPor, CanalExclusion, CierreConversacion,
  CierreConversacionCrear, ConfiguracionWhatsApp, Conversacion, ConversacionResumen, EstadoConversacion,
  EstadoTrabajos, Finalidad, ItemCola, Mensaje, MensajeTextoCrear, PaginaMensajes, Plantilla, PlantillaActualizar,
  PlantillaConsolaCrear, PlantillaEnvioCrear, RegistroCandidato, ResultadoEnvioPlantilla, ResultadoSincronizacion,
  SimulacionEntrante,
  AccionIA, ConfiguracionGlobalIA, ConfiguracionIA, ConfiguracionIAActualizar, ConversacionIAResumen, EvaluacionCrear,
  EvaluacionIA, Instruccion, MetricasIA, Oferta, OfertaActualizar, OfertaCrear, UsoIAConversacion,
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
export const listarExclusiones = (
  p: ParamsPagina & { q?: string; motivo?: MotivoExclusion | ''; aplica_a?: AplicaA | ''; canal?: CanalExclusion | '' },
) => solicitar<Pagina<Exclusion>>('GET', '/exclusiones', { params: { ...p } });
export const crearExclusion = (
  c: { telefono: string; motivo: MotivoExclusion; aplica_a?: AplicaA; observacion?: string | null; canal?: CanalExclusion },
) =>
  solicitar<Exclusion>('POST', '/exclusiones', { cuerpo: c });
export const eliminarExclusion = (id: number) => solicitar<void>('DELETE', `/exclusiones/${id}`);
export const importarExclusiones = (archivo: File, motivo: MotivoExclusion, aplicaA: AplicaA, canal: CanalExclusion = 'todos') => {
  const f = new FormData();
  f.append('archivo', archivo);
  f.append('motivo', motivo);
  f.append('aplica_a', aplicaA);
  if (canal !== 'todos') f.append('canal', canal);
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

// Tiempo real: ticket de un solo uso para abrir el WebSocket
export const obtenerTicketWs = () => solicitar<TicketWs>('POST', '/ws/ticket');

// Fase 2B: WhatsApp (configuración, plantillas, autorizaciones)
export const obtenerConfiguracionWhatsApp = () => solicitar<ConfiguracionWhatsApp>('GET', '/whatsapp/configuracion');
export const listarPlantillas = (p: { campana_id?: number | ''; enviables?: boolean } = {}) =>
  solicitar<Plantilla[]>('GET', '/whatsapp/plantillas', { params: { ...p } });
export const sincronizarPlantillas = () => solicitar<ResultadoSincronizacion>('POST', '/whatsapp/plantillas/sincronizar');
export const actualizarPlantilla = (id: number, c: PlantillaActualizar) =>
  solicitar<Plantilla>('PUT', `/whatsapp/plantillas/${id}`, { cuerpo: c });
export const listarAutorizaciones = (p: ParamsPagina & { numero?: string; finalidad?: Finalidad | ''; vigentes?: boolean | '' }) =>
  solicitar<Pagina<Autorizacion>>('GET', '/autorizaciones', { params: { ...p } });
export const crearAutorizacion = (c: AutorizacionCrear) => solicitar<Autorizacion>('POST', '/autorizaciones', { cuerpo: c });
export const revocarAutorizacion = (id: number) => solicitar<void>('DELETE', `/autorizaciones/${id}`);

// Fase 2B: bandeja de conversaciones
export const listarConversaciones = (
  p: ParamsPagina & {
    estado?: EstadoConversacion | ''; atendida_por?: AtendidaPor | ''; campana_id?: number | ''; sin_campana?: boolean | '';
    usuario_id?: number | '';
  },
) => solicitar<Pagina<ConversacionResumen>>('GET', '/conversaciones', { params: { ...p } });
/** `apertura=true` solo al abrir la conversación en la bandeja (audita `conversacion.ver`); las recargas van sin él. */
export const obtenerConversacion = (id: number, apertura = false) =>
  solicitar<Conversacion>('GET', `/conversaciones/${id}`, { params: { apertura: apertura ? true : undefined } });
export const listarMensajes = (id: number, p: { antes_de?: number; limite?: number } = {}) =>
  solicitar<PaginaMensajes>('GET', `/conversaciones/${id}/mensajes`, { params: { ...p } });
export const marcarLeida = (id: number) => solicitar<void>('POST', `/conversaciones/${id}/leida`);
export const enviarTexto = (id: number, c: MensajeTextoCrear) =>
  solicitar<Mensaje>('POST', `/conversaciones/${id}/mensajes`, { cuerpo: c });
export const enviarPlantillaConversacion = (id: number, c: PlantillaEnvioCrear) =>
  solicitar<ResultadoEnvioPlantilla>('POST', `/conversaciones/${id}/plantillas`, { cuerpo: c });
export const enviarPlantillaConsola = (registroId: number, c: PlantillaConsolaCrear) =>
  solicitar<ResultadoEnvioPlantilla>('POST', `/consola/registros/${registroId}/whatsapp/plantilla`, { cuerpo: c });
export const tomarConversacion = (id: number) => solicitar<Conversacion>('POST', `/conversaciones/${id}/tomar`);
export const tomarSiguiente = () => solicitar<Conversacion | undefined>('POST', '/atencion/tomar-siguiente');
export const asignarConversacion = (id: number, usuarioId: number) =>
  solicitar<Conversacion>('POST', `/conversaciones/${id}/asignar`, { cuerpo: { usuario_id: usuarioId } });
export const liberarConversacion = (id: number) => solicitar<Conversacion>('POST', `/conversaciones/${id}/liberar`);
export const cerrarConversacion = (id: number, c: CierreConversacionCrear) =>
  solicitar<CierreConversacion>('POST', `/conversaciones/${id}/cerrar`, { cuerpo: c });
export const optOutConversacion = (id: number, alcance: 'whatsapp' | 'todos') =>
  solicitar<Conversacion>('POST', `/conversaciones/${id}/opt-out`, { cuerpo: { alcance } });
export const autorizarConversacion = (id: number, c: AutorizacionConversacionCrear) =>
  solicitar<Autorizacion>('POST', `/conversaciones/${id}/autorizacion`, { cuerpo: c });
export const listarRegistrosCandidatos = (id: number) =>
  solicitar<RegistroCandidato[]>('GET', `/conversaciones/${id}/registros-candidatos`);
export const vincularRegistro = (id: number, campanaClienteId: number) =>
  solicitar<Conversacion>('PUT', `/conversaciones/${id}/registro`, { cuerpo: { campana_cliente_id: campanaClienteId } });
export const obtenerFichaConversacion = (id: number) => solicitar<FichaCliente>('GET', `/conversaciones/${id}/ficha`);
export const listarColaAtencion = (p: { campana_id?: number | ''; motivo?: string } = {}) =>
  solicitar<ItemCola[]>('GET', '/atencion/cola', { params: { ...p } });
/** Adjunto entrante por el proxy autenticado (nunca la URL de Twilio). */
export const descargarMedia = (conversacionId: number, mensajeId: number, indice: number) =>
  solicitarBlob(`/conversaciones/${conversacionId}/mensajes/${mensajeId}/media/${indice}`);

// Fase 2B: supervisión del worker y simulación
export const obtenerEstadoTrabajos = () => solicitar<EstadoTrabajos>('GET', '/supervision/trabajos');
export const simularEntranteWhatsApp = (c: SimulacionEntrante) =>
  solicitar<{ mensaje_id: number; proveedor_id: string }>('POST', '/whatsapp/simulacion/entrante', { cuerpo: c });
export const simularEstadoMensaje = (
  mensajeId: number, c: { estado: 'delivered' | 'read' | 'failed' | 'undelivered'; error_codigo?: string | null },
) => solicitar<void>('POST', `/whatsapp/simulacion/mensajes/${mensajeId}/estado`, { cuerpo: c });

// Fase 2C: agente IA (configuración por campaña, ofertas, global)
export const obtenerConfiguracionIA = (campanaId: number) => solicitar<ConfiguracionIA>('GET', `/campanas/${campanaId}/ia`);
export const guardarConfiguracionIA = (campanaId: number, c: ConfiguracionIAActualizar) =>
  solicitar<ConfiguracionIA>('PUT', `/campanas/${campanaId}/ia`, { cuerpo: c });
export const activarIA = (campanaId: number) => solicitar<ConfiguracionIA>('POST', `/campanas/${campanaId}/ia/activar`);
export const desactivarIA = (campanaId: number) =>
  solicitar<ConfiguracionIA>('POST', `/campanas/${campanaId}/ia/desactivar`, { cuerpo: {} });
export const listarOfertas = (campanaId: number, activas?: boolean) =>
  solicitar<Oferta[]>('GET', `/campanas/${campanaId}/ofertas`, { params: { activas } });
export const crearOferta = (campanaId: number, c: OfertaCrear) =>
  solicitar<Oferta>('POST', `/campanas/${campanaId}/ofertas`, { cuerpo: c });
export const actualizarOferta = (campanaId: number, ofertaId: number, c: OfertaActualizar) =>
  solicitar<Oferta>('PATCH', `/campanas/${campanaId}/ofertas/${ofertaId}`, { cuerpo: c });
export const obtenerConfiguracionGlobalIA = () => solicitar<ConfiguracionGlobalIA>('GET', '/configuracion/ia');
export const guardarConfiguracionGlobalIA = (iaActiva: boolean) =>
  solicitar<ConfiguracionGlobalIA>('PUT', '/configuracion/ia', { cuerpo: { ia_activa: iaActiva } });

// Fase 2C: supervisión de la IA y conversaciones
export const listarConversacionesIA = (
  p: ParamsPagina & {
    campana_id?: number | ''; estado?: EstadoConversacion | ''; atendida_por?: AtendidaPor | ''; con_gestion?: boolean | '';
    identidad?: 'verificada' | 'no_verificada' | ''; desde?: string; hasta?: string;
  },
) => solicitar<Pagina<ConversacionIAResumen>>('GET', '/supervision/ia/conversaciones', { params: { ...p } });
export const obtenerMetricasIA = (p: { campana_id?: number | ''; desde?: string; hasta?: string } = {}) =>
  solicitar<MetricasIA>('GET', '/supervision/ia/metricas', { params: { ...p } });
export const listarAccionesIA = (id: number) => solicitar<AccionIA[]>('GET', `/conversaciones/${id}/acciones-ia`);
export const obtenerUsoIA = (id: number) => solicitar<UsoIAConversacion>('GET', `/conversaciones/${id}/uso-ia`);
export const listarInstrucciones = (id: number) => solicitar<Instruccion[]>('GET', `/conversaciones/${id}/instrucciones`);
export const crearInstruccion = (id: number, texto: string) =>
  solicitar<Instruccion>('POST', `/conversaciones/${id}/instrucciones`, { cuerpo: { texto } });
export const traspasarConversacion = (id: number, resumen?: string) =>
  solicitar<Conversacion>('POST', `/conversaciones/${id}/traspasar`, { cuerpo: resumen ? { resumen } : {} });
export const devolverConversacionIA = (id: number) =>
  solicitar<Conversacion>('POST', `/conversaciones/${id}/devolver-ia`, { cuerpo: {} });

// Fase 2C: evaluaciones de la IA
export const listarEvaluaciones = (p: ParamsPagina & { modo?: 'offline' | 'online' | ''; campana_id?: number | '' }) =>
  solicitar<Pagina<EvaluacionIA>>('GET', '/ia/evaluaciones', { params: { ...p } });
export const obtenerEvaluacion = (id: number) => solicitar<EvaluacionIA>('GET', `/ia/evaluaciones/${id}`);
export const lanzarEvaluacion = (c: EvaluacionCrear) => solicitar<EvaluacionIA>('POST', '/ia/evaluaciones', { cuerpo: c });
