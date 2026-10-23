interface Props {
  page: number;
  pageSize: number;
  total: number;
  onCambiar: (page: number) => void;
}

export function Paginador({ page, pageSize, total, onCambiar }: Props) {
  const paginas = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="paginador" aria-label="Paginación">
      <button type="button" disabled={page <= 1} onClick={() => onCambiar(page - 1)}>
        Anterior
      </button>
      <span aria-live="polite">
        Página {page} de {paginas} ({total} registros)
      </span>
      <button type="button" disabled={page >= paginas} onClick={() => onCambiar(page + 1)}>
        Siguiente
      </button>
    </nav>
  );
}
