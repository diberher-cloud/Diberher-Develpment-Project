import { useEffect, useState } from 'react';

/** Marca de tiempo (ms) que se actualiza cada `intervaloMs`; sirve para contadores en vivo. */
export function useAhora(intervaloMs = 1000, activo = true): number {
  const [ahora, setAhora] = useState(() => Date.now());
  useEffect(() => {
    if (!activo) return;
    setAhora(Date.now());
    const id = setInterval(() => setAhora(Date.now()), intervaloMs);
    return () => clearInterval(id);
  }, [intervaloMs, activo]);
  return ahora;
}
