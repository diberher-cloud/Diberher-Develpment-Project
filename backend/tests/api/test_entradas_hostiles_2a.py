"""Entradas límite y hostiles en los endpoints de 2A: nunca debe haber un 5xx."""

import pytest
from escenario import cab
from test_tipificaciones import K, llamada_terminada, tipificar
from voz import contexto


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


@pytest.mark.parametrize(
    "monto",
    [
        pytest.param("1" + "0" * 30, id="31-digitos"),  # excede la precisión del contexto decimal
        pytest.param("1E+100", id="1E+100"),
        pytest.param("9" * 5000, id="5000-nueves"),
        pytest.param("1e-400", id="1e-400"),
        "NaN",
        "Infinity",
        "-0",
        "0",
        "1_000",
        "１２３",  # dígitos de ancho completo
        "٣٠٠٠",  # dígitos arábigo-índicos
        "1,000.00",
        "",
        "   ",
        "0x10",
        "100.001",
        "1000.00\x00",
    ],
)
def test_monto_de_promesa_hostil_da_422_nunca_500(client, ctx, db, monto):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "promesa_pago", promesa={"monto": monto, "fecha_pago": "2026-10-30"}
    )
    assert r.status_code in (201, 422), (monto[:20], r.status_code, r.text[:200])
    if monto.strip() in ("1000.00\x00",):
        assert r.status_code == 422


@pytest.mark.parametrize(
    "valor",
    [pytest.param("1" + "0" * 30, id="31-digitos"), pytest.param("1E+100", id="1E+100"),
     pytest.param("9" * 5000, id="5000-nueves"), "NaN", "-1", "0", "abc", "", "12.345"],
)  # fmt: skip
def test_valor_de_venta_hostil_da_422_nunca_500(client, esc, crear_usuario, reloj, db, valor):
    c = contexto(esc, crear_usuario, reloj, tipo="venta")
    lid = llamada_terminada(client, c, db)
    r = tipificar(client, c, lid, "venta", venta={"producto": "Seguro", "valor": valor})
    assert r.status_code == 422, (valor[:20], r.status_code, r.text[:200])


@pytest.mark.parametrize(
    "cuando",
    [
        "0001-01-01T00:00:00Z",
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-05:00",
        "9999-12-31T23:59:59Z",
        "2026-10-26T10:00:00+99:00",
        "2026-10-26T10:00:00",
        "no es fecha",
        "2026-10-26",
        "",
    ],
)
def test_volver_a_llamar_en_extremo_da_422_nunca_500(client, ctx, db, cuando):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "volver_a_llamar", contacto_directo=True, volver_a_llamar_en=cuando
    )
    assert r.status_code == 422, (cuando, r.status_code, r.text[:200])


@pytest.mark.parametrize("fecha", ["0001-01-01", "9999-12-31", "2026-02-30", "26-10-2026", "x"])
def test_fecha_de_pago_extrema_da_422_nunca_500(client, ctx, db, fecha):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "promesa_pago", promesa={"monto": "100.00", "fecha_pago": fecha}
    )
    assert r.status_code == 422, (fecha, r.status_code, r.text[:200])


def test_observacion_limites(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "rechazo", observacion="a" * 1001)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == "observacion"
    # 1000 caracteres más espacios laterales: tras recortar caben.
    r = tipificar(client, ctx, lid, "rechazo", observacion="  " + "á" * 1000 + "  ")
    assert r.status_code == 201, r.text
    assert len(r.json()["observacion"]) == 1000


def test_observacion_solo_espacios_es_null(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "rechazo", observacion="   \n\t ")
    assert r.status_code == 201 and r.json()["observacion"] is None


@pytest.mark.parametrize("lid", [0, -1, 2**31, 2**63, "abc", None, 1.5, True])
def test_llamada_id_invalido_422(client, ctx, lid):
    r = client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": "rechazo"},
        headers=cab(ctx.agente),
    )
    assert r.status_code in (404, 422), (lid, r.status_code)


@pytest.mark.parametrize(
    "ruta",
    ["/registros/0/tomar", "/registros/-3/tomar", f"/registros/{2**31}/tomar",
     f"/registros/{2**70}/tomar", "/registros/abc/tomar", "/registros/1.5/tomar"],
)  # fmt: skip
def test_ids_de_ruta_invalidos(client, ctx, ruta):
    r = client.post(f"{K}{ruta}", headers=cab(ctx.agente))
    assert r.status_code in (404, 422), (ruta, r.status_code, r.text[:200])


@pytest.mark.parametrize(
    "params",
    ["campana_id=0", f"campana_id={2**31}", "campana_id=abc", "page=0", "page=99999999999",
     "page_size=0", "page_size=100000", "page=-1"],
)  # fmt: skip
def test_parametros_de_lista_invalidos(client, ctx, params):
    r = client.get(f"{K}/registros?{params}", headers=cab(ctx.agente))
    assert r.status_code < 500, (params, r.status_code, r.text[:200])
