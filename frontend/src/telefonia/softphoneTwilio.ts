import type { Call, Device } from '@twilio/voice-sdk';
import type { TokenTelefonia } from '../api/tipos';
import { EmisorEstado, type EstadoSoftphone, type Softphone } from './softphone';

/**
 * Softphone con `@twilio/voice-sdk`. El SDK se carga de forma perezosa (import dinámico) para no inflar el
 * bundle inicial.
 */
export class SoftphoneTwilio implements Softphone {
  private emisor = new EmisorEstado();
  private device: Device | null = null;
  private llamada: Call | null = null;
  private destruido = false;

  constructor(
    private readonly tokenInicial: TokenTelefonia,
    private readonly obtenerToken: () => Promise<TokenTelefonia>,
  ) {}

  async iniciar(): Promise<void> {
    this.emisor.emitir('registrando');
    try {
      const { Device: DeviceSdk } = await import('@twilio/voice-sdk');
      if (this.destruido) return;
      const device = new DeviceSdk(this.tokenInicial.token, {
        codecPreferences: ['opus', 'pcmu'] as unknown as Call.Codec[],
        closeProtection: true,
      });
      this.device = device;
      device.on('registered', () => {
        if (this.emisor.estado === 'registrando') this.emisor.emitir('listo');
      });
      device.on('error', (error: { message?: string }) => {
        this.emisor.emitir('error', error?.message ?? 'Error del dispositivo de voz.');
      });
      device.on('tokenWillExpire', () => {
        void this.obtenerToken().then(
          (t) => device.updateToken(t.token),
          () => this.emisor.emitir('error', 'No se pudo renovar el token de telefonía.'),
        );
      });
      await device.register();
      if (this.emisor.estado === 'registrando') this.emisor.emitir('listo');
    } catch (e) {
      this.emisor.emitir('error', e instanceof Error ? e.message : 'No se pudo iniciar el softphone.');
    }
  }

  async llamar(params: { campana_cliente_id: number; telefono_id: number }): Promise<void> {
    if (!this.device) {
      this.emisor.emitir('error', 'El softphone no está listo.');
      return;
    }
    this.emisor.emitir('conectando');
    try {
      // Los parámetros personalizados de Twilio son strings; el número de destino lo resuelve el servidor.
      const call = await this.device.connect({
        params: { campana_cliente_id: String(params.campana_cliente_id), telefono_id: String(params.telefono_id) },
      });
      this.llamada = call;
      call.on('accept', () => this.emisor.emitir('en_curso'));
      const fin = () => {
        this.llamada = null;
        this.emisor.emitir('finalizada');
      };
      call.on('disconnect', fin);
      call.on('cancel', fin);
      call.on('reject', fin);
      call.on('error', (error: { message?: string }) => {
        this.emisor.emitir('error', error?.message ?? 'Error en la llamada.');
      });
    } catch (e) {
      this.llamada = null;
      this.emisor.emitir('error', e instanceof Error ? e.message : 'No se pudo iniciar la llamada.');
    }
  }

  colgar(): void {
    if (this.llamada) this.llamada.disconnect();
    else this.device?.disconnectAll();
  }

  silenciar(activo: boolean): void {
    this.llamada?.mute(activo);
  }

  destruir(): void {
    this.destruido = true;
    this.emisor.limpiar();
    this.llamada = null;
    this.device?.destroy();
    this.device = null;
  }

  onEstado(cb: (estado: EstadoSoftphone, detalle?: string) => void): () => void {
    return this.emisor.suscribir(cb);
  }
}
