import { useCallback, useEffect, useRef, useState } from 'react';
import { ErrorApi } from '../api/cliente';

export interface EstadoCarga<T> {
  datos: T | null;
  cargando: boolean;
  error: ErrorApi | null;
  recargar: () => void;
}

/** Ejecuta `cargador` al montar y cada vez que cambie (memorícelo con useCallback). */
export function useCarga<T>(cargador: () => Promise<T>): EstadoCarga<T> {
  const [datos, setDatos] = useState<T | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [version, setVersion] = useState(0);
  const ultima = useRef(0);

  useEffect(() => {
    const id = ++ultima.current;
    let cancelado = false;
    setCargando(true);
    setError(null);
    cargador().then(
      (d) => {
        if (cancelado || id !== ultima.current) return;
        setDatos(d);
        setCargando(false);
      },
      (e: unknown) => {
        if (cancelado || id !== ultima.current) return;
        setError(e instanceof ErrorApi ? e : new ErrorApi(0, 'ERROR', 'Ocurrió un error inesperado.'));
        setCargando(false);
      },
    );
    return () => {
      cancelado = true;
    };
  }, [cargador, version]);

  const recargar = useCallback(() => setVersion((v) => v + 1), []);
  return { datos, cargando, error, recargar };
}

/** Convierte cualquier excepción en ErrorApi. */
export function comoErrorApi(e: unknown): ErrorApi {
  return e instanceof ErrorApi ? e : new ErrorApi(0, 'ERROR', 'Ocurrió un error inesperado.');
}
