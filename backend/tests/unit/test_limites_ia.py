"""Límites de negocio (fase-2c.md §4.9; casos U1-U15)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modulos.agente_ia import limites as lim

REGLAS = lim.validar_reglas_cobranza(
    {
        "base_descuento": "saldo_mora",
        "descuento_max_pct": "20.00",
        "descuento_max_pct_por_cuotas": [
            {"max_cuotas": 1, "descuento_max_pct": "20.00"},
            {"max_cuotas": 3, "descuento_max_pct": "10.00"},
            {"max_cuotas": 6, "descuento_max_pct": "0.00"},
        ],
        "monto_minimo_promesa": "100000.00",
        "monto_minimo_cuota": "50000.00",
        "max_cuotas": 6,
        "plazo_max_dias_primer_pago": 14,
        "plazo_max_dias_total": 90,
        "periodicidades": ["quincenal", "mensual"],
    }
)
OB = lim.Obligacion(Decimal("1500000"), Decimal("300000"))
HOY = date(2026, 10, 23)


def sim(monto, n, fecha, per, reglas=REGLAS):
    return lim.simular_acuerdo(OB, reglas, monto, n, date.fromisoformat(fecha), per, HOY)


def codigo(r):
    assert isinstance(r, lim.Rechazo), r
    return r.codigo


def test_u1_u2_pago_unico():
    p = sim("240000", 1, "2026-10-30", "unica")
    assert isinstance(p, lim.Plan) and p.descuento_porcentaje == Decimal("20.00")
    r = sim("239999", 1, "2026-10-30", "unica")
    assert codigo(r) == "DESCUENTO_EXCEDE_LIMITE"
    assert r.limites["monto_minimo_para_cuotas"] == "240000.00"


def test_u3_u4_tres_cuotas():
    p = sim("270000.00", 3, "2026-10-30", "quincenal")
    assert [(c.fecha.isoformat(), c.monto) for c in p.cuotas] == [
        ("2026-10-30", Decimal(90000)),
        ("2026-11-14", Decimal(90000)),
        ("2026-11-29", Decimal(90000)),
    ]
    assert codigo(sim("260000", 3, "2026-10-30", "quincenal")) == "DESCUENTO_EXCEDE_LIMITE"


def test_u5_u6_u7_cuotas_y_plazos():
    assert codigo(sim("300000", 7, "2026-10-30", "quincenal")) == "CUOTAS_EXCEDEN_LIMITE"
    assert codigo(sim("300000", 6, "2026-10-30", "mensual")) == "PLAZO_EXCEDE_LIMITE"
    p = sim("300000", 6, "2026-10-30", "quincenal")
    assert p.cuotas[-1].fecha == date(2027, 1, 13) and p.cuotas[0].monto == Decimal(50000)
    assert codigo(sim("300000", 1, "2026-11-07", "unica")) == "PLAZO_EXCEDE_LIMITE"
    assert codigo(sim("300000", 1, "2026-10-22", "unica")) == "FECHA_INVALIDA"


def test_u8_periodicidad():
    assert codigo(sim("300000", 3, "2026-10-30", "semanal")) == "PERIODICIDAD_NO_PERMITIDA"
    assert codigo(sim("300000", 1, "2026-10-30", "quincenal")) == "PERIODICIDAD_NO_PERMITIDA"
    assert codigo(sim("300000", 3, "2026-10-30", "unica")) == "PERIODICIDAD_NO_PERMITIDA"


def test_u9_u10_saldo_y_cuota_minima():
    assert sim("310000", 1, "2026-10-30", "unica").descuento_porcentaje == 0
    assert codigo(sim("1600000", 1, "2026-10-30", "unica")) == "MONTO_SUPERA_SALDO"
    reglas = REGLAS.model_copy(update={"monto_minimo_cuota": Decimal(100000)})
    assert codigo(sim("300000", 6, "2026-10-30", "quincenal", reglas)) == "CUOTA_INFERIOR_MINIMO"


@pytest.mark.parametrize("monto", ["270000.50", "2.7e5", "-1", "0", " ", "abc"])
def test_u11_monto_invalido(monto):
    assert codigo(sim(monto, 1, "2026-10-30", "unica")) == "MONTO_INVALIDO"


def test_u12_u13_reparto_y_mensual():
    reglas = REGLAS.model_copy(update={"monto_minimo_cuota": Decimal(10000)})
    p = sim("100000", 3, "2026-10-30", "mensual", reglas)
    # descuento 66,67 % > 10 %: se comprueba el reparto con base grande
    assert codigo(p) == "DESCUENTO_EXCEDE_LIMITE"
    ob = lim.Obligacion(Decimal(100000), Decimal(100000))
    p = lim.simular_acuerdo(ob, reglas, "100000", 3, date(2026, 10, 30), "mensual", HOY)
    assert [c.monto for c in p.cuotas] == [Decimal(33333), Decimal(33333), Decimal(33334)]
    assert lim.fechas_de_cuotas(date(2026, 10, 31), 3, "mensual") == [
        date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31)
    ]  # fmt: skip


def test_u14_reglas_invalidas_por_campo():
    base = dict(
        base_descuento="saldo_mora", descuento_max_pct="20", monto_minimo_promesa="1000",
        monto_minimo_cuota="100", max_cuotas=6, plazo_max_dias_primer_pago=30,
        plazo_max_dias_total=10, periodicidades=[],
        descuento_max_pct_por_cuotas=[
            {"max_cuotas": 3, "descuento_max_pct": "10"},
            {"max_cuotas": 2, "descuento_max_pct": "30"},
        ],
    )  # fmt: skip
    with pytest.raises(lim.ErroresReglas) as e:
        lim.validar_reglas_cobranza(base)
    campos = {c for c, _ in e.value.detalles}
    assert {
        "plazo_max_dias_total",
        "periodicidades",
        "descuento_max_pct_por_cuotas.1.max_cuotas",
        "descuento_max_pct_por_cuotas.1.descuento_max_pct",
    } <= campos
    with pytest.raises(lim.ErroresReglas):
        lim.validar_reglas_cobranza({**base, "extra": 1})


def test_u15_cotizar_venta():
    o = lim.OfertaDatos("SEG", "Seguro hogar", None, Decimal("89900"), Decimal(10), 2, None)
    rv = lim.ReglasVenta(max_unidades_por_venta=2)
    c = lim.cotizar_venta(o, rv, 2, "10.00")
    assert c.valor_total == Decimal(161820)
    assert codigo(lim.cotizar_venta(o, rv, 2, "11")) == "DESCUENTO_EXCEDE_LIMITE"
    assert codigo(lim.cotizar_venta(o, rv, 3, "0")) == "UNIDADES_EXCEDEN_LIMITE"
    inactiva = lim.OfertaDatos("SEG", "S", None, Decimal(1), Decimal(0), 1, None, activa=False)
    assert codigo(lim.cotizar_venta(inactiva, rv, 1, "0")) == "OFERTA_NO_DISPONIBLE"
    assert codigo(lim.cotizar_venta(None, rv, 1, "0")) == "OFERTA_NO_DISPONIBLE"


def test_condiciones_y_promesa_humana():
    c = lim.condiciones_negociacion(OB, REGLAS, HOY)
    assert c["monto_minimo_acuerdo"] == "240000.00" and c["fecha_ultima_cuota_max"] == "2027-01-21"
    assert c["fecha_primer_pago_max"] == "2026-11-06" and c["base"] == "300000.00"
    msg = lim.validar_promesa_humana(OB, REGLAS, Decimal(200000))
    assert msg == "Con 1 cuota el monto mínimo es $ 240.000."
    assert lim.validar_promesa_humana(OB, REGLAS, Decimal(240000)) is None
