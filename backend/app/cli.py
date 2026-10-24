"""CLI: `python -m app.cli crear-admin` y `python -m app.cli generar-festivos`."""

import argparse
import getpass
import sys

from email_validator import EmailNotValidError, validate_email
from pydantic import ValidationError

from app import db as bd
from app import registro_modelos  # noqa: F401
from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.cumplimiento.festivos import ANIO_MAX, ANIO_MIN
from app.modulos.cumplimiento.servicio import generar_festivos
from app.modulos.usuarios import servicio as usuarios
from app.modulos.usuarios.esquemas import UsuarioCrear


def crear_admin(args: argparse.Namespace) -> int:
    try:
        email = validate_email(args.email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        print(f"Email inválido: {exc}", file=sys.stderr)
        return 2
    password = get_settings().admin_password
    if not password:
        password = getpass.getpass("Contraseña del administrador (10-128 caracteres): ")
    try:
        datos = UsuarioCrear(
            email=email, nombre=args.nombre, rol="administrador", password=password
        )
    except ValidationError as exc:
        for err in exc.errors():
            print(f"{'.'.join(map(str, err['loc']))}: {err['msg']}", file=sys.stderr)
        return 2
    with bd.SessionLocal() as db:
        try:
            usuario = usuarios.crear(db, datos, actor_id=None, origen="cli")
        except ErrorApp as exc:
            print(exc.mensaje, file=sys.stderr)
            return 1
        print(f"Administrador creado (id={usuario.id}).")
    return 0


def generar(args: argparse.Namespace) -> int:
    if not (ANIO_MIN <= args.desde <= args.hasta <= ANIO_MAX):
        print(f"Rango inválido: use {ANIO_MIN} <= desde <= hasta <= {ANIO_MAX}.", file=sys.stderr)
        return 2
    with bd.SessionLocal() as db:
        for anio in range(args.desde, args.hasta + 1):
            try:
                r = generar_festivos(db, anio, usuario_id=None)
            except ErrorApp as exc:
                print(exc.mensaje, file=sys.stderr)
                return 1
            print(f"{anio}: creados={r.creados} existentes={r.existentes}")
    return 0


LIMITE_LLAMADA_SEGUNDOS = 3600  # timeLimit del <Dial>


def liberar_gestion(args: argparse.Namespace) -> int:
    """Soporte: tipifica como `sistema` una llamada que su agente no tipificó."""
    from app.modulos.consola.tipificacion import tipificar_sistema
    from app.modulos.telefonia import servicio as telefonia
    from app.modulos.telefonia.modelos import Llamada
    from app.reloj import ahora

    with bd.SessionLocal() as db:
        llamada = db.get(Llamada, args.llamada_id)
        if llamada is None:
            print("Llamada no encontrada.", file=sys.stderr)
            return 1
        try:
            if llamada.estado in ("iniciando", "sonando", "en_curso"):
                # Llamada atascada (webhooks perdidos). Se valida todo antes de tocar nada.
                if args.resultado not in ("no_contesta", "numero_errado"):
                    print(
                        "La llamada sigue activa: al forzar su cierre (fallida) solo se admiten "
                        "los resultados no_contesta y numero_errado.",
                        file=sys.stderr,
                    )
                    return 1
                ahora_ = ahora()
                antiguedad = (ahora_ - llamada.iniciada_en).total_seconds()
                if antiguedad <= LIMITE_LLAMADA_SEGUNDOS:
                    print(
                        f"La llamada sigue activa y se inició hace {int(antiguedad)} s; solo se "
                        f"puede forzar su cierre pasados {LIMITE_LLAMADA_SEGUNDOS} s (timeLimit).",
                        file=sys.stderr,
                    )
                    return 1
                # Sin commit intermedio: cierre y tipificación en una sola transacción.
                telefonia.finalizar(db, llamada, "failed", None, ahora_)
            tipificar_sistema(db, args.llamada_id, args.resultado, ahora())
            # La auditoría `consola.tipificacion_sistema` la escribe el propio servicio.
        except ErrorApp as exc:
            db.rollback()
            print(f"{exc.codigo}: {exc.mensaje}", file=sys.stderr)
            return 1
    print(f"Llamada {args.llamada_id} tipificada como '{args.resultado}' (sistema).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_admin = sub.add_parser("crear-admin", help="Crea un usuario administrador")
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--nombre", required=True)
    p_admin.set_defaults(func=crear_admin)
    p_fest = sub.add_parser("generar-festivos", help="Genera festivos calculados (idempotente)")
    p_fest.add_argument("--desde", type=int, required=True)
    p_fest.add_argument("--hasta", type=int, required=True)
    p_fest.set_defaults(func=generar)
    p_lib = sub.add_parser(
        "liberar-gestion", help="Tipifica como sistema una llamada que el agente no tipificó"
    )
    p_lib.add_argument("--llamada-id", type=int, required=True)
    p_lib.add_argument(
        "--resultado", required=True, choices=["no_contesta", "numero_errado", "contactado"]
    )
    p_lib.set_defaults(func=liberar_gestion)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
