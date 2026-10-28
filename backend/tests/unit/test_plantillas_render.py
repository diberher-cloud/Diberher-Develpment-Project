from app.modulos.whatsapp import plantillas_render as r


def test_variables_de_ordenadas_numericamente_y_sin_repetir():
    assert r.variables_de("{{2}} y {{ 10 }} y {{1}} y {{2}}") == ["1", "2", "10"]
    assert r.variables_de("sin variables") == []


def test_renderizar_tolera_espacios_y_deja_literal_lo_desconocido():
    cuerpo = "Hola {{1}}, de {{ 2 }}. Ref {{9}}"
    assert r.renderizar(cuerpo, {"1": "María", "2": "Acme"}) == "Hola María, de Acme. Ref {{9}}"


def test_campos_son_la_lista_blanca_sin_montos():
    assert r.CAMPOS == ("primer_nombre", "empresa", "agente", "producto")
    assert "saldo_mora" not in r.CAMPOS


def test_limpiar_valor_y_primera_palabra():
    assert r.limpiar_valor("  Tarjeta\n  Oro \t") == "Tarjeta Oro"
    assert r.limpiar_valor(None) == ""
    assert r.primera_palabra("maría josé PÉREZ") == "María"
    assert r.primera_palabra("   ") == ""
