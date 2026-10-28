import { useCallback, useEffect, useRef } from 'react';

/**
 * Agrupa solicitudes de recarga: las claves pedidas durante `ms` se acumulan y `alEjecutar` se llama una sola vez al
 * vencer el plazo con el conjunto de claves. Evita una recarga por cada evento de tiempo real.
 */
export function useAgrupador<K extends string>(ms: number, alEjecutar: (claves: Set<K>) => void): (clave: K) => void {
  const ejecutar = useRef(alEjecutar);
  useEffect(() => {
    ejecutar.current = alEjecutar;
  });
  const pendientes = useRef(new Set<K>());
  const temporizador = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(temporizador.current), []);
  return useCallback(
    (clave: K) => {
      pendientes.current.add(clave);
      if (temporizador.current !== undefined) return;
      temporizador.current = setTimeout(() => {
        temporizador.current = undefined;
        const claves = pendientes.current;
        pendientes.current = new Set<K>();
        ejecutar.current(claves);
      }, ms);
    },
    [ms],
  );
}
