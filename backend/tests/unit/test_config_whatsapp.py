"""Configuración de WhatsApp y del worker (B21)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def cfg(**cambios):
    base = {"_env_file": None, "entorno": "test"}
    base.update(cambios)
    return Settings(**base)


def test_entorno_test_arranca_sin_variables_de_whatsapp():
    s = cfg()
    assert s.whatsapp_proveedor == "falso" and s.whatsapp_numero_empresa == "+573000000001"
    assert (s.whatsapp_margen_ventana_segundos, s.whatsapp_media_max_bytes) == (
        60,
        16 * 1024 * 1024,
    )
    assert (s.atencion_max_conversaciones_agente, s.conversacion_inactividad_horas) == (5, 24)
    assert (s.worker_intervalo_segundos, s.worker_lote, s.worker_bloqueo_segundos) == (1, 10, 300)


def test_twilio_sin_credenciales_error_claro():
    with pytest.raises(ValidationError) as e:
        cfg(whatsapp_proveedor="twilio")
    texto = str(e.value)
    assert "WHATSAPP_PROVEEDOR=twilio exige" in texto
    for variable in ("TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SID", "TWILIO_API_KEY_SECRET"):
        assert variable in texto


def test_twilio_con_credenciales_ok_y_exige_https_fuera_de_test():
    credenciales = dict(
        whatsapp_proveedor="twilio",
        twilio_account_sid="ACabc",
        twilio_api_key_sid="SKabc",
        twilio_api_key_secret="sec",
        twilio_auth_token="tok",
    )
    assert cfg(**credenciales, public_base_url="http://localhost:8000")
    with pytest.raises(ValidationError, match="https"):
        cfg(
            **credenciales,
            entorno="desarrollo",
            jwt_secreto="x" * 32,
            public_base_url="http://x.co",
        )


@pytest.mark.parametrize("numero", ["3001234567", "+0123456789", "573001234567", "+57abc", ""])
def test_numero_de_empresa_debe_ser_e164(numero):
    with pytest.raises(ValidationError, match="WHATSAPP_NUMERO_EMPRESA"):
        cfg(whatsapp_numero_empresa=numero)


@pytest.mark.parametrize(
    "cambios",
    [
        {"whatsapp_margen_ventana_segundos": -1},
        {"whatsapp_margen_ventana_segundos": 3601},
        {"whatsapp_media_max_bytes": 1023},
        {"whatsapp_media_max_bytes": 64 * 1024 * 1024 + 1},
        {"conversacion_inactividad_horas": 0},
        {"conversacion_inactividad_horas": 169},
        {"atencion_max_conversaciones_agente": 0},
        {"atencion_max_conversaciones_agente": 51},
        {"worker_intervalo_segundos": 0.05},
        {"worker_intervalo_segundos": 61},
        {"worker_lote": 0},
        {"worker_lote": 101},
        {"worker_bloqueo_segundos": 29},
        {"worker_bloqueo_segundos": 3601},
        {"whatsapp_mensaje_espera": "x" * 1001},
        {"whatsapp_mensaje_opt_out": "x" * 1001},
    ],
)
def test_rangos(cambios):
    with pytest.raises(ValidationError):
        cfg(**cambios)


def test_limites_inclusivos_y_mensajes_vacios_permitidos():
    assert cfg(whatsapp_margen_ventana_segundos=0, whatsapp_media_max_bytes=1024, worker_lote=100)
    assert cfg(
        worker_intervalo_segundos=0.1, worker_bloqueo_segundos=30, whatsapp_mensaje_espera=""
    )
