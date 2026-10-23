export function Cargando({ texto = 'Cargando…' }: { texto?: string }) {
  return (
    <p role="status" className="cargando">
      {texto}
    </p>
  );
}
