import pytest

from app.modulos.importacion.telefonos import ErrorTelefono, enmascarar, normalizar_telefono


@pytest.mark.parametrize(
    "crudo",
    ["3001234567", "300 123 4567", "+57 300-123-4567", "573001234567", "3001234567.0"],
)
def test_movil(crudo):
    r = normalizar_telefono(crudo)
    assert (r.numero_e164, r.tipo_linea) == ("+573001234567", "movil")


@pytest.mark.parametrize("crudo", ["6012345678", "(601) 234 5678"])
def test_fijo(crudo):
    r = normalizar_telefono(crudo)
    assert (r.numero_e164, r.tipo_linea) == ("+576012345678", "fijo")


@pytest.mark.parametrize(
    ("crudo", "codigo"),
    [
        ("", "TELEFONO_REQUERIDO"),
        (None, "TELEFONO_REQUERIDO"),
        ("   ", "TELEFONO_REQUERIDO"),
        ("2345678", "TELEFONO_INVALIDO"),
        ("12345", "TELEFONO_INVALIDO"),
        ("abc", "TELEFONO_INVALIDO"),
        ("+1 415 555 2671", "TELEFONO_NO_COLOMBIANO"),
        # phonenumbers reconoce 01-8000 como línea gratuita (TOLL_FREE) -> tipo no permitido.
        ("018000123456", "TELEFONO_TIPO_NO_PERMITIDO"),
    ],
)
def test_errores(crudo, codigo):
    with pytest.raises(ErrorTelefono) as exc:
        normalizar_telefono(crudo)
    assert exc.value.codigo == codigo


def test_enmascarar():
    assert enmascarar("3001234567") == "***4567"
    assert enmascarar("") == "***"
