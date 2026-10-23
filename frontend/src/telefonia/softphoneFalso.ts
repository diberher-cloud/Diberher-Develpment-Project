import { ErrorApi } from '../api/cliente';
import { simularEventoLlamada, simularLlamada } from '../api/endpoints';
import type { EventoSimulacion, Motivo, TokenTelefonia } from '../api/tipos';
import { EmisorEstado, type EstadoSoftphone, type SoftphoneSimulable } from './softphone';

/** Softphone sin audio: usa los endpoints de simulación del backend (proveedor `falso`). */
export class SoftphoneFalso implements SoftphoneSimulable {
  readonly simulable = true as const;
  private emisor = new EmisorEstado();
  private llamadaId: number | null = null;
  private contestadaEn: number | null = null;
  private _motivos: Motivo[] = [];

  // El token falso solo identifica el modo; la autenticación de la simulación es la sesión JWT.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  constructor(_token?: TokenTelefonia) {}

  get motivosBloqueo(): Motivo[] {
    return this._motivos;
  }

  async iniciar(): Promise<void> {
    this.emisor.emitir('registrando');
    this.emisor.emitir('listo');
  }

  async llamar(params: { campana_cliente_id: number; telefono_id: number }): Promise<void> {
    this._motivos = [];
    this.contestadaEn = null;
    this.llamadaId = null;
    this.emisor.emitir('conectando');
    try {
      const r = await simularLlamada(params);
      this.llamadaId = r.llamada_id;
      if (!r.permitida || r.llamada_id === null) {
        this._motivos = r.motivos;
        this.llamadaId = null;
        this.emisor.emitir('finalizada', r.motivos.map((m) => m.mensaje).join(' ') || 'La llamada no está permitida.');
      }
    } catch (e) {
      this.llamadaId = null;
      this.emisor.emitir('error', e instanceof ErrorApi ? e.message : 'No se pudo iniciar la llamada.');
    }
  }

  async simular(evento: EventoSimulacion): Promise<void> {
    if (this.llamadaId === null) return;
    const id = this.llamadaId;
    try {
      await simularEventoLlamada(id, evento);
    } catch (e) {
      this.emisor.emitir('error', e instanceof ErrorApi ? e.message : 'No se pudo simular el evento.');
      return;
    }
    if (evento.evento === 'contestada') {
      this.contestadaEn = Date.now();
      this.emisor.emitir('en_curso');
    } else {
      this.llamadaId = null;
      this.emisor.emitir('finalizada');
    }
  }

  colgar(): void {
    if (this.llamadaId === null) return;
    const duracion = this.contestadaEn === null ? undefined : Math.max(0, Math.round((Date.now() - this.contestadaEn) / 1000));
    void this.simular(
      duracion === undefined
        ? { evento: 'finalizada', resultado: 'completed' }
        : { evento: 'finalizada', resultado: 'completed', duracion_segundos: duracion },
    );
  }

  silenciar(): void {
    /* sin audio */
  }

  destruir(): void {
    this.emisor.limpiar();
    this.llamadaId = null;
  }

  onEstado(cb: (estado: EstadoSoftphone, detalle?: string) => void): () => void {
    return this.emisor.suscribir(cb);
  }
}
