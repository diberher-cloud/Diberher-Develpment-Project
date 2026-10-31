"""Carga y validación de los casos de evaluación (fase-2c.md §7.1)."""

import fnmatch
import json
from pathlib import Path
from typing import Any

# backend/tests/evaluacion_ia/casos (los casos son datos de prueba sintéticos del repositorio)
DIRECTORIO_CASOS = Path(__file__).resolve().parents[4] / "tests" / "evaluacion_ia" / "casos"

EXPECTATIVAS = frozenset(
    {
        "acuerdo_registrado",
        "venta_registrada",
        "acuerdo",
        "herramientas_llamadas",
        "herramientas_rechazadas",
        "herramientas_no_llamadas",
        "identidad_verificada",
        "sin_montos_antes_de_verificar",
        "derivado",
        "motivo_derivacion",
        "opt_out",
        "conversacion_cerrada",
        "motivo_cierre",
        "resultado_tipificacion",
        "textos_enviados_contienen_alguno",
        "textos_enviados_no_contienen",
        "max_mensajes_ia",
        "guardas_activadas",
        "max_costo_usd",
    }
)
CLAVES_OBLIGATORIAS = (
    "id",
    "version",
    "categoria",
    "canal",
    "campana",
    "cliente",
    "reloj",
    "turnos_cliente",
    "expectativas",
)
CATEGORIAS_ESTRICTAS_ONLINE = ("opt_out", "identidad", "inyeccion", "monto", "humano")


class CasoInvalido(ValueError):
    pass


def reglas_nombradas(directorio: Path | None = None) -> dict[str, Any]:
    ruta = (directorio or DIRECTORIO_CASOS) / "_reglas.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def validar(caso: dict[str, Any], reglas: dict[str, Any]) -> None:
    ident = caso.get("id", "?")
    for k in CLAVES_OBLIGATORIAS:
        if k not in caso:
            raise CasoInvalido(f"{ident}: falta '{k}'.")
    desconocidas = set(caso["expectativas"]) - EXPECTATIVAS
    if desconocidas:
        raise CasoInvalido(f"{ident}: expectativas desconocidas {sorted(desconocidas)}.")
    r = caso["campana"].get("reglas")
    if isinstance(r, str) and r not in reglas:
        raise CasoInvalido(f"{ident}: reglas '{r}' desconocidas.")
    guion = caso.get("guion_llm_falso", [])
    pasos = caso.get("pasos_por_turno")
    if pasos is not None:
        if len(pasos) != len(caso["turnos_cliente"]):
            raise CasoInvalido(f"{ident}: pasos_por_turno no coincide con turnos_cliente.")
        if sum(pasos) != len(guion):
            raise CasoInvalido(f"{ident}: pasos_por_turno suma {sum(pasos)}, guion {len(guion)}.")


def cargar_casos(patron: str | None = None, directorio: Path | None = None) -> list[dict[str, Any]]:
    base = directorio or DIRECTORIO_CASOS
    reglas = reglas_nombradas(base)
    casos = []
    for ruta in sorted(base.glob("*.json")):
        if ruta.name.startswith("_"):
            continue
        caso = json.loads(ruta.read_text(encoding="utf-8"))
        validar(caso, reglas)
        if patron is None or fnmatch.fnmatch(caso["id"], patron):
            casos.append(caso)
    return casos


def resolver_reglas(caso: dict[str, Any], directorio: Path | None = None) -> dict[str, Any]:
    r = caso["campana"]["reglas"]
    return reglas_nombradas(directorio)[r] if isinstance(r, str) else r


def es_categoria_estricta(categoria: str) -> bool:
    return categoria.startswith(CATEGORIAS_ESTRICTAS_ONLINE)
