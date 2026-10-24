from datetime import UTC, datetime, timedelta

from app.modulos.consola.efectos import EntradaEfectos, calcular_efectos

AHORA = datetime(2026, 10, 23, 23, 30, tzinfo=UTC)  # vie 18:30 Bogotá


def entrada(resultado, **kw):
    base = {
        "resultado": resultado,
        "ahora": AHORA,
        "intentos": 1,
        "max_intentos": 3,
        "intervalo_reintento_minutos": 60,
    }
    base.update(kw)
    return EntradaEfectos(**base)


def test_no_contesta_reprograma_en_ventana():
    siguiente = datetime(2026, 10, 24, 13, 0, tzinfo=UTC)  # sáb 08:00 Bogotá
    e = calcular_efectos(entrada("no_contesta", proxima_ventana=lambda t: siguiente))
    assert (e.estado, e.intentos, e.proximo_intento_en, e.contacto_directo) == (
        "pendiente",
        2,
        siguiente,
        False,
    )


def test_no_contesta_pasa_la_hora_calculada_a_la_ventana():
    vistos = []
    calcular_efectos(entrada("no_contesta", proxima_ventana=lambda t: vistos.append(t)))
    assert vistos == [AHORA + timedelta(minutes=60)]


def test_no_contesta_agota_intentos():
    e = calcular_efectos(entrada("no_contesta", intentos=2))
    assert (e.estado, e.intentos, e.proximo_intento_en) == ("gestionado", 3, None)


def test_numero_errado_con_y_sin_otros_telefonos():
    con = calcular_efectos(entrada("numero_errado", quedan_telefonos_llamables=True))
    sin = calcular_efectos(entrada("numero_errado", quedan_telefonos_llamables=False))
    assert (con.estado, con.excluir_telefono, con.intentos) == ("pendiente", True, 2)
    assert (sin.estado, sin.excluir_telefono, sin.proximo_intento_en) == ("descartado", True, None)
    assert sin.cierra_registro and not con.cierra_registro


def test_resultados_con_contacto_directo():
    for r in ("contactado", "promesa_pago", "venta", "rechazo"):
        e = calcular_efectos(entrada(r))
        assert (e.estado, e.intentos, e.contacto_directo, e.proximo_intento_en) == (
            "gestionado",
            2,
            True,
            None,
        )
    assert calcular_efectos(entrada("promesa_pago")).crear_promesa
    assert calcular_efectos(entrada("venta")).crear_venta
    assert not calcular_efectos(entrada("rechazo")).crear_promesa


def test_volver_a_llamar():
    cuando = AHORA + timedelta(days=2)
    for directo in (True, False):
        e = calcular_efectos(
            entrada("volver_a_llamar", contacto_directo_pedido=directo, volver_a_llamar_en=cuando)
        )
        assert (e.estado, e.intentos, e.proximo_intento_en, e.contacto_directo) == (
            "pendiente",
            2,
            cuando,
            directo,
        )


def test_numero_errado_con_intentos_agotados_es_gestionado():
    e = calcular_efectos(entrada("numero_errado", intentos=2, quedan_telefonos_llamables=True))
    assert (e.estado, e.intentos, e.excluir_telefono) == ("gestionado", 3, True)
    e = calcular_efectos(entrada("numero_errado", intentos=0, max_intentos=1))
    assert e.estado == "gestionado"
