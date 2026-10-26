import type { ErrorRespuesta } from './tipos';
import { leerSesion, limpiarSesion } from './sesion';

export const BASE_API = '/api/v1';

export interface DetalleError { campo: string | null; mensaje: string }

export class ErrorApi extends Error {
  readonly status: number;
  readonly codigo: string;
  readonly detalles: DetalleError[];

  constructor(status: number, codigo: string, mensaje: string, detalles: DetalleError[] = []) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.status = status;
    this.codigo = codigo;
    this.detalles = detalles;
  }

  /** Mensaje del detalle asociado a un campo (coincide por ruta exacta o por sufijo tras un punto). */
  detalleDe(campo: string): string | undefined {
    const d = this.detalles.find((x) => x.campo === campo || (x.campo ?? '').endsWith(`.${campo}`));
    return d?.mensaje;
  }

  /** Detalles que no corresponden a ninguno de los campos dados. */
  detallesSueltos(campos: string[]): DetalleError[] {
    return this.detalles.filter((d) => !d.campo || !campos.some((c) => d.campo === c || d.campo!.endsWith(`.${c}`)));
  }
}

export type Parametros = Record<string, string | number | boolean | null | undefined>;

export interface OpcionesSolicitud {
  params?: Parametros;
  cuerpo?: unknown;
  formulario?: FormData;
}

function construirQuery(params?: Parametros): string {
  if (!params) return '';
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

export function esErrorRespuesta(x: unknown): x is ErrorRespuesta {
  return typeof x === 'object' && x !== null && 'error' in x &&
    typeof (x as ErrorRespuesta).error === 'object' && (x as ErrorRespuesta).error !== null;
}

export async function solicitar<T>(
  metodo: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  ruta: string,
  opciones: OpcionesSolicitud = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const sesion = leerSesion();
  if (sesion) headers.Authorization = `Bearer ${sesion.token}`;

  let body: BodyInit | undefined;
  if (opciones.formulario) {
    body = opciones.formulario; // el navegador fija el multipart y su boundary
  } else if (opciones.cuerpo !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opciones.cuerpo);
  }

  let respuesta: Response;
  try {
    respuesta = await fetch(`${BASE_API}${ruta}${construirQuery(opciones.params)}`, { method: metodo, headers, body });
  } catch {
    throw new ErrorApi(0, 'RED', 'No se pudo conectar con el servidor. Verifique su conexión e intente de nuevo.');
  }

  if (respuesta.status === 204) return undefined as T;

  let datos: unknown = null;
  const texto = await respuesta.text();
  if (texto) {
    try {
      datos = JSON.parse(texto);
    } catch {
      datos = null;
    }
  }

  if (!respuesta.ok) {
    if (respuesta.status === 401) limpiarSesion();
    if (esErrorRespuesta(datos)) {
      const e = datos.error;
      throw new ErrorApi(respuesta.status, e.codigo, e.mensaje, Array.isArray(e.detalles) ? e.detalles : []);
    }
    throw new ErrorApi(respuesta.status, 'ERROR_DESCONOCIDO', `Error inesperado del servidor (HTTP ${respuesta.status}).`);
  }
  return datos as T;
}

/**
 * Descarga un binario protegido (p. ej. adjuntos de WhatsApp) con el Bearer de la sesión. El navegador no puede
 * usar `<img src>` con JWT: el llamador crea un `blob:` URL con el resultado (y debe revocarlo).
 */
export async function solicitarBlob(ruta: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const sesion = leerSesion();
  if (sesion) headers.Authorization = `Bearer ${sesion.token}`;
  let respuesta: Response;
  try {
    respuesta = await fetch(`${BASE_API}${ruta}`, { method: 'GET', headers });
  } catch {
    throw new ErrorApi(0, 'RED', 'No se pudo conectar con el servidor. Verifique su conexión e intente de nuevo.');
  }
  if (!respuesta.ok) {
    if (respuesta.status === 401) limpiarSesion();
    let datos: unknown = null;
    try {
      datos = JSON.parse(await respuesta.text());
    } catch {
      datos = null;
    }
    if (esErrorRespuesta(datos)) {
      const e = datos.error;
      throw new ErrorApi(respuesta.status, e.codigo, e.mensaje, Array.isArray(e.detalles) ? e.detalles : []);
    }
    throw new ErrorApi(respuesta.status, 'ERROR_DESCONOCIDO', `Error inesperado del servidor (HTTP ${respuesta.status}).`);
  }
  return respuesta.blob();
}
