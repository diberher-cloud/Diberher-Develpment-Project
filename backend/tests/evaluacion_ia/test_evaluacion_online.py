"""Evaluación online con la API real de Anthropic: se OMITE sin ANTHROPIC_API_KEY.

cd backend && IA_PROVEEDOR=anthropic ANTHROPIC_API_KEY=... pytest -m ia_real
"""

import os

import pytest

pytestmark = pytest.mark.ia_real
HAY_CLAVE = (
    bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("IA_PROVEEDOR") == "anthropic"
)


@pytest.mark.skipif(not HAY_CLAVE, reason="requiere IA_PROVEEDOR=anthropic y ANTHROPIC_API_KEY")
def test_online_casos_estrictos():
    from app.config import get_settings
    from app.modulos.agente_ia.evaluacion import casos, harness, informe
    from app.modulos.agente_ia.llm_anthropic import ClienteAnthropic

    s = get_settings()
    cliente = ClienteAnthropic(api_key=s.anthropic_api_key.get_secret_value())
    resultados = harness.ejecutar_casos(
        casos.cargar_casos("opt_out_*") + casos.cargar_casos("humano_*"),
        "online", cliente, modelo="claude-haiku-5-5", esfuerzo="low",
    )  # fmt: skip
    assert informe.aprobada(resultados, "online"), [r.fallos for r in resultados]
