from datetime import date
from decimal import Decimal

import pytest

from app.modulos.importacion import normalizacion as nz


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("1.234.567,89", "1234567.89"),
        ("$ 1.500.000", "1500000.00"),
        ("1500000", "1500000.00"),
        ("1500.5", "1500.50"),
        ("1500,5", "1500.50"),
        ("0", "0.00"),
    ],
)
def test_monto_valido(crudo, esperado):
    assert nz.parsear_monto(crudo) == Decimal(esperado)


@pytest.mark.parametrize("crudo", ["1,234.56", "-5", "abc", "", None, "1.5.5", "9" * 20])
def test_monto_invalido(crudo):
    with pytest.raises(nz.ErrorValor) as exc:
        nz.parsear_monto(crudo)
    assert exc.value.codigo == "MONTO_INVALIDO"


def test_fechas():
    assert nz.parsear_fecha("2026-09-15") == date(2026, 9, 15)
    assert nz.parsear_fecha("15/09/2026") == date(2026, 9, 15)
    for malo in ("31/02/2026", "2026-13-01", "15-09-2026", ""):
        with pytest.raises(nz.ErrorValor):
            nz.parsear_fecha(malo)


def test_documentos():
    assert nz.normalizar_documento("NIT", "900.123.456-7") == "9001234567"
    assert nz.normalizar_documento("CC", "1.020.304.050") == "1020304050"
    assert nz.normalizar_documento("CE", " ab-12 ".replace("-", "")) == "AB12"
    for tipo, malo in (("CC", "12a45"), ("CC", "123"), ("PA", "a"), ("CC", "")):
        with pytest.raises(nz.ErrorValor) as exc:
            nz.normalizar_documento(tipo, malo)
        assert exc.value.codigo == "DOCUMENTO_INVALIDO"


def test_tipo_documento():
    assert nz.normalizar_tipo_documento(" cc ") == "CC"
    with pytest.raises(nz.ErrorValor):
        nz.normalizar_tipo_documento("XX")


def test_cabeceras():
    assert nz.normalizar_cabecera("Teléfono 1") == "telefono_1"
    assert nz.normalizar_cabecera("  Número-Documento ") == "numero_documento"


def test_enteros_y_email():
    assert nz.parsear_entero_no_negativo("45") == 45
    for malo in ("-1", "4.5", "x", ""):
        with pytest.raises(nz.ErrorValor):
            nz.parsear_entero_no_negativo(malo)
    assert nz.validar_email("Ana@Empresa.CO") == "ana@empresa.co"
    with pytest.raises(nz.ErrorValor):
        nz.validar_email("no-es-email")
