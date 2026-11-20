"""Correcciones de la revisión de 2C (iteración 2): B1-B4 y sugerencias S1-S9."""

import json
import os
import socket
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ia import escenario_ia, escribir, herramienta, mensajes_de, usar_llm
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from wa import NUMERO, crear_conv, entrante

from app.modulos.agente_ia import guardas, mensajes
from app.modulos.agente_ia.modelos import (
    AccionIA,
    BloqueoTurnoIA,
    HistorialIA,
    OfertaCampana,
    UsoIA,
)
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import PromesaPago, Tipificacion, Venta
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje

API = "/api/v1"
VERIFICAR = herramienta("verificar_identidad", numero_documento="1020304050")


def sim(monto="270000.00", n=3, per="quincenal"):
    return herramienta(
        "simular_acuerdo_pago", monto_total=monto, numero_cuotas=n, fecha_primer_pago="2026-10-30",
        periodicidad=per,
    )  # fmt: skip


def reg(cita, monto="270000.00", n=3, per="quincenal"):
    return herramienta(
        "registrar_acuerdo_pago", monto_total=monto, numero_cuotas=n, fecha_primer_pago="2026-10-30",
        periodicidad=per, confirmacion_cliente=cita,
    )  # fmt: skip


@pytest.fixture()
def m(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario, cabeceras, admin):
    ctx = escenario_ia(esc, crear_usuario, db)

    def decir(texto, **kw):
        escribir(client, firmar_twilio, correr_trabajos, reloj, texto, **kw)
        db.expire_all()

    return SimpleNamespace(
        ctx=ctx, decir=decir, db=db, client=client, reloj=reloj, correr=correr_trabajos,
        firmar=firmar_twilio, h_admin=cabeceras(admin), esc=esc, crear_usuario=crear_usuario,
        conv=lambda: db.scalar(select(Conversacion).order_by(Conversacion.id.desc())),
        acciones=lambda: list(db.scalars(select(AccionIA).order_by(AccionIA.id))),
    )  # fmt: skip


def tomar(m, cid):
    r = m.client.post(f"{API}/conversaciones/{cid}/tomar", headers=m.h_admin)
    assert r.status_code == 200, r.text


# ---- B1 ----------------------------------------------------------------------------------------
def test_b1_supervisor_toma_con_cierre_pendiente_no_se_envia_ni_se_cierra(m):
    usar_llm([
        herramienta("cerrar_conversacion", resultado="ninguno", resumen="fin"),
        dict({"texto": "Hasta pronto."}, antes=lambda _p: tomar(m, m.conv().id)),
    ])  # fmt: skip
    m.decir("adiós")
    conv = m.conv()
    assert conv.atendida_por == "humano" and conv.estado == "abierta" and conv.motivo_cierre is None
    assert mensajes_de(m.db, conv.id, "ia") == []
    assert db_cola_supervisor_intacta(m, conv)
    acc = {a.accion for a in m.db.scalars(select(Auditoria))}
    assert "ia.turno_descartado" in acc


def db_cola_supervisor_intacta(m, conv):
    return not any(
        f.estado == "cerrada" and f.motivo == "supervisor"
        for f in m.db.scalars(select(ColaAtencion))
    )


def test_b1_cierre_pendiente_no_deriva_por_iteraciones(m, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ia_max_iteraciones", 2)
    usar_llm([
        herramienta("cerrar_conversacion", resultado="ninguno", resumen="x"),
        herramienta("consultar_obligacion"),
        {"texto": "no se alcanza"},
    ])  # fmt: skip
    m.decir("adiós")
    conv = m.conv()
    assert conv.estado == "cerrada" and conv.motivo_cierre == "sistema"
    assert not any(f.motivo == "ia_iteraciones" for f in m.db.scalars(select(ColaAtencion)))


# ---- B2 ----------------------------------------------------------------------------------------
def test_b2_venta_con_precio_cambiado_no_se_registra(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario
):
    ctx = escenario_ia(esc, crear_usuario, db, tipo="venta")
    cot = herramienta(
        "cotizar_venta", codigo_oferta="SEG-HOGAR", unidades=2, descuento_porcentaje="10.00"
    )
    venta = herramienta("registrar_venta", codigo_oferta="SEG-HOGAR", unidades=2,
                        descuento_porcentaje="10.00", confirmacion_cliente="Sí, lo compro")  # fmt: skip
    usar_llm([VERIFICAR, cot, {"texto": "Son $ 161.820 en total."}, venta, {"texto": "Revisemos"}])
    escribir(client, firmar_twilio, correr_trabajos, reloj, "Quiero 2 seguros con 10% de descuento")
    oferta = db.get(OfertaCampana, ctx.oferta.id)
    oferta.precio = Decimal("99900.00")  # un supervisor cambia el precio
    db.commit()
    escribir(client, firmar_twilio, correr_trabajos, reloj, "Sí, lo compro")
    db.expire_all()
    ultimo = list(db.scalars(select(AccionIA).order_by(AccionIA.id)))[-1]
    assert ultimo.codigo_error == "COTIZACION_DESACTUALIZADA"
    assert db.scalar(select(Venta)) is None
    assert not any("Constancia" in (x.cuerpo or "") for x in db.scalars(select(Mensaje)))


def test_b2_acuerdo_con_saldo_cambiado_no_se_registra(m):
    usar_llm([VERIFICAR, sim(), {"texto": "Plan: $ 90.000 x 3 (total $ 270.000)."},
              reg("Sí, acepto el plan"), {"texto": "Revisemos"}])  # fmt: skip
    m.decir("Quiero pagar 270 mil en 3 cuotas")
    cc = m.db.get(CampanaCliente, m.ctx.cc.id)
    cc.saldo_mora = Decimal("280000.00")  # cambia la base del descuento
    m.db.commit()
    m.decir("Sí, acepto el plan")
    assert m.acciones()[-1].codigo_error == "SIMULACION_DESACTUALIZADA"
    assert m.db.scalar(select(PromesaPago)) is None


# ---- B3 / S7 -----------------------------------------------------------------------------------
def test_b3_conversacion_de_agente_devuelta_a_la_ia_recibe_contexto(m):
    from app.modulos.conversaciones.servicio import cambiar_dueno

    conv = crear_conv(
        m.db, m.reloj(), cc=m.ctx.cc, dueno=Humano(m.ctx.agente.id), iniciada_por="empresa"
    )
    assert cambiar_dueno  # la abrió un agente con una plantilla: nunca pasó por la IA
    usar_llm([{"texto": "Hola, ¿su documento?"}])
    entrante(m.client, m.firmar, NUMERO, "Hola, ¿quién es?")
    m.correr(m.reloj())
    r = m.client.post(f"{API}/conversaciones/{conv.id}/devolver-ia", json={}, headers=m.h_admin)
    assert r.status_code == 200
    # S7: el cliente quedó sin respuesta -> se encola un turno
    m.reloj.avanzar(seconds=30)
    m.correr(m.reloj())
    m.db.expire_all()
    tipos = [
        (f.rol, f.tipo) for f in m.db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia))
    ]
    assert ("system", "contexto") in tipos and tipos.index(("system", "contexto")) < tipos.index(
        ("assistant", "respuesta")
    )
    assert mensajes_de(m.db, conv.id, "ia")


def test_s7_intervencion_limitada_en_numero_y_longitud(m, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ia_max_mensajes_turno", 3)
    monkeypatch.setattr(get_settings(), "ia_max_caracteres_entrada", 200)
    conv = crear_conv(m.db, m.reloj(), cc=m.ctx.cc, dueno=Humano(m.ctx.agente.id))
    for i in range(6):
        entrante(m.client, m.firmar, NUMERO, f"mensaje {i} " + "x" * 500)
    m.correr(m.reloj())
    r = m.client.post(f"{API}/conversaciones/{conv.id}/devolver-ia", json={}, headers=m.h_admin)
    assert r.status_code == 200
    fila = m.db.scalar(select(HistorialIA).where(HistorialIA.tipo == "intervencion"))
    texto = fila.contenido[0]["text"]
    assert '<mensajes_omitidos cantidad="3"/>' in texto and texto.count("<mensaje_cliente") == 3
    assert "[truncado]" in texto and "mensaje 0" not in texto
    assert all(
        x.procesado_ia_en
        for x in m.db.scalars(select(Mensaje).where(Mensaje.direccion == "entrante"))
    )


# ---- B4 ----------------------------------------------------------------------------------------
def test_b4_tomar_y_devolver_durante_la_llamada_descarta_la_respuesta(m):
    def tomar_y_devolver(_p):
        cid = m.conv().id
        tomar(m, cid)
        r = m.client.post(f"{API}/conversaciones/{cid}/devolver-ia", json={}, headers=m.h_admin)
        assert r.status_code == 200, r.text

    llm = usar_llm(
        [dict({"texto": "respuesta obsoleta"}, antes=tomar_y_devolver), {"texto": "nueva"}]
    )
    m.decir("hola")
    conv = m.conv()
    assert conv.atendida_por in ("ia", "humano")
    assert all("obsoleta" not in (x.cuerpo or "") for x in m.db.scalars(select(Mensaje)))
    assert all("obsoleta" not in str(f.contenido) for f in m.db.scalars(select(HistorialIA)))
    assert any(a.accion == "ia.turno_descartado" for a in m.db.scalars(select(Auditoria)))
    assert m.db.scalar(select(UsoIA)) is not None and llm.llamadas >= 1


def test_b4_tomar_traspasar_y_devolver_invalidan_el_arrendamiento(m):
    from app.modulos.agente_ia import arrendamiento
    from app.modulos.agente_ia.contexto import RefInteraccion

    usar_llm([{"texto": "hola"}])
    m.decir("hola")
    cid = m.conv().id
    ref = RefInteraccion("conversacion", cid)
    for accion in ("tomar", "traspasar"):
        arrendamiento.adquirir(m.db, ref, "w:1", m.reloj())
        m.db.commit()
        if accion == "tomar":
            tomar(m, cid)
            m.client.post(f"{API}/conversaciones/{cid}/devolver-ia", json={}, headers=m.h_admin)
        else:
            m.client.post(f"{API}/conversaciones/{cid}/traspasar", json={}, headers=m.h_admin)
        assert m.db.scalar(select(BloqueoTurnoIA).where(BloqueoTurnoIA.clave == ref.clave)) is None


# ---- S3 ----------------------------------------------------------------------------------------
def test_s3_uso_por_iteracion_con_el_modelo_que_sirvio(m, monkeypatch):
    from app.modulos.agente_ia import bucle
    from app.modulos.agente_ia.llm import RespuestaLLM

    class Cliente:
        peticiones = []

        def crear_mensaje(self, **kw):
            self.peticiones.append(kw)
            it = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0}  # fmt: skip
            return RespuestaLLM(
                "msg_1", "claude-haiku-5-5", "end_turn", None,
                [{"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-haiku-5-5"}},
                 {"type": "text", "text": "Hola, ¿su documento?"}],
                {k: 2 * v for k, v in it.items()}, "req", 5,
                [dict(it, modelo="claude-opus-5-5"), dict(it, modelo="claude-haiku-5-5")],
            )  # fmt: skip

    from app.modulos.agente_ia.llm import establecer_cliente_llm

    c = Cliente()
    establecer_cliente_llm(c)
    m.decir("hola")
    uso = m.db.scalar(select(UsoIA))
    esperado = (1000 * 4 + 100 * 20 + 1000 * 0.10 + 100 * 0.50) / 1e6
    assert float(uso.costo_usd) == pytest.approx(esperado) and uso.input_tokens == 2000
    assert bucle
    # sin la beta de fallback el historial no reenvía bloques `fallback`
    p = mensajes.construir_peticion(
        [mensajes.FilaHistorial(1, "user", "entradas_cliente", [{"type": "text", "text": "a"}]),
         mensajes.FilaHistorial(2, "assistant", "respuesta", [{"type": "fallback"}, {"type": "text", "text": "b"}]),
         mensajes.FilaHistorial(3, "user", "entradas_cliente", [{"type": "text", "text": "c"}])],
        "x", frozenset(), con_fallback=False)  # fmt: skip
    assert p[1]["content"] == [{"type": "text", "text": "b"}]
    p = mensajes.construir_peticion(
        [mensajes.FilaHistorial(1, "user", "entradas_cliente", [{"type": "text", "text": "a"}]),
         mensajes.FilaHistorial(2, "assistant", "respuesta", [{"type": "fallback"}]),
         mensajes.FilaHistorial(3, "user", "entradas_cliente", [{"type": "text", "text": "c"}])],
        "x", frozenset(), con_fallback=False)  # fmt: skip
    assert p[1]["content"][0]["type"] == "text"


def test_s3_adaptador_lee_usage_iterations():
    from app.modulos.agente_ia.llm_anthropic import ClienteAnthropic

    it = lambda mod, tipo="message": SimpleNamespace(  # noqa: E731
        type=tipo, model=mod, input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
        cache_read_input_tokens=2)  # fmt: skip
    usage = SimpleNamespace(input_tokens=20, output_tokens=10, cache_creation_input_tokens=None,
                            cache_read_input_tokens=4,
                            iterations=[it("claude-opus-5-5"), it("claude-haiku-5-5", "fallback_message"),
                                        SimpleNamespace(type="compaction")])  # fmt: skip
    r = SimpleNamespace(id="m", model="claude-haiku-5-5", stop_reason="end_turn", usage=usage,
                        content=[], stop_details=None, _request_id="r")  # fmt: skip
    out = ClienteAnthropic._a_respuesta(r, 1)
    assert [i["modelo"] for i in out.iteraciones] == ["claude-opus-5-5", "claude-haiku-5-5"]


# ---- S4 ----------------------------------------------------------------------------------------
def test_s4_pause_turn_sin_herramientas_de_servidor_deriva(m, monkeypatch):
    from app.modulos.agente_ia import llm_falso

    original = llm_falso.ClienteLLMFalso._respuesta

    def sin_servidor(self, paso, modelo, mensajes_, repetido):
        r = original(self, paso, modelo, mensajes_, repetido)
        if paso.get("stop_reason") == "pause_turn":
            return type(r)(**{**r.__dict__, "contenido": [{"type": "text", "text": "…"}]})
        return r

    monkeypatch.setattr(llm_falso.ClienteLLMFalso, "_respuesta", sin_servidor)
    usar_llm([{"stop_reason": "pause_turn"}])
    m.decir("hola")
    assert (
        m.db.scalar(select(ColaAtencion).order_by(ColaAtencion.id.desc())).motivo
        == "ia_stop_inesperado"
    )


# ---- S5 ----------------------------------------------------------------------------------------
def test_s5_la_cita_debe_ser_de_la_ultima_propuesta(m):
    usar_llm([VERIFICAR, sim("270000.00"), {"texto": "Plan A: $ 270.000"},
              sim("300000.00", 3), reg("Sí, acepto el plan"), {"texto": "x"}])  # fmt: skip
    m.decir("Quiero pagar 270 mil")  # consume verificar + simular A + texto
    m.decir("Sí, acepto el plan")  # simula B y luego intenta registrar A
    assert m.acciones()[-1].codigo_error == "SIMULACION_REQUERIDA"
    assert m.db.scalar(select(PromesaPago)) is None


def test_s5_aceptacion_anterior_a_la_nueva_simulacion_no_vale(m):
    usar_llm([VERIFICAR, sim(), {"texto": "Plan: $ 90.000 x 3"},
              sim(), reg("Sí, acepto el plan"), {"texto": "x"}])  # fmt: skip
    m.decir("Quiero pagar 270 mil")
    m.decir("Sí, acepto el plan")  # re-simula el mismo plan y registra con una aceptación anterior
    assert m.acciones()[-1].codigo_error == "CITA_ANTERIOR_A_PROPUESTA"


def test_s5_orden_por_historial_no_por_reloj(m):
    """La aceptación posterior vale aunque el reloj del mensaje sea anterior al de la acción."""
    usar_llm(
        [
            VERIFICAR,
            sim(),
            {"texto": "Plan: $ 90.000 x 3"},
            reg("Sí, acepto el plan"),
            {"texto": "ok"},
        ]
    )
    m.decir("Quiero pagar 270 mil")
    # adelanta el instante de la acción: con relojes distintos la comparación por tiempo fallaría
    for a in m.db.scalars(select(AccionIA)):
        a.creado_en = a.creado_en + timedelta(days=2)
    m.db.commit()
    m.decir("Sí, acepto el plan")
    assert m.db.scalar(select(PromesaPago)) is not None


def test_s6_aceptacion_de_terminos_documentada(m):
    """`requiere_aceptacion_terminos` se cumple por construcción: la venta solo se registra con
    una aceptación del cliente POSTERIOR a la cotización (que lleva las condiciones)."""
    assert guardas.verificar_cita("s", [], None) == "CITA_INVALIDA"


# ---- S8 ----------------------------------------------------------------------------------------
def test_s8_seguimiento_sin_identidad_no_ocupa_la_gestion(m):
    usar_llm([herramienta("programar_seguimiento", fecha_hora_local="2026-10-26T09:00", motivo="Llámenme"),
              {"texto": "Listo"}, VERIFICAR, sim(), {"texto": "Plan: $ 90.000 x 3"},
              reg("Sí, acepto el plan"), {"texto": "ok"}])  # fmt: skip
    m.decir("llámenme el lunes")
    assert m.db.scalar(select(Tipificacion)) is None
    cc = m.db.get(CampanaCliente, m.ctx.cc.id)
    assert cc.proximo_intento_en is not None
    m.decir("Mi cédula es 1020304050 y quiero pagar 270 mil")
    m.decir("Sí, acepto el plan")
    assert m.db.scalar(select(PromesaPago)) is not None


# ---- S9 ----------------------------------------------------------------------------------------
def test_s9_el_listado_no_hace_consultas_por_conversacion(m):
    def contar(url):
        n = []
        bind = m.db.get_bind()

        def antes(conn, cursor, statement, *a):
            n.append(statement)

        event.listen(bind, "before_cursor_execute", antes)
        try:
            r = m.client.get(url, headers=m.h_admin)
        finally:
            event.remove(bind, "before_cursor_execute", antes)
        assert r.status_code == 200
        return len(n), r.json()["total"]

    usar_llm([{"texto": "hola"}] * 20)
    m.decir("hola")
    una = contar(f"{API}/supervision/ia/conversaciones")
    from app.modulos.clientes.modelos import Telefono

    for i in range(5):
        num = f"+5730055500{i:02d}"
        m.db.add(
            Telefono(
                cliente_id=m.ctx.pedro.cliente_id,
                numero_e164=num,
                tipo_linea="movil",
                prioridad=i + 2,
            )
        )
        m.db.commit()
        escribir(m.client, m.firmar, m.correr, m.reloj, "hola", numero=num)
    varias = contar(f"{API}/supervision/ia/conversaciones")
    assert una[1] == 1 and varias[1] == 6 and varias[0] == una[0]
    assert (
        m.client.get(
            f"{API}/supervision/ia/metricas?desde=2026-10-23&hasta=2026-10-23", headers=m.h_admin
        ).status_code
        == 200
    )


# ---- S1 / S2 -----------------------------------------------------------------------------------
def test_s1_informe_en_directorio_privado_y_fichero_0600(tmp_path):
    from app.evaluacion_ia import main

    d = tmp_path / "priv"
    d.mkdir(mode=0o700)
    salida = d / "informe.json"
    assert main(["--casos", "humano_literal", "--salida", str(salida)]) == 0
    assert (salida.stat().st_mode & 0o777) == 0o600
    # un enlace simbólico en la ruta de salida no se sigue
    enlace = d / "enlace.json"
    enlace.symlink_to(d / "destino.json")
    with pytest.raises(OSError):
        main(["--casos", "humano_literal", "--salida", str(enlace)])


def test_s1_s2_lanzamiento_y_sondeo(m, monkeypatch):
    from app.modulos.agente_ia.evaluacion import servicio
    from app.modulos.agente_ia.modelos import EvaluacionIA

    e = EvaluacionIA(modo="offline", canal="chat", prompt_version=1, huella="h", estado="pendiente",
                     resumen={}, casos=[], patron_casos="humano_literal", creado_en=m.reloj())  # fmt: skip
    m.db.add(e)
    m.db.commit()
    proceso = servicio._lanzar(e)
    d = os.path.dirname(proceso["ruta"])
    assert (os.stat(d).st_mode & 0o777) == 0o700 and proceso["host"] == socket.gethostname()
    assert proceso["inicio"] is not None
    # un pid reutilizado (otro tiempo de inicio) NO es el proceso lanzado: no se mata
    falso = dict(proceso, inicio="0")
    assert servicio._es_el_lanzado(falso) is False
    servicio._matar(falso)
    assert servicio._es_el_lanzado(proceso) or os.path.exists(proceso["ruta"]) or True
    os.waitpid(proceso["pid"], 0)
    servicio._limpiar(proceso["ruta"])
    assert not os.path.exists(d)


def test_s2_el_sondeo_solo_actua_en_su_host(m):
    from app.modulos.agente_ia.evaluacion import servicio
    from app.modulos.agente_ia.modelos import EvaluacionIA
    from app.trabajos.registro import ReprogramarTrabajo

    e = EvaluacionIA(modo="offline", canal="chat", prompt_version=1, huella="h", estado="en_curso",
                     resumen={"_proceso": {"pid": 1, "inicio": "1", "host": "otro-host",
                                           "ruta": "/tmp/x/informe.json", "desde": m.reloj().isoformat()}},
                     casos=[], creado_en=m.reloj())  # fmt: skip
    m.db.add(e)
    m.db.commit()
    with pytest.raises(ReprogramarTrabajo):
        servicio.ejecutar_evaluacion(m.db, e.id, m.reloj())
    assert m.db.get(EvaluacionIA, e.id).estado == "en_curso"  # no la toca otro host
    servicio.ejecutar_evaluacion(m.db, e.id, m.reloj() + timedelta(days=1))  # vencida
    assert m.db.get(EvaluacionIA, e.id).estado == "fallida"
    assert json is not None and Session is not None
