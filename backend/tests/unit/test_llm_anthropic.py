"""Adaptador del SDK (fase-2c.md §4.2; casos L1-L7) sin red: cliente inyectado."""

import logging
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.modulos.agente_ia.llm import ErrorLLM
from app.modulos.agente_ia.llm_anthropic import BETA_FALLBACK, ClienteAnthropic
from app.modulos.agente_ia.llm_falso import ClienteLLMFalso, GuionAgotado


class Bloque:
    def __init__(self, **d):
        self.d = d

    def to_dict(self, mode="json"):
        return dict(self.d)


def respuesta(stop="end_turn", contenido=None, **kw):
    uso = SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=None,
                          cache_read_input_tokens=3)  # fmt: skip
    r = SimpleNamespace(
        id="msg_1", model="claude-sonnet-5-5", stop_reason=stop, usage=uso,
        content=contenido if contenido is not None else [Bloque(type="text", text="hola")],
        stop_details=kw.get("detalles"), _request_id="req_1",
    )  # fmt: skip
    return r


class FalsoSDK:
    def __init__(self, resultado=None, error=None):
        self.llamadas = []
        self.resultado, self.error = resultado, error
        self.messages = SimpleNamespace(create=lambda **k: self._crear("std", k))
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **k: self._crear("beta", k))
        )

    def _crear(self, via, kw):
        self.llamadas.append((via, kw))
        if self.error:
            raise self.error
        return self.resultado or respuesta()


def llamar(sdk, **extra):
    base = dict(modelo="claude-opus-5-5", max_tokens=100, esfuerzo="medium", sistema=[{"type": "text"}],
                herramientas=[{"name": "x"}], mensajes=[{"role": "user", "content": "a"}],
                fallback_rechazo=False, cache_ttl="5m")  # fmt: skip
    base.update(extra)
    return ClienteAnthropic(cliente=sdk).crear_mensaje(**base)


def test_l1_parametros_enviados():
    sdk = FalsoSDK()
    llamar(sdk)
    via, kw = sdk.llamadas[0]
    assert via == "std" and kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 100
    assert kw["output_config"] == {"effort": "medium"} and kw["cache_control"] == {
        "type": "ephemeral"
    }
    assert kw["system"] and kw["tools"] and kw["messages"]
    for prohibido in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert prohibido not in kw
    llamar(sdk, cache_ttl="1h")
    assert sdk.llamadas[1][1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_l2_fallback():
    sdk = FalsoSDK()
    llamar(sdk, fallback_rechazo=True)
    via, kw = sdk.llamadas[0]
    assert via == "beta" and kw["betas"] == [BETA_FALLBACK] and kw["fallbacks"] == "default"


def _req():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls, codigo):
    return cls("m", response=httpx2.Response(codigo, request=_req()), body=None)


@pytest.mark.parametrize(
    "exc,codigo,trans",
    [
        (_status(anthropic.RateLimitError, 429), "RATE_LIMIT", True),
        (anthropic.APIConnectionError(request=_req()), "CONEXION", True),
        (anthropic.APITimeoutError(request=_req()), "TIMEOUT", True),
        (_status(anthropic.InternalServerError, 529), "HTTP_529", True),
        (_status(anthropic.BadRequestError, 400), "HTTP_400", False),
        (_status(anthropic.AuthenticationError, 401), "HTTP_401", False),
        (_status(anthropic.PermissionDeniedError, 403), "HTTP_403", False),
        (_status(anthropic.NotFoundError, 404), "HTTP_404", False),
        (_status(anthropic.APIStatusError, 402), "HTTP_402", False),
    ],
)
def test_l3_mapeo_de_excepciones(exc, codigo, trans, caplog):
    with caplog.at_level(logging.DEBUG), pytest.raises(ErrorLLM) as e:
        llamar(FalsoSDK(error=exc))
    assert (e.value.codigo, e.value.transitorio) == (codigo, trans)
    assert "m" != caplog.text.strip() and "https://" not in caplog.text


def test_l4_l5_contenido_y_uso():
    bloques = [Bloque(type="thinking", thinking="", signature="sig"), Bloque(type="raro", x=1)]
    r = llamar(FalsoSDK(resultado=respuesta("tool_use", bloques)))
    assert r.contenido == [{"type": "thinking", "thinking": "", "signature": "sig"},
                           {"type": "raro", "x": 1}]  # fmt: skip
    assert r.uso == {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
                     "cache_read_input_tokens": 3}  # fmt: skip
    assert r.request_id == "req_1" and r.modelo == "claude-sonnet-5-5"
    ref = respuesta("refusal", detalles=SimpleNamespace(category="cyber"))
    assert llamar(FalsoSDK(resultado=ref)).stop_categoria == "cyber"
    assert llamar(FalsoSDK(resultado=respuesta("stop_sequence"))).stop_reason == "otro"


def test_l7_falso_determinista():
    llm = ClienteLLMFalso([{"texto": "a"}, {"herramientas": [{"name": "x", "input": {}}]}])
    kw = dict(modelo="m", max_tokens=1, esfuerzo="low", sistema=[], herramientas=[], mensajes=[],
              fallback_rechazo=False, cache_ttl="5m")  # fmt: skip
    r1, r2 = llm.crear_mensaje(**kw), llm.crear_mensaje(**kw)
    assert r1.id == "msg_falso_1" and r2.contenido[0]["id"] == "toolu_falso_1"
    assert (
        r1.uso["cache_creation_input_tokens"] == 2000 and r2.uso["cache_read_input_tokens"] == 2000
    )
    with pytest.raises(GuionAgotado):
        llm.crear_mensaje(**kw)
