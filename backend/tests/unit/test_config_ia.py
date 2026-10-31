"""Configuración del agente IA (B40, fase-2c.md §8)."""

import logging

import pytest
from pydantic import ValidationError

from app.config import Settings


def cfg(**kw):
    return Settings(_env_file=None, entorno="test", **kw)


def test_test_arranca_sin_clave():
    s = cfg()
    assert (
        s.ia_proveedor == "falso"
        and s.ia_habilitada
        and s.anthropic_api_key.get_secret_value() == ""
    )
    assert s.modelos_ia_permitidos == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert s.ia_modelo_por_defecto == "claude-opus-5-5" and s.ia_esfuerzo_por_defecto == "medium"


def test_anthropic_sin_clave_falla_fuera_de_test():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(
            _env_file=None, entorno="desarrollo", jwt_secreto="x" * 32, ia_proveedor="anthropic"
        )
    assert cfg(ia_proveedor="anthropic")  # en test solo se usa con el marcador ia_real


def test_produccion_con_proveedor_falso_y_habilitada_falla():
    base = dict(_env_file=None, entorno="produccion", jwt_secreto="x" * 32,
                twilio_auth_token="real", public_base_url="https://app.empresa.co")  # fmt: skip
    with pytest.raises(ValidationError, match="IA_PROVEEDOR=falso"):
        Settings(**base)
    assert Settings(**base, ia_habilitada=False)
    assert Settings(**base, ia_proveedor="anthropic", anthropic_api_key="sk-ant-x")


def test_clave_no_aparece_en_repr():
    s = cfg(anthropic_api_key="sk-ant-secreta-123")
    assert "secreta" not in repr(s) and "secreta" not in str(s)
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-secreta-123"


@pytest.mark.parametrize(
    "cambio",
    [
        {"ia_modelo_por_defecto": "otro"},
        {"ia_modelos_permitidos": "claude-opus-5-5,modelo-sin-precio"},
        {"ia_max_tokens": 10},
        {"ia_max_iteraciones": 0},
        {"ia_turno_max_segundos": 300},
        {"ia_debounce_segundos": 20, "ia_debounce_max_segundos": 10},
        {"ia_aviso_asistente": " "},
        {"ia_alerta_presupuesto_pct": 100},
        {"ia_precios_json": "no es json"},
    ],
)
def test_validaciones(cambio):
    with pytest.raises(ValidationError):
        cfg(**cambio)


def test_precios_sobrescribibles():
    s = cfg(ia_precios_json='{"claude-opus-5-5": {"entrada": 9.0}}')
    assert s.precios_ia["claude-opus-5-5"]["entrada"] == 9.0
    assert s.precios_ia["claude-opus-5-5"]["salida"] == 20.0


def test_loggers_del_sdk_en_warning():
    from app import logging_seguro

    logging.getLogger("anthropic").setLevel(logging.DEBUG)
    logging_seguro.instalar()
    for nombre in ("anthropic", "httpx2", "httpx"):
        assert logging.getLogger(nombre).level == logging.WARNING
