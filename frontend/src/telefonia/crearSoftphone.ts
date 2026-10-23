import { obtenerTokenTelefonia } from '../api/endpoints';
import type { TokenTelefonia } from '../api/tipos';
import type { Softphone } from './softphone';
import { SoftphoneFalso } from './softphoneFalso';

/** Elige la implementación según `proveedor` del token (`POST /telefonia/token`). */
export async function crearSoftphone(
  obtenerToken: () => Promise<TokenTelefonia> = obtenerTokenTelefonia,
): Promise<Softphone> {
  const token = await obtenerToken();
  if (token.proveedor === 'falso') return new SoftphoneFalso(token);
  const { SoftphoneTwilio } = await import('./softphoneTwilio');
  return new SoftphoneTwilio(token, obtenerToken);
}
