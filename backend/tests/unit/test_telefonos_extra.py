"""Teléfonos: casos adicionales de ADR-0007 (formatos, 018000, fijos de otras ciudades, fuzz)."""

import random
import string

import pytest

from app.modulos.importacion.telefonos import ErrorTelefono, enmascarar, normalizar_telefono


@pytest.mark.parametrize(
    "crudo",
    ["+573001234567", "(+57) 300 123 4567", "+57-3001234567", "  +57  300 123 4567  ",
     "3001234567 ", "\t3001234567\n", "573001234567.0"],
)  # fmt: skip
def test_formatos_moviles_equivalentes(crudo):
    r = normalizar_telefono(crudo)
    assert (r.numero_e164, r.tipo_linea) == ("+573001234567", "movil")


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("3101234567", "+573101234567"),
        ("3201234567", "+573201234567"),
        ("3501234567", "+573501234567"),
        ("3151112233", "+573151112233"),
    ],
)
def test_prefijos_moviles(crudo, esperado):
    r = normalizar_telefono(crudo)
    assert (r.numero_e164, r.tipo_linea) == (esperado, "movil")


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("6012345678", "+576012345678"),  # Bogotá
        ("6042345678", "+576042345678"),  # Medellín
        ("6022345678", "+576022345678"),  # Cali
        ("6052345678", "+576052345678"),  # Barranquilla
        ("6072345678", "+576072345678"),  # Bucaramanga
        ("6012345678.0", "+576012345678"),  # exportado desde Excel como número
        ("+57 601 234 5678", "+576012345678"),
        ("576012345678", "+576012345678"),
    ],
)
def test_fijos_de_distintas_ciudades(crudo, esperado):
    r = normalizar_telefono(crudo)
    assert (r.numero_e164, r.tipo_linea) == (esperado, "fijo")


@pytest.mark.parametrize(
    "crudo",
    [
        "018000123456",  # línea gratuita nacional (el caso del plan)
        "01 8000 123456",
        "01-8000-123456",
        "18000123456",
        "+57 18000123456",
        "+5718000123456",
    ],
)
def test_018000_se_rechaza_como_tipo_no_permitido(crudo):
    """`phonenumbers` clasifica 01-8000 como TOLL_FREE: se rechaza con TIPO_NO_PERMITIDO."""
    with pytest.raises(ErrorTelefono) as exc:
        normalizar_telefono(crudo)
    assert exc.value.codigo == "TELEFONO_TIPO_NO_PERMITIDO"
    assert exc.value.mensaje  # mensaje legible


@pytest.mark.parametrize("crudo", ["018000", "0180001", "01800012345678", "01 8000 12"])
def test_018000_incompleto_es_invalido(crudo):
    with pytest.raises(ErrorTelefono) as exc:
        normalizar_telefono(crudo)
    assert exc.value.codigo in {"TELEFONO_INVALIDO", "TELEFONO_TIPO_NO_PERMITIDO"}


@pytest.mark.parametrize(
    "crudo",
    ["1234567", "123", "9001234567", "30012345678", "300123456", "0300 123 4567", "+", "-",
     "....", "N/A", "sin telefono", "3001234567891234"],
)  # fmt: skip
def test_invalidos(crudo):
    with pytest.raises(ErrorTelefono) as exc:
        normalizar_telefono(crudo)
    assert exc.value.codigo == "TELEFONO_INVALIDO"


@pytest.mark.parametrize(
    "crudo", ["+1 415 555 2671", "+44 20 7946 0958", "+52 55 1234 5678", "+34 612 345 678"]
)
def test_extranjeros(crudo):
    with pytest.raises(ErrorTelefono) as exc:
        normalizar_telefono(crudo)
    assert exc.value.codigo == "TELEFONO_NO_COLOMBIANO"


def test_idempotente_sobre_la_salida():
    for crudo in ("3001234567", "6012345678", "573109998877"):
        primero = normalizar_telefono(crudo)
        segundo = normalizar_telefono(primero.numero_e164)
        assert segundo == primero


def test_el_resultado_siempre_tiene_forma_e164_colombiana():
    for crudo in ("3001234567", "(601) 234 5678", "+57 300-123-4567"):
        e164 = normalizar_telefono(crudo).numero_e164
        assert e164.startswith("+57") and e164[1:].isdigit() and len(e164) in (13,)


def test_fuzz_nunca_lanza_otra_excepcion():
    """Cualquier texto produce un resultado válido o un ErrorTelefono, jamás otra excepción."""
    rnd = random.Random(1234)
    alfabeto = string.digits * 3 + " +-().x\t,;abc/ñ"
    for _ in range(3000):
        crudo = "".join(rnd.choice(alfabeto) for _ in range(rnd.randint(0, 20)))
        try:
            r = normalizar_telefono(crudo)
        except ErrorTelefono as exc:
            assert exc.codigo in {
                "TELEFONO_REQUERIDO",
                "TELEFONO_INVALIDO",
                "TELEFONO_NO_COLOMBIANO",
                "TELEFONO_TIPO_NO_PERMITIDO",
            }
        else:
            assert r.numero_e164.startswith("+57") and r.tipo_linea in {"movil", "fijo"}


def test_enmascarar_nunca_muestra_mas_de_4_caracteres():
    assert enmascarar("1020304050") == "***4050"
    assert enmascarar("+573001234567") == "***4567"
    assert enmascarar(None) == "***"
    assert enmascarar("12") == "***12"
    assert "1020" not in enmascarar("1020304050")
