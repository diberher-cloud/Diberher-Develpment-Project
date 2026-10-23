import pytest
from pydantic import ValidationError

from app.config import Settings


def test_secreto_corto_falla_fuera_de_test():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, entorno="produccion", jwt_secreto="corto")


def test_secreto_largo_ok():
    assert Settings(_env_file=None, entorno="produccion", jwt_secreto="x" * 32)


def test_entorno_test_permite_sin_secreto():
    assert Settings(_env_file=None, entorno="test", jwt_secreto="").jwt_secreto
