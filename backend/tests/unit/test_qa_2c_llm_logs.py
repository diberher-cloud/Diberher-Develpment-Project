"""QA 2C L6: el adaptador del SDK nunca registra mensajes, prompt ni texto de excepciones."""

import logging

import anthropic
import httpx2
import pytest
from test_llm_anthropic import FalsoSDK, llamar, respuesta

from app.modulos.agente_ia.llm import ErrorLLM

SECRETO = "Mi cédula es 1020304050 y debo 300000 pesos"


def _mensajes():
    return [{"role": "user", "content": [{"type": "text", "text": SECRETO}]}]


def test_l6_sin_texto_en_logs_en_exito(caplog):
    with caplog.at_level(logging.DEBUG):
        llamar(
            FalsoSDK(), mensajes=_mensajes(), sistema=[{"type": "text", "text": "PROMPT-SECRETO"}]
        )
    assert SECRETO not in caplog.text and "PROMPT-SECRETO" not in caplog.text
    assert "1020304050" not in caplog.text


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_l6_sin_texto_en_logs_en_error_aunque_la_excepcion_lo_incluya(status, caplog):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(status, request=req, json={"error": {"message": SECRETO}})
    exc = anthropic.APIStatusError(SECRETO, response=resp, body={"message": SECRETO})
    with caplog.at_level(logging.DEBUG), pytest.raises(ErrorLLM):
        llamar(FalsoSDK(error=exc), mensajes=_mensajes())
    assert SECRETO not in caplog.text and "1020304050" not in caplog.text
    assert "api.anthropic.com" not in caplog.text


def test_l6_excepcion_ajena_al_sdk_se_propaga_sin_ser_tragada():
    with pytest.raises(ZeroDivisionError):
        llamar(FalsoSDK(error=ZeroDivisionError("x")))


def test_l1_nunca_termina_en_assistant_ni_envia_prefill():
    sdk = FalsoSDK(resultado=respuesta())
    llamar(sdk, mensajes=_mensajes())
    enviados = sdk.llamadas[0][1]["messages"]
    assert enviados[-1]["role"] == "user"
