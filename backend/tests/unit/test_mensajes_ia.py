"""Reconstrucción pura de la petición (fase-2c.md §4.3; casos M)."""

from datetime import UTC, datetime

import pytest

from app.modulos.agente_ia import mensajes as m
from app.modulos.agente_ia.canal import EntradaCliente
from app.modulos.agente_ia.mensajes import FilaHistorial as F

AHORA = datetime(2026, 10, 23, 15, 15, tzinfo=UTC)


def u(n, texto="hola"):
    return F(n, "user", "entradas_cliente", [{"type": "text", "text": texto}])


def s(n, texto="ctx"):
    return F(n, "system", "contexto", {"texto": texto})


def a(n, *bloques):
    return F(n, "assistant", "respuesta", list(bloques) or [{"type": "text", "text": "r"}])


def tr(n, tid="t1"):
    return F(n, "user", "resultados_herramientas",
             [{"type": "tool_result", "tool_use_id": tid, "content": "{}"}])  # fmt: skip


USO = {"type": "tool_use", "id": "t1", "name": "x", "input": {}}


def roles(msgs):
    return [x["role"] for x in msgs]


def test_m1_cola_abierta_se_fusiona():
    msgs = m.construir_peticion([u(1), s(2), u(3, "otra")], "claude-opus-5-5", frozenset())
    assert roles(msgs) == ["user", "system"] and len(msgs[0]["content"]) == 2


def test_m2_tool_result_primero():
    filas = [u(1), s(2), a(3, USO), u(4, "texto"), tr(5)]
    msgs = m.construir_peticion(filas, "claude-opus-5-5", frozenset())
    assert [b["type"] for b in msgs[3]["content"]] == ["tool_result", "text"]


def test_m3_nunca_termina_en_assistant_ni_empieza_por_system():
    with pytest.raises(m.PeticionInvalida):
        m.construir_peticion([u(1), a(2)], "x", frozenset())
    assert m.construir_peticion([s(1), u(2)], "x", frozenset())[0]["role"] == "user"
    with pytest.raises(m.PeticionInvalida):
        m.construir_peticion([u(1), a(2, USO), u(3)], "x", frozenset())


def test_m4_prefijo_estable_entre_peticiones():
    filas = [u(1), s(2), a(3)]
    k = m.construir_peticion([*filas, u(4, "dos")], "x", frozenset())
    k1 = m.construir_peticion([*filas, u(4, "dos"), a(5), u(6, "tres")], "x", frozenset())
    assert k1[: len(k)] == k


def test_segmento_abortado_es_igual_abierto_o_cerrado():
    abierto = m.construir_peticion([u(1), s(2), u(3, "b")], "x", frozenset())
    cerrado = m.construir_peticion([u(1), s(2), u(3, "b"), a(4), u(5)], "x", frozenset())
    assert cerrado[:2] == abierto


def test_m8_modelo_sin_system_intermedio():
    msgs = m.construir_peticion([u(1), s(2, "aviso")], "haiku", frozenset({"haiku"}))
    assert roles(msgs) == ["user"]
    assert msgs[0]["content"][-1]["text"] == "<aviso_servidor>aviso</aviso_servidor>"


def test_formatear_entradas_y_contexto():
    es = [
        EntradaCliente(101, AHORA, "texto", "Hola <b> & chao", None, None),
        EntradaCliente(102, AHORA, "boton", "Asesor", None, "ASESOR"),
        EntradaCliente(103, AHORA, "media", None, "audio", None),
        EntradaCliente(104, AHORA, "media", "comprobante", "imagen", None),
    ]
    b = [x["text"] for x in m.formatear_entradas(es, "America/Bogota", omitidas=3)]
    assert b[0] == '<mensajes_omitidos cantidad="3"/>'
    assert b[1] == (
        '<mensaje_cliente id="101" fecha_local="2026-10-23T10:15">Hola &lt;b&gt; &amp; chao'
        "</mensaje_cliente>"
    )
    assert (
        b[3]
        == '<mensaje_cliente id="103" fecha_local="2026-10-23T10:15" tipo="audio" soportado="false"/>'
    )
    assert "Pie: comprobante" in b[4]
    ctx = m.contexto_sistema(
        tipo_campana="cobranza", tratamiento="usted", nombre_pila="María", ahora=AHORA,
        zona="America/Bogota", iniciada_por="cliente", identidad_verificada=False, instrucciones=None,
    )  # fmt: skip
    assert "viernes 23/10/2026 10:15 (America/Bogota)" in ctx and "Identidad verificada: no." in ctx
    assert "Instrucciones de la campaña: ninguna." in ctx
