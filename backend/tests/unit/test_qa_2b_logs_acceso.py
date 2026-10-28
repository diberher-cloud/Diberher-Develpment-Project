"""QA 2B: el log de acceso de uvicorn no debe llevar números de teléfono (se loguea la query).

`GET /api/v1/autorizaciones?numero=3109876543` (2B) y `GET /api/v1/exclusiones?q=3109876543` (2A)
aparecen con el número completo en `uvicorn.access`: el filtro solo enmascara `token=`/`ticket=`.
"""

import logging

import pytest

from app.logging_seguro import MascaraCredencialesFilter


def _registro(mensaje: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, mensaje, (), None)


@pytest.mark.parametrize("param", ["numero", "q"])
@pytest.mark.parametrize("valor", ["3109876543", "%2B573109876543", "+573109876543"])
def test_h4_el_filtro_enmascara_numeros_en_la_query(param, valor):
    r = _registro(f'127.0.0.1:1 - "GET /api/v1/autorizaciones?{param}={valor} HTTP/1.1" 200')
    MascaraCredencialesFilter().filter(r)
    assert "3109876543" not in r.getMessage(), r.getMessage()


def test_el_filtro_actual_sigue_enmascarando_credenciales():
    r = _registro('"WebSocket /api/v1/ws?ticket=abc123" [accepted]')
    MascaraCredencialesFilter().filter(r)
    assert "abc123" not in r.getMessage()
