import pytest
from pydantic import ValidationError

from app.config import TOKEN_TWILIO_EJEMPLO, Settings


def test_secreto_corto_falla_fuera_de_test():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, entorno="produccion", jwt_secreto="corto")


def test_secreto_largo_ok():
    assert Settings(
        _env_file=None,
        entorno="produccion",
        jwt_secreto="x" * 32,
        ia_habilitada=False,
        twilio_auth_token="token-real-de-produccion",
        public_base_url="https://app.empresa.co",
    )


def test_entorno_test_permite_sin_secreto():
    assert Settings(_env_file=None, entorno="test", jwt_secreto="").jwt_secreto


def _twilio(**cambios):
    base = {
        "_env_file": None,
        "entorno": "desarrollo",
        "jwt_secreto": "x" * 32,
        "telefonia_proveedor": "twilio",
        "twilio_account_sid": "ACabc",
        "twilio_auth_token": "tok",
        "twilio_api_key_sid": "SKabc",
        "twilio_api_key_secret": "sec",
        "twilio_twiml_app_sid": "APabc",
        "twilio_numero_saliente": "+576015550000",
        "public_base_url": "https://app.empresa.co",
    }
    base.update(cambios)
    return Settings(**base)


def test_entorno_test_arranca_sin_variables_de_twilio():
    s = Settings(_env_file=None, entorno="test")
    assert s.telefonia_proveedor == "falso" and s.twilio_account_sid == ""


def test_proveedor_twilio_sin_credenciales_falla_con_mensaje_claro():
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None, entorno="test", telefonia_proveedor="twilio")
    msg = str(e.value)
    assert (
        "TWILIO_ACCOUNT_SID" in msg
        and "TWILIO_API_KEY_SECRET" in msg
        and "TWILIO_TWIML_APP_SID" in msg
    )


def test_proveedor_twilio_completo_ok_y_validaciones():
    assert _twilio().telefonia_proveedor == "twilio"
    with pytest.raises(ValidationError):
        _twilio(twilio_numero_saliente="6015550000")
    with pytest.raises(ValidationError):
        _twilio(public_base_url="http://app.empresa.co")  # twilio exige https (salvo test)
    assert _twilio(entorno="test", public_base_url="http://localhost:8000")


def test_public_base_url_con_barra_final_se_rechaza():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, entorno="test", public_base_url="https://app.empresa.co/")


def test_produccion_exige_token_distinto_del_ejemplo_y_https():
    base = {
        "_env_file": None,
        "entorno": "produccion",
        "jwt_secreto": "x" * 32,
        "ia_habilitada": False,
    }
    with pytest.raises(ValidationError):
        Settings(
            **base, twilio_auth_token=TOKEN_TWILIO_EJEMPLO, public_base_url="https://app.empresa.co"
        )
    with pytest.raises(ValidationError):
        Settings(**base, twilio_auth_token="real", public_base_url="http://app.empresa.co")
    assert Settings(**base, twilio_auth_token="real", public_base_url="https://app.empresa.co")


def test_defaults_de_consola():
    s = Settings(_env_file=None, entorno="test")
    assert (s.consola_reserva_minutos, s.consola_desconexion_segundos, s.promesa_max_dias) == (
        15,
        60,
        60,
    )
    assert s.importacion_max_bytes_descomprimido == 104857600 and s.bus_eventos == "auto"
