import { useEffect, useRef, useState } from 'react';
import { descargarMedia } from '../../api/endpoints';
import type { ErrorApi } from '../../api/cliente';
import type { MediaMensaje } from '../../api/tipos';
import { comoErrorApi } from '../../utilidades/useCarga';

interface Props {
  conversacionId: number;
  mensajeId: number;
  media: MediaMensaje;
}

const ETIQUETA = { imagen: 'imagen', audio: 'audio', documento: 'documento PDF' } as const;

/**
 * Adjunto entrante. El binario se pide al proxy del servidor con el Bearer (fetch) y se muestra desde un `blob:`
 * URL local; nunca se usa la URL de Twilio. La descarga es a petición (cada vista queda auditada en el servidor) y
 * el `blob:` se revoca al desmontar.
 */
export function AdjuntoMedia({ conversacionId, mensajeId, media }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<ErrorApi | null>(null);
  const urlActual = useRef<string | null>(null);
  const montado = useRef(true);

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      if (urlActual.current) URL.revokeObjectURL(urlActual.current);
      urlActual.current = null;
    };
  }, []);

  if (!media.disponible || media.categoria === 'no_soportado') {
    return <p className="adjunto adjunto-no-soportado">Adjunto no soportado ({media.tipo_contenido})</p>;
  }
  const categoria = media.categoria;

  async function cargar() {
    setError(null);
    setCargando(true);
    try {
      const blob = await descargarMedia(conversacionId, mensajeId, media.indice);
      if (!montado.current) return;
      if (urlActual.current) URL.revokeObjectURL(urlActual.current);
      const nueva = URL.createObjectURL(blob);
      urlActual.current = nueva;
      setUrl(nueva);
    } catch (e) {
      if (montado.current) setError(comoErrorApi(e));
    } finally {
      if (montado.current) setCargando(false);
    }
  }

  const nombre = `Adjunto ${media.indice + 1} del mensaje ${mensajeId}`;
  return (
    <div className="adjunto">
      {url === null && (
        <button type="button" disabled={cargando} onClick={() => void cargar()}>
          {cargando ? 'Descargando…' : `Ver ${ETIQUETA[categoria]}`}
          <span className="solo-lectura"> (adjunto {media.indice + 1} del mensaje {mensajeId})</span>
        </button>
      )}
      {url !== null && categoria === 'imagen' && <img src={url} alt={nombre} className="adjunto-imagen" />}
      {url !== null && categoria === 'audio' && <audio controls src={url} aria-label={nombre} />}
      {url !== null && categoria === 'documento' && (
        <a href={url} download={`documento-${mensajeId}-${media.indice}.pdf`}>
          Descargar documento PDF<span className="solo-lectura"> ({nombre})</span>
        </a>
      )}
      {error && (
        <p role="alert" className="error-campo">
          {error.message}
        </p>
      )}
    </div>
  );
}
