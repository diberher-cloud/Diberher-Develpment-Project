"""Herramientas del agente con validación en servidor (fase-2c.md §4.8; casos H)."""

import json

import pytest
from ia import escenario_ia, escribir, herramienta, mensajes_de, usar_llm
from sqlalchemy import select

from app.modulos.agente_ia.modelos import AccionIA, PromesaCuota
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal

VERIFICAR = herramienta("verificar_identidad", numero_documento="1020304050")


def sim(monto="270000.00", n=3, fecha="2026-10-30", per="quincenal"):
    return herramienta(
        "simular_acuerdo_pago", monto_total=monto, numero_cuotas=n, fecha_primer_pago=fecha,
        periodicidad=per,
    )  # fmt: skip


def reg(cita, monto="270000.00", n=3, fecha="2026-10-30", per="quincenal"):
    return herramienta(
        "registrar_acuerdo_pago", monto_total=monto, numero_cuotas=n, fecha_primer_pago=fecha,
        periodicidad=per, confirmacion_cliente=cita,
    )  # fmt: skip


class Ctx:
    def __init__(self, client, firmar, correr, reloj, db):
        self.client, self.firmar, self.correr, self.reloj, self.db = (
            client,
            firmar,
            correr,
            reloj,
            db,
        )

    def decir(self, texto):
        escribir(self.client, self.firmar, self.correr, self.reloj, texto)
        self.db.expire_all()

    def conv(self):
        return self.db.scalar(select(Conversacion).order_by(Conversacion.id.desc()))

    def acciones(self):
        return list(self.db.scalars(select(AccionIA).order_by(AccionIA.id)))


@pytest.fixture()
def c(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario):
    escenario_ia(esc, crear_usuario, db)
    return Ctx(client, firmar_twilio, correr_trabajos, reloj, db)


def test_h1_h2_identidad(c):
    usar_llm([herramienta("verificar_identidad", numero_documento="CC 1.020.304.050"),
              {"texto": "Gracias."}])  # fmt: skip
    c.decir("mi cédula")
    assert c.conv().identidad_verificada
    a = c.acciones()[0]
    assert a.entrada == {"numero_documento": "***4050"} and a.efecto == "identidad"
    assert any(x.accion == "ia.identidad" for x in c.db.scalars(select(Auditoria)))


def test_h3_h4_bloqueo_y_sin_verificar(c):
    mal = lambda d: herramienta("verificar_identidad", numero_documento=d)  # noqa: E731
    usar_llm([herramienta("consultar_obligacion"), {"texto": "Primero verifique."},
              mal("1"), {"texto": "no"}, mal("2"), {"texto": "no"}, mal("3"), {"texto": "Adiós"},
              ])  # fmt: skip
    c.decir("hola")
    assert c.acciones()[0].codigo_error == "IDENTIDAD_NO_VERIFICADA"
    assert "saldo" not in json.dumps(c.acciones()[0].resultado)
    for d in ("a", "b", "c"):
        c.decir(d)
    codigos = [a.codigo_error for a in c.acciones()]
    assert codigos[-1] == "IDENTIDAD_BLOQUEADA" and c.conv().atendida_por == "sin_asignar"
    from app.modulos.conversaciones.modelos import ColaAtencion

    cola = c.db.scalar(select(ColaAtencion).order_by(ColaAtencion.id.desc()))
    assert cola.motivo == "identidad_bloqueada" and cola.prioridad == 1


def test_h5_obligacion_literal(c):
    usar_llm([VERIFICAR, herramienta("consultar_obligacion"), {"texto": "ok"}])
    c.decir("hola")
    r = c.acciones()[1].resultado
    assert r["obligacion"] == {
        "numero_mascara": "***-001", "producto": None, "saldo_total": "1500000.00",
        "saldo_mora": "300000.00", "dias_mora": 45, "fecha_vencimiento": "2026-09-15",
    }  # fmt: skip
    assert r["acuerdo_vigente"] is None and r["fecha_hoy"] == "2026-10-23"
    assert r["condiciones"]["monto_minimo_acuerdo"] == "240000.00"
    texto = json.dumps(r)
    assert "1020304050" not in texto and "3001234567" not in texto


def acuerdo_completo(c, cita="Sí, acepto el plan"):
    usar_llm([VERIFICAR, sim(), {"texto": "Plan: 3 cuotas quincenales de $ 90.000, total $ 270.000."},
              reg(cita), {"texto": "Registrado."}])  # fmt: skip
    c.decir("Quiero pagar 270 mil en 3 cuotas")
    c.decir(cita)


def test_h9_registro_correcto_con_constancia(c):
    acuerdo_completo(c)
    t = c.db.scalar(select(Tipificacion))
    assert (t.resultado, t.origen, t.canal, t.usuario_id) == (
        "promesa_pago",
        "agente_ia",
        "whatsapp_mensaje",
        None,
    )
    assert t.conversacion_id == c.conv().id
    p = c.db.scalar(select(PromesaPago))
    assert (p.numero_cuotas, str(p.descuento_porcentaje), p.periodicidad, p.reglas_version) == (
        3,
        "10.00",
        "quincenal",
        1,
    )
    assert len(list(c.db.scalars(select(PromesaCuota)))) == 3
    cc = c.db.scalar(select(CampanaCliente).where(CampanaCliente.id == c.conv().campana_cliente_id))
    assert cc.estado == "gestionado"
    constancia = [
        m.cuerpo for m in mensajes_de(c.db, c.conv().id, "sistema") if "Constancia" in m.cuerpo
    ][0]
    assert constancia == (
        "*Constancia de su acuerdo de pago con Mi Empresa S.A.S.*\n"
        "Total: $ 270.000 en 3 cuotas quincenales.\n"
        "1) 30/10/2026: $ 90.000\n2) 14/11/2026: $ 90.000\n3) 29/11/2026: $ 90.000\n"
        f"Referencia: AP-{p.id}. Si algo no coincide con lo que acordó, responda a este mensaje."
    )
    acc = {a.accion for a in c.db.scalars(select(Auditoria))}
    assert {"ia.acuerdo_registrado", "tipificacion.crear"} <= acc
    intento_directo = c.db.get(
        __import__("app.modulos.cumplimiento.modelos", fromlist=["x"]).IntentoContacto,
        c.conv().intento_contacto_id,
    )
    assert intento_directo.contacto_directo and intento_directo.resultado == "promesa_pago"


def test_h6_h7_h8_requisitos_previos(c):
    usar_llm([VERIFICAR, reg("Sí acepto"), sim(), {"texto": "x $ 90.000"},
              reg("Sí acepto", monto="270000.00", n=2), {"texto": "y"},
              reg("no dije eso"), {"texto": "z"}])  # fmt: skip
    c.decir("hola")
    assert c.acciones()[1].codigo_error == "SIMULACION_REQUERIDA"
    c.decir("Sí acepto")
    assert c.acciones()[-1].codigo_error == "SIMULACION_REQUERIDA"  # valores distintos
    c.decir("otra cosa")
    assert c.acciones()[-1].codigo_error == "CITA_NO_ENCONTRADA"
    assert c.db.scalar(select(Tipificacion)) is None


def test_h10_h11_gestion_y_promesa_vigente(c):
    acuerdo_completo(c)
    # una gestión por conversación
    paso = reg("x")
    paso["herramientas"][0]["id"] = "toolu_nuevo"  # los ids del falso se reinician por cliente
    llm = usar_llm([paso, {"texto": "z"}])
    # la conversación quedó abierta (el modelo no cerró): otra herramienta de gestión
    c.decir("otra cosa")
    assert llm.llamadas == 2
    assert c.acciones()[-1].codigo_error == "GESTION_YA_REGISTRADA"


def test_h12_idempotencia_por_tool_use_id(c):
    from app.modulos.agente_ia import arrendamiento
    from app.modulos.agente_ia.canal_chat import CanalChat
    from app.modulos.agente_ia.contexto import RefInteraccion, cargar_contexto
    from app.modulos.agente_ia.herramientas.ejecutores import EstadoTurno, ejecutar_herramienta

    usar_llm([VERIFICAR, {"texto": "ok"}])
    c.decir("hola")
    conv = c.conv()
    ref = RefInteraccion("conversacion", conv.id)
    ctx = cargar_contexto(c.db, ref)
    sesion = lambda: c.db.get_bind() and __import__("sqlalchemy.orm", fromlist=["x"]).Session(
        bind=c.db.get_bind(), expire_on_commit=False
    )  # noqa: E731
    with sesion() as s:
        arrendamiento.adquirir(s, ref, "w", c.reloj())
        s.commit()
    uso = {
        "type": "tool_use",
        "id": "toolu_x",
        "name": "consultar_historial_gestiones",
        "input": {},
    }
    r1 = ejecutar_herramienta(sesion, CanalChat(), ctx, uso, EstadoTurno(), c.reloj, "w")
    r2 = ejecutar_herramienta(sesion, CanalChat(), ctx, uso, EstadoTurno(), c.reloj, "w")
    assert r1.resultado == r2.resultado and r1.accion_id == r2.accion_id
    assert len([a for a in c.acciones() if a.tool_use_id == "toolu_x"]) == 1


def test_h14_reglas_endurecidas(c):
    usar_llm(
        [
            VERIFICAR,
            sim("270000.00"),
            {"texto": "Plan: $ 270.000"},
            reg("Sí acepto"),
            {"texto": "no"},
        ]
    )
    c.decir("hola")
    c.cfg = c.db.get(
        __import__("app.modulos.agente_ia.modelos", fromlist=["x"]).ConfiguracionIACampana,
        c.conv().campana_id,
    )
    c.cfg.reglas = {
        **c.cfg.reglas,
        "descuento_max_pct_por_cuotas": [{"max_cuotas": 6, "descuento_max_pct": "0.00"}],
    }
    c.db.commit()
    c.decir("Sí acepto")
    assert c.acciones()[-1].codigo_error == "DESCUENTO_EXCEDE_LIMITE"
    assert c.db.scalar(select(Tipificacion)) is None


def test_h16_h23_no_disponible_y_entrada_invalida(c):
    usar_llm([VERIFICAR,
              herramienta("registrar_venta", codigo_oferta="X", unidades=1, descuento_porcentaje="0", confirmacion_cliente="si"),
              {"herramientas": [{"name": "consultar_historial_gestiones", "input": {"cliente_id": 3}}]},
              herramienta("simular_acuerdo_pago", monto_total="1", numero_cuotas="tres", fecha_primer_pago="2026-10-30", periodicidad="unica"),
              {"texto": "ok"}])  # fmt: skip
    c.decir("hola")
    cods = [a.codigo_error for a in c.acciones()]
    assert cods[1:4] == ["HERRAMIENTA_NO_DISPONIBLE", "ENTRADA_INVALIDA", "ENTRADA_INVALIDA"]
    assert "cliente_id" in c.acciones()[2].resultado["campos"][0]


def test_h17_seguimiento(c):
    usar_llm([VERIFICAR, herramienta("programar_seguimiento", fecha_hora_local="2026-10-25T10:00", motivo="x"),
              herramienta("programar_seguimiento", fecha_hora_local="2026-10-26T09:00", motivo="Llamar el lunes"),
              {"texto": "Listo"}])  # fmt: skip
    c.decir("llámenme el lunes")
    a = c.acciones()
    assert (
        a[1].codigo_error == "FUERA_DE_FRANJA"
        and a[1].resultado["limites"]["proxima_ventana"] == "2026-10-26T07:00"
    )
    t = c.db.scalar(select(Tipificacion))
    assert t.resultado == "volver_a_llamar" and t.observacion == "Llamar el lunes"
    cc = c.db.get(CampanaCliente, t.campana_cliente_id)
    assert cc.proximo_intento_en.isoformat().startswith("2026-10-26T14:00")


def test_h18_autorizacion(c):
    usar_llm(
        [
            herramienta("registrar_autorizacion_whatsapp", cita_cliente="acepto que me escriban"),
            {"texto": "ok"},
        ]
    )
    c.decir("Sí, acepto que me escriban")
    a = c.db.scalar(select(AutorizacionCanal))
    assert (a.origen, a.finalidad, a.registrada_por) == ("agente_ia", "cobranza", None)
    assert a.evidencia.startswith(f"Conversación {c.conv().id}, mensaje ")


def test_h19_opt_out_sin_texto_del_modelo(c):
    usar_llm(
        [herramienta("registrar_opt_out", alcance="whatsapp", cita_cliente="no me escriban más")]
    )
    c.decir("no me escriban más por favor gracias señor")
    e = c.db.scalar(select(Exclusion))
    assert (e.origen, e.canal, e.creado_por) == ("agente_ia", "whatsapp", None)
    conv = c.conv()
    assert conv.estado == "cerrada" and conv.motivo_cierre == "opt_out"
    assert mensajes_de(c.db, conv.id, "ia") == []
    assert any("Hemos registrado" in m.cuerpo for m in mensajes_de(c.db, conv.id, "sistema"))


def test_h20_derivar_y_despedida(c):
    usar_llm([herramienta("derivar_a_humano", motivo="queja", resumen="r" * 600),
              herramienta("consultar_historial_gestiones"), ])  # fmt: skip
    usar_llm([{"herramientas": [
        {"name": "derivar_a_humano", "input": {"motivo": "queja", "resumen": "r" * 600}},
        {"name": "consultar_historial_gestiones", "input": {}}]},
        {"texto": "Un asesor continuará la conversación."}])  # fmt: skip
    c.decir("quiero poner una queja")
    from app.modulos.conversaciones.modelos import ColaAtencion

    cola = c.db.scalar(select(ColaAtencion))
    assert len(cola.resumen) == 500 and cola.prioridad == 1 and cola.motivo == "queja"
    assert c.acciones()[1].codigo_error == "CONVERSACION_EN_TRASPASO"
    textos = [m.cuerpo for m in mensajes_de(c.db, c.conv().id, "ia")]
    assert textos and textos[0].endswith("continuará la conversación.")


def test_h21_h22_cierre(c):
    usar_llm([herramienta("cerrar_conversacion", resultado="contactado", resumen="x"),
              VERIFICAR, herramienta("cerrar_conversacion", resultado="contactado", resumen="Habló el titular"),
              {"texto": "Hasta pronto."}])  # fmt: skip
    c.decir("adiós")
    assert c.acciones()[0].codigo_error == "IDENTIDAD_NO_VERIFICADA"
    conv = c.conv()
    assert conv.estado == "cerrada" and conv.motivo_cierre == "sistema"
    assert c.db.scalar(select(Tipificacion)).resultado == "contactado"
    despedida = [m for m in mensajes_de(c.db, conv.id, "ia") if m.cuerpo.endswith("Hasta pronto.")]
    assert (
        despedida and despedida[0].estado == "enviado" and despedida[0].creado_en <= conv.cerrada_en
    )
    assert any(a.accion == "ia.cierre" for a in c.db.scalars(select(Auditoria)))


def test_h22_numero_errado_excluye_telefono(c):
    usar_llm([herramienta("cerrar_conversacion", resultado="numero_errado", resumen="No es el titular"),
              {"texto": "Disculpe."}])  # fmt: skip
    c.decir("no conozco a nadie con ese nombre")
    e = c.db.scalar(select(Exclusion))
    assert (e.motivo, e.canal, e.origen, e.creado_por) == (
        "numero_errado",
        "todos",
        "agente_ia",
        None,
    )
    assert c.db.scalar(select(Tipificacion)).resultado == "numero_errado"


def test_h24_historial_sin_observaciones(c):
    usar_llm([VERIFICAR, herramienta("consultar_historial_gestiones"), {"texto": "ok"}])
    c.decir("hola")
    assert c.acciones()[1].resultado == {"gestiones": []}
