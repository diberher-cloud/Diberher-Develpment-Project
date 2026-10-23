from datetime import date
from decimal import Decimal

from app.modulos.consola.guion import formatear_monto, renderizar_guion

CTX = {
    "nombre": "María Pérez",
    "primer_nombre": "María",
    "saldo_total": Decimal("1500000.00"),
    "saldo_mora": Decimal("250000.50"),
    "dias_mora": 45,
    "fecha_vencimiento": date(2026, 9, 15),
    "producto": None,
    "empresa": "Mi Empresa S.A.S.",
    "agente": "Pedro Agente",
    "datos": {"segmento": "A"},
}


def test_montos():
    assert formatear_monto(Decimal("1500000.00")) == "$ 1.500.000"
    assert formatear_monto(Decimal("250000.50")) == "$ 250.000,50"
    assert formatear_monto(Decimal("0")) == "$ 0"
    assert formatear_monto(None) == ""


def test_render_completo():
    plantilla = (
        "Buenos días, {{nombre}}. Le habla {{agente}} de {{empresa}}, debe {{saldo_mora}} de "
        "{{saldo_total}}, {{dias_mora}} días, vence {{fecha_vencimiento}}. Seg {{datos.segmento}}."
    )
    assert renderizar_guion(plantilla, CTX) == (
        "Buenos días, María Pérez. Le habla Pedro Agente de Mi Empresa S.A.S., "
        "debe $ 250.000,50 de $ 1.500.000, 45 días, vence 15/09/2026. Seg A."
    )


def test_espacios_nulos_y_desconocidas():
    assert renderizar_guion("[{{ primer_nombre }}]", CTX) == "[María]"
    assert renderizar_guion("[{{producto}}]", CTX) == "[]"
    assert renderizar_guion("[{{inexistente}}] [{{datos.nada}}] [{{datos}}]", CTX) == (
        "[{{inexistente}}] [{{datos.nada}}] [{{datos}}]"
    )
    assert renderizar_guion(None, CTX) is None
    assert renderizar_guion("sin variables", CTX) == "sin variables"
