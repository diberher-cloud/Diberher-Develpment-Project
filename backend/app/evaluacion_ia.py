"""CLI de la evaluación del agente IA (fase-2c.md §7.4).

    python -m app.evaluacion_ia [--real] [--casos "cobranza_*"] [--modelo M] [--esfuerzo E]
        [--canal chat] [--registrar] [--salida informe.json]

Por defecto usa el cliente de Claude FALSO (determinista, sin red). `--real` exige
`IA_PROVEEDOR=anthropic` y `ANTHROPIC_API_KEY` y llama a la API real (cuesta dinero).
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app import registro_modelos  # noqa: F401
from app.config import get_settings
from app.modulos.agente_ia import configuracion
from app.modulos.agente_ia.evaluacion import casos as casos_mod
from app.modulos.agente_ia.evaluacion import harness, informe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evaluacion_ia")
    parser.add_argument("--real", action="store_true", help="llama a la API real de Anthropic")
    parser.add_argument("--casos", help="patrón fnmatch de ids de caso")
    parser.add_argument("--modelo")
    parser.add_argument("--esfuerzo", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--canal", default="chat", choices=["chat"])
    parser.add_argument("--registrar", action="store_true", help="guarda el resultado en la BD")
    parser.add_argument("--salida", help="ruta del informe JSON")
    args = parser.parse_args(argv)
    settings = get_settings()
    modo = "online" if args.real else "offline"
    cliente = None
    if args.real:
        if (
            settings.ia_proveedor != "anthropic"
            or not settings.anthropic_api_key.get_secret_value()
        ):
            print("--real exige IA_PROVEEDOR=anthropic y ANTHROPIC_API_KEY.", file=sys.stderr)
            return 2
        from app.modulos.agente_ia.llm_anthropic import ClienteAnthropic

        cliente = ClienteAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout_segundos=settings.ia_timeout_segundos,
        )
    casos = casos_mod.cargar_casos(args.casos)
    if not casos:
        print("Ningún caso coincide con el patrón.", file=sys.stderr)
        return 2

    def mostrar(r: informe.ResultadoCaso) -> None:
        print(
            f"{'OK ' if r.aprobado else 'FALLA'} {r.id}" + ("" if r.aprobado else f": {r.fallos}")
        )

    resultados = harness.ejecutar_casos(
        casos, modo, cliente, mostrar, modelo=args.modelo, esfuerzo=args.esfuerzo
    )
    resumen = informe.agregar(resultados, modo)
    aprobada = informe.aprobada(resultados, modo) and args.casos is None
    print(
        f"{resumen['aprobados']}/{resumen['total']} casos aprobados; "
        f"coste {resumen['costo_usd']} USD"
    )
    if args.salida:
        Path(args.salida).write_text(
            json.dumps(
                {
                    "modo": modo,
                    "aprobada": aprobada,
                    "resumen": resumen,
                    "casos": [r.como_dict() for r in resultados],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if args.registrar:
        from app.db import SessionLocal
        from app.modulos.agente_ia.evaluacion import servicio
        from app.modulos.agente_ia.modelos import EvaluacionIA
        from app.modulos.agente_ia.prompts import VERSIONES

        ahora = datetime.now(UTC)
        with SessionLocal() as db:
            version = VERSIONES["chat"][-1]
            e = EvaluacionIA(
                modo=modo,
                canal="chat",
                campana_id=None,
                modelo=args.modelo,
                esfuerzo=args.esfuerzo,
                prompt_version=version,
                huella=configuracion.huella_evaluacion(version),
                patron_casos=args.casos,
                estado="en_curso",
                resumen={},
                casos=[],
                creado_en=ahora,
            )
            db.add(e)
            db.flush()
            servicio.registrar_resultado(db, e, resultados, ahora)
            db.commit()
            print(f"Evaluación registrada con id {e.id}.")
    return 0 if all(r.aprobado for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
