import type { EventoSimulacion, Motivo } from '../api/tipos';

export type EstadoSoftphone = 'inactivo' | 'registrando' | 'listo' | 'conectando' | 'en_curso' | 'finalizada' | 'error';

/** Interfaz común del softphone (fase-2.md §4.11). */
export interface Softphone {
  /** Obtiene el token y prepara el dispositivo. */
  iniciar(): Promise<void>;
  llamar(params: { campana_cliente_id: number; telefono_id: number }): Promise<void>;
  colgar(): void;
  silenciar(activo: boolean): void;
  destruir(): void;
  /** Devuelve la función de baja. */
  onEstado(cb: (estado: EstadoSoftphone, detalle?: string) => void): () => void;
}

/** Extensión del softphone falso: la consola muestra botones de simulación solo con este tipo. */
export interface SoftphoneSimulable extends Softphone {
  readonly simulable: true;
  /** Motivos devueltos por el servidor cuando la última llamada no se permitió. */
  readonly motivosBloqueo: Motivo[];
  simular(evento: EventoSimulacion): Promise<void>;
}

export function esSimulable(s: Softphone | null): s is SoftphoneSimulable {
  return !!s && (s as Partial<SoftphoneSimulable>).simulable === true;
}

export type OyenteEstado = (estado: EstadoSoftphone, detalle?: string) => void;

/** Emisor de estado compartido por las implementaciones. */
export class EmisorEstado {
  private oyentes = new Set<OyenteEstado>();
  private _estado: EstadoSoftphone = 'inactivo';

  get estado(): EstadoSoftphone {
    return this._estado;
  }

  emitir(estado: EstadoSoftphone, detalle?: string): void {
    this._estado = estado;
    this.oyentes.forEach((o) => o(estado, detalle));
  }

  suscribir(cb: OyenteEstado): () => void {
    this.oyentes.add(cb);
    return () => {
      this.oyentes.delete(cb);
    };
  }

  limpiar(): void {
    this.oyentes.clear();
  }
}
