export function Guion({ guion }: { guion: string | null }) {
  return (
    <section aria-labelledby="t-guion" className="tarjeta">
      <h2 id="t-guion">Guion</h2>
      {guion ? <pre className="guion">{guion}</pre> : <p>La campaña no tiene guion.</p>}
    </section>
  );
}
