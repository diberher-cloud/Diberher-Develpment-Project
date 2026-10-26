import type {
  ConfiguracionWhatsApp, Conversacion, ConversacionResumen, ItemCola, Mensaje, Plantilla, FichaCliente,
} from '../api/tipos';

export const AHORA = Date.now();
export const enHoras = (h: number) => new Date(AHORA + h * 3_600_000).toISOString();
export const haceMin = (m: number) => new Date(AHORA - m * 60_000).toISOString();

export const configuracion = (o: Partial<ConfiguracionWhatsApp> = {}): ConfiguracionWhatsApp => ({
  proveedor: 'falso', simulacion: true, numero_empresa_mascara: '+57300****001', margen_ventana_segundos: 60,
  max_caracteres_texto: 4096, max_conversaciones_agente: 5, media_max_bytes: 16777216, ...o,
});

export const conversacion = (o: Partial<Conversacion> = {}): Conversacion => ({
  id: 12, estado: 'abierta', atendida_por: 'humano', usuario_asignado: { id: 1, nombre: 'Usuario agente' },
  numero_mascara: '+57300****567', numero_e164: null, nombre_perfil: 'María', campana: { id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza' },
  cliente_nombre: 'María Pérez', iniciada_por: 'cliente', ventana_abierta: true, ventana_expira_en: enHoras(20),
  ultimo_mensaje_en: haceMin(5), mensajes_sin_leer: 0, motivo_cola: null, abierta_en: haceMin(30), cerrada_en: null, motivo_cierre: null,
  campana_cliente_id: 15, cliente_id: 9, telefono_id: 21, tipificada: false, puede_responder: true, motivos_no_responder: [], alertas: [],
  ...o,
});

export const resumen = (o: Partial<ConversacionResumen> = {}): ConversacionResumen => {
  const { campana_cliente_id: _a, cliente_id: _b, telefono_id: _c, tipificada: _d, puede_responder: _e, motivos_no_responder: _f, alertas: _g, ...r } = conversacion(o);
  void [_a, _b, _c, _d, _e, _f, _g];
  return r;
};

export const mensaje = (o: Partial<Mensaje> = {}): Mensaje => ({
  id: 101, conversacion_id: 12, direccion: 'entrante', autor: 'cliente', usuario: null, tipo: 'texto', cuerpo: 'Hola, quiero pagar',
  plantilla: null, media: [], boton: null, estado: 'recibido', error: null, programado_para: null,
  creado_en: haceMin(10), enviado_en: null, entregado_en: null, leido_en: null, ...o,
});

export const itemCola = (o: Partial<ItemCola> = {}): ItemCola => ({
  id: 40, conversacion_id: 12, campana: { id: 1, nombre: 'Cobranza cartera octubre' }, motivo: 'entrante', prioridad: 2,
  resumen: null, numero_mascara: '+57300****567', creado_en: haceMin(2), espera_segundos: 95, ...o,
});

export const plantilla = (o: Partial<Plantilla> = {}): Plantilla => ({
  id: 3, content_sid: 'HXfalso0001', nombre: 'recordatorio_cobranza', idioma: 'es', categoria: 'utility', estado_aprobacion: 'aprobada',
  motivo_rechazo: null, cuerpo: 'Hola {{1}}, le escribimos de {{2}}. ¿Podemos conversar sobre su cuenta?', variables: ['1', '2'], botones: [],
  tiene_boton_baja: false, mapeo_variables: { '1': 'primer_nombre', '2': 'empresa' }, finalidad: 'cobranza', activa: true, enviable: true,
  sincronizada_en: haceMin(60), ...o,
});

export const fichaConWhatsApp = (o: Partial<FichaCliente> = {}): FichaCliente => ({
  id: 15, campana: { id: 1, nombre: 'Cobranza cartera octubre', tipo: 'cobranza' }, estado: 'en_gestion',
  reservado_hasta: enHoras(1), intentos: 1, max_intentos: 3, ultimo_resultado: null, proximo_intento_en: null,
  cliente: { id: 9, tipo_documento: 'CC', numero_documento: '1020304050', nombre: 'María Pérez', email: null, ciudad: 'Bogotá' },
  telefonos: [
    {
      id: 21, numero_mascara: '+57300****567', tipo_linea: 'movil', prioridad: 1, excluido: false, llamable: true, motivos: [],
      whatsapp: { autorizado: true, excluido: false, enviable: true, motivos: [], conversacion_abierta: null },
    },
  ],
  numero_obligacion: 'OB-001', saldo_total: '1500000.00', saldo_mora: '250000.50', dias_mora: 45, fecha_vencimiento: '2026-09-15',
  producto: null, oferta: null, datos_adicionales: {}, guion: null,
  cumplimiento: { permitido: true, motivos: [], momento_local: '2026-10-23T10:15:00-05:00', proxima_ventana_inicio: null, politica_version: 1 },
  historial: [], ...o,
});

export const pagina = <T,>(items: T[], total = items.length) => ({ items, total, page: 1, page_size: 20 });

/** Parámetros de query de una URL relativa de la API. */
export const consulta = (url: string) => new URL(url, 'http://localhost').searchParams;
