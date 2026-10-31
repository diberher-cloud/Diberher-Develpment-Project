"""Definiciones del catálogo (fase-2c.md §4.7), prompt de sistema y huella."""

import hashlib
import re

import pytest

from app.modulos.agente_ia.herramientas import definiciones as d
from app.modulos.agente_ia.prompts import VERSIONES, cargar_sistema

PROHIBIDAS = {"cliente_id", "campana_id", "conversacion_id", "telefono", "documento_cliente"}
CLAVES_SCHEMA = {"type", "enum", "format", "description", "properties", "required",
                 "additionalProperties"}  # fmt: skip


def recorrer(esquema, ruta=""):
    assert set(esquema) <= CLAVES_SCHEMA, (ruta, set(esquema) - CLAVES_SCHEMA)
    if esquema.get("type") == "object":
        assert esquema["additionalProperties"] is False
        assert esquema["required"] == list(esquema["properties"])
        for k, v in esquema["properties"].items():
            assert k not in PROHIBIDAS
            recorrer(v, f"{ruta}.{k}")


@pytest.mark.parametrize("tipo", ["cobranza", "venta"])
def test_catalogo_estricto_y_ordenado(tipo):
    cat = d.catalogo("chat", tipo)
    nombres = [t["name"] for t in cat]
    assert nombres == sorted(nombres) and len(nombres) == 10
    for t in cat:
        assert t["strict"] is True and t["input_schema"]["type"] == "object"
        recorrer(t["input_schema"])
    assert ("registrar_venta" in nombres) == (tipo == "venta")
    assert ("registrar_acuerdo_pago" in nombres) == (tipo == "cobranza")


def test_huella_estable_y_distinta_por_tipo():
    assert d.huella("chat", "cobranza", 1) == d.huella("chat", "cobranza", 1)
    assert d.huella("chat", "cobranza", 1) != d.huella("chat", "venta", 1)


def test_prompt_sin_datos_variables():
    texto = cargar_sistema("chat", 1, "Mi Empresa S.A.S.")
    assert "{" not in texto and "Mi Empresa S.A.S." in texto
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{6,}|\d{1,2}/\d{1,2}/\d{4}", texto)
    assert VERSIONES == {"chat": (1,)}


def test_prompt_v1_no_se_edita():
    """Una versión publicada es inmutable: cambiar el texto exige `sistema_chat_v2.md`."""
    crudo = cargar_sistema("chat", 1, "{empresa}")
    assert hashlib.sha256(crudo.encode()).hexdigest() == HUELLA_V1


HUELLA_V1 = "6a7d55f971417ced61fdbff92a9d5dd988401cf39ea6c3fb882ee50b0022e309"
