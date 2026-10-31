"""Turno del agente IA sobre WhatsApp (fase-2c.md §4.4; casos T de QA)."""

from ia import escenario_ia, escribir, herramienta, mensajes_de, usar_llm
from sqlalchemy import select

from app.modulos.agente_ia.modelos import AccionIA, HistorialIA, UsoIA
from app.modulos.conversaciones.modelos import Conversacion


def test_t1_entrante_a_conversacion_ia_con_aviso(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario
):
    escenario_ia(esc, crear_usuario, db)
    llm = usar_llm([{"texto": "Hola, ¿me indica su número de documento?"}, {"texto": "Gracias."}])
    escribir(client, firmar_twilio, correr_trabajos, reloj, "Hola")
    conv = db.scalar(select(Conversacion))
    assert conv.atendida_por == "ia" and conv.turnos_ia == 1 and conv.aviso_ia_enviado_en
    ia = mensajes_de(db, conv.id, "ia")
    assert len(ia) == 1 and ia[0].cuerpo.startswith("Le atiende el asistente virtual")
    assert ia[0].cuerpo.endswith("número de documento?")
    assert len(llm.peticiones) == 1
    escribir(client, firmar_twilio, correr_trabajos, reloj, "mi cédula")
    ia = mensajes_de(db, conv.id, "ia")
    assert len(ia) == 2 and not ia[1].cuerpo.startswith("Le atiende")


def test_flujo_con_herramientas_historial_y_uso(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario
):
    escenario_ia(esc, crear_usuario, db)
    usar_llm(
        [
            herramienta("verificar_identidad", numero_documento="1.020.304.050"),
            herramienta("consultar_obligacion"),
            {"texto": "Gracias, María. Su saldo en mora es de $ 300.000."},
        ]
    )
    escribir(client, firmar_twilio, correr_trabajos, reloj, "Mi cédula es 1.020.304.050")
    conv = db.scalar(select(Conversacion))
    assert conv.identidad_verificada
    acciones = list(db.scalars(select(AccionIA).order_by(AccionIA.id)))
    assert [a.herramienta for a in acciones] == ["verificar_identidad", "consultar_obligacion"]
    assert acciones[0].entrada == {"numero_documento": "***4050"}
    filas = list(db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia)))
    assert [(f.rol, f.tipo) for f in filas] == [
        ("user", "entradas_cliente"),
        ("system", "contexto"),
        ("assistant", "respuesta"),
        ("user", "resultados_herramientas"),
        ("assistant", "respuesta"),
        ("user", "resultados_herramientas"),
        ("assistant", "respuesta"),
    ]
    assert db.scalar(select(UsoIA.id).limit(1)) is not None
    assert "$ 300.000" in mensajes_de(db, conv.id, "ia")[0].cuerpo


# ---- Más casos T ------------------------------------------------------------------------------
import json  # noqa: E402
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from wa import NUMERO, entrante  # noqa: E402

from app.modulos.agente_ia.modelos import ConfiguracionIACampana, ErrorIA  # noqa: E402
from app.modulos.auditoria.modelos import Auditoria  # noqa: E402
from app.modulos.conversaciones.modelos import ColaAtencion  # noqa: E402
from app.trabajos.modelos import Trabajo  # noqa: E402


@pytest.fixture()
def e(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario):
    from types import SimpleNamespace

    ctx = escenario_ia(esc, crear_usuario, db)

    def decir(texto, **kw):
        escribir(client, firmar_twilio, correr_trabajos, reloj, texto, **kw)
        db.expire_all()

    return SimpleNamespace(
        ctx=ctx, decir=decir, db=db, reloj=reloj, correr=correr_trabajos, client=client,
        firmar=firmar_twilio,
        conv=lambda: db.scalar(select(Conversacion).order_by(Conversacion.id.desc())),
        cola=lambda: db.scalar(select(ColaAtencion).order_by(ColaAtencion.id.desc())),
    )  # fmt: skip


def test_t2_t3_sin_ia_o_sin_registro(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario
):
    ctx = escenario_ia(esc, crear_usuario, db)
    ctx.cfg.activa = False
    db.commit()
    entrante(client, firmar_twilio, NUMERO, "Hola")
    correr_trabajos(reloj())
    assert db.scalar(select(Conversacion)).atendida_por == "sin_asignar"
    entrante(client, firmar_twilio, "+573005550000", "Hola")
    correr_trabajos(reloj())
    otra = db.scalar(
        select(Conversacion).where(Conversacion.numero_cliente_e164 == "+573005550000")
    )
    assert otra.atendida_por == "sin_asignar"
    assert (
        db.scalar(select(ColaAtencion).where(ColaAtencion.conversacion_id == otra.id)).motivo
        == "sin_campana"
    )


def test_t4_debounce_tres_mensajes_un_turno(e):
    llm = usar_llm([{"texto": "Hola, ¿su documento?"}])
    for t in ("uno", "dos", "tres"):
        entrante(e.client, e.firmar, NUMERO, t)
        e.reloj.avanzar(seconds=1)
    e.correr(e.reloj())
    turnos = list(e.db.scalars(select(Trabajo).where(Trabajo.tipo == "ia.turno")))
    assert len(turnos) == 1
    e.reloj.avanzar(seconds=30)
    e.correr(e.reloj())
    assert len(llm.peticiones) == 1
    bloques = [b["text"] for b in llm.peticiones[0]["mensajes"][0]["content"]]
    assert sum("<mensaje_cliente" in b for b in bloques) == 3


def test_t6_t7_dos_herramientas_y_error(e):
    usar_llm([{"herramientas": [
        {"name": "verificar_identidad", "input": {"numero_documento": "1020304050"}},
        {"name": "consultar_obligacion", "input": {}}]},
        {"herramientas": [{"name": "simular_acuerdo_pago", "input": {
            "monto_total": "abc", "numero_cuotas": 1, "fecha_primer_pago": "2026-10-30", "periodicidad": "unica"}}]},
        {"texto": "Con un solo pago el mínimo es $ 240.000."}])  # fmt: skip
    e.decir("hola")
    filas = list(e.db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia)))
    resultados = [f for f in filas if f.tipo == "resultados_herramientas"]
    assert len(resultados[0].contenido) == 2 and resultados[1].contenido[0]["is_error"] is True
    assert json.loads(resultados[1].contenido[0]["content"])["codigo"] == "MONTO_INVALIDO"
    assert mensajes_de(e.db, e.conv().id, "ia")


@pytest.mark.parametrize(
    "paso,motivo",
    [
        ({"stop_reason": "max_tokens", "texto": "corta"}, "ia_max_tokens"),
        ({"stop_reason": "refusal", "categoria": "cyber"}, "ia_rechazo"),
        ({"stop_reason": "otro_raro"}, "ia_stop_inesperado"),
    ],
)
def test_t9_t10_t12_stops(e, paso, motivo):
    usar_llm([paso])
    e.decir("hola")
    assert e.cola().motivo == motivo and e.conv().atendida_por == "sin_asignar"
    assert mensajes_de(e.db, e.conv().id, "ia") == []
    uso = e.db.scalar(select(UsoIA))
    if motivo == "ia_rechazo":
        assert uso.stop_categoria == "cyber"
        assert any(a.accion == "ia.rechazo_modelo" for a in e.db.scalars(select(Auditoria)))


def test_t8_iteraciones_agotadas(e, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ia_max_iteraciones", 3)
    usar_llm([herramienta("consultar_obligacion")] * 5)
    e.decir("hola")
    assert e.cola().motivo == "ia_iteraciones"


def test_t11_pause_turn_sin_user_nuevo(e):
    llm = usar_llm([{"stop_reason": "pause_turn"}, {"texto": "Listo, ¿su documento?"}])
    e.decir("hola")
    p1, p2 = (x["mensajes"] for x in llm.peticiones)
    assert p2[:-1] == p1 and p2[-1]["role"] == "assistant"  # se reanuda sin `user` nuevo
    assert mensajes_de(e.db, e.conv().id, "ia")


def test_t13_end_turn_vacio(e):
    usar_llm([{"stop_stop": 1, "texto": ""}])
    e.decir("hola")
    assert mensajes_de(e.db, e.conv().id, "ia") == [] and e.conv().atendida_por == "ia"


def test_t14_t15_error_transitorio_reintento_y_agotado(e):
    llm = usar_llm([{"error": "RATE_LIMIT"}, {"texto": "Ya, ¿su documento?"}])
    e.decir("hola")  # el reintento con backoff (5 s) ocurre dentro del avance del ayudante
    assert len(mensajes_de(e.db, e.conv().id, "ia")) == 1
    users = [f for f in e.db.scalars(select(HistorialIA)) if f.tipo == "entradas_cliente"]
    assert len(users) == 1  # el user no se duplica
    assert e.db.scalar(select(ErrorIA)).transitorio is True
    assert llm.llamadas == 2


def test_t15_agotado_deriva(e):
    usar_llm([{"error": "RATE_LIMIT"}] * 3)
    e.decir("hola")
    for _ in range(3):
        e.reloj.avanzar(seconds=700)
        e.correr(e.reloj())
    assert e.cola().motivo == "ia_error"
    assert any(x.codigo == "AGOTADO" for x in e.db.scalars(select(ErrorIA)))


def test_t16_error_no_transitorio_y_desactivacion_automatica(e, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ia_errores_umbral", 2)
    usar_llm([{"error": "HTTP_400"}, {"error": "HTTP_400"}])
    e.decir("hola")
    assert e.cola().motivo == "ia_error"
    cfg = e.db.get(ConfiguracionIACampana, e.ctx.campana.id)
    assert cfg.activa is True
    # segunda conversación (otro número) que también falla
    e.ctx.numero  # noqa: B018
    from app.modulos.clientes.modelos import Telefono

    e.db.add(
        Telefono(
            cliente_id=e.ctx.pedro.cliente_id,
            numero_e164="+573005557777",
            tipo_linea="movil",
            prioridad=2,
        )
    )
    e.db.commit()
    entrante(e.client, e.firmar, "+573005557777", "hola")
    e.correr(e.reloj())
    e.reloj.avanzar(seconds=30)
    e.correr(e.reloj())
    e.db.expire_all()
    cfg = e.db.get(ConfiguracionIACampana, e.ctx.campana.id)
    assert cfg.activa is False and cfg.desactivada_motivo == "errores"


def test_t17_desactivacion_entre_iteraciones(e):
    llm = usar_llm([dict(herramienta("consultar_obligacion"),
                         antes=lambda p: _apagar(e.db, e.ctx.campana.id)), {"texto": "no debe salir"}])  # fmt: skip
    e.decir("hola")
    assert llm.llamadas == 1
    assert mensajes_de(e.db, e.conv().id, "ia") == []
    assert e.cola().motivo == "ia_desactivada"


def _apagar(db, campana_id):
    from sqlalchemy.orm import Session

    with Session(bind=db.get_bind()) as s:
        s.get(ConfiguracionIACampana, campana_id).activa = False
        s.commit()


def test_t18_supervisor_toma_durante_la_llamada(e, h_admin):
    def tomar(_p):
        r = e.client.post(f"/api/v1/conversaciones/{e.conv().id}/tomar", headers=h_admin)
        assert r.status_code == 200, r.text

    usar_llm([dict({"texto": "no debe enviarse"}, antes=tomar)])
    e.decir("hola")
    assert e.conv().atendida_por == "humano"
    assert mensajes_de(e.db, e.conv().id, "ia") == []
    assert [f.rol for f in e.db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia))].count(
        "assistant"
    ) == 0
    assert e.db.scalar(select(UsoIA)) is not None


def test_t19_reintento_sin_reejecutar(e, monkeypatch):
    import app.modulos.agente_ia.bucle as bucle

    original = bucle._ejecutar_herramientas
    usar_llm([{"herramientas": [
        {"name": "verificar_identidad", "input": {"numero_documento": "1020304050"}},
        {"name": "consultar_obligacion", "input": {}}]}, {"texto": "Listo."}])  # fmt: skip
    llamadas = {"n": 0}

    def fallar_una_vez(*a, **k):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            from app.modulos.agente_ia.herramientas.ejecutores import ejecutar_herramienta

            sesion, canal, ctx, r, estado, reloj, trab = a
            ejecutar_herramienta(sesion, canal, ctx, r.contenido[0], estado, reloj, trab)
            raise RuntimeError("caída")
        return original(*a, **k)

    monkeypatch.setattr(bucle, "_ejecutar_herramientas", fallar_una_vez)
    e.decir("hola")
    e.reloj.avanzar(seconds=700)
    e.correr(e.reloj())
    acciones = list(e.db.scalars(select(AccionIA).order_by(AccionIA.id)))
    assert [a.herramienta for a in acciones] == ["verificar_identidad"]  # nada se reejecuta
    resultados = [
        json.loads(b["content"])
        for f in e.db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia))
        if f.tipo == "resultados_herramientas"
        for b in f.contenido
    ]
    assert resultados[0] == {"verificada": True} and resultados[1]["codigo"] == "INTERRUMPIDO"


def test_t20_t22_presupuesto_conversacion(e):
    e.ctx.cfg.max_costo_conversacion_usd = __import__("decimal").Decimal("0.0001")
    e.db.commit()
    llm = usar_llm([{"texto": "Hola"}])
    e.decir("hola")
    e.decir("otra vez")
    assert llm.llamadas == 1 and e.cola().motivo == "presupuesto_excedido"


def test_t21_presupuesto_campana_desactiva_una_vez(e):
    e.ctx.cfg.presupuesto_usd_mensual = __import__("decimal").Decimal("0.01")
    e.db.commit()
    usar_llm([{"texto": "Hola"}, {"texto": "otra"}])
    e.decir("hola")
    e.decir("segundo")
    cfg = e.db.get(ConfiguracionIACampana, e.ctx.campana.id)
    assert cfg.activa is False and cfg.desactivada_motivo == "presupuesto"
    assert e.cola().motivo == "presupuesto_excedido"


def test_t23_fuera_de_franja_retiene_y_ejecuta_a_las_0800(e):
    from app.modulos.cumplimiento.modelos import PoliticaCumplimiento

    for p in e.db.scalars(select(PoliticaCumplimiento)):
        p.configuracion = {
            **p.configuracion,
            "entrantes": {"responder_fuera_de_franja": False, "establecen_contacto_directo": True},
        }
    e.db.commit()
    from datetime import UTC, datetime

    e.reloj.fijar(
        datetime(
            2026, 10, 23, 19, 20, tzinfo=__import__("zoneinfo").ZoneInfo("America/Bogota")
        ).astimezone(UTC)
    )
    llm = usar_llm([{"texto": "Buenos días"}])
    e.decir("hola")
    assert llm.llamadas == 0
    t = e.db.scalar(select(Trabajo).where(Trabajo.tipo == "ia.turno"))
    assert (
        t.estado == "pendiente"
        and t.disponible_desde.astimezone(
            __import__("zoneinfo").ZoneInfo("America/Bogota")
        ).strftime("%a %H:%M")
        == "Sat 08:00"
    )
    e.reloj.fijar(t.disponible_desde + timedelta(seconds=5))
    e.correr(e.reloj())
    assert llm.llamadas == 1


def test_t24_t26_media_prefijo_y_costes(e):
    llm = usar_llm([{"texto": "Escriba por favor"}, {"texto": "Gracias"}])
    entrante(
        e.client,
        e.firmar,
        NUMERO,
        "",
        NumMedia="1",
        MediaUrl0="https://media.falso.invalid/a",
        MediaContentType0="audio/ogg",
    )
    e.correr(e.reloj())
    e.reloj.avanzar(seconds=30)
    e.correr(e.reloj())
    texto = json.dumps(llm.peticiones[0]["mensajes"])
    assert 'soportado=\\"false\\"' in texto and "http" not in texto
    e.decir("ahora texto")
    a, b = llm.peticiones
    assert (a["sistema"], a["herramientas"]) == (b["sistema"], b["herramientas"])
    n = len(a["mensajes"])
    assert b["mensajes"][: n - 1] == a["mensajes"][: n - 1] or b["mensajes"][0] == a["mensajes"][0]
    usos = list(e.db.scalars(select(UsoIA).order_by(UsoIA.id)))
    assert usos[0].cache_creation_input_tokens == 2000 and usos[1].cache_read_input_tokens == 2000
    esperado = (usos[0].input_tokens * 4 + usos[0].output_tokens * 20 + 2000 * 5) / 1e6
    assert float(usos[0].costo_usd) == pytest.approx(esperado)
    assert e.conv().turnos_ia == 2 and float(e.conv().costo_usd_acumulado) == pytest.approx(
        float(usos[0].costo_usd + usos[1].costo_usd)
    )


def test_t27_opt_out_posterior_cancela_el_envio(e):
    usar_llm([{"texto": "Hola"}])
    entrante(e.client, e.firmar, NUMERO, "hola")
    e.correr(e.reloj())
    e.reloj.avanzar(seconds=5)
    e.correr(e.reloj())  # turno: crea el mensaje `ia` pendiente de envío
    from app.modulos.exclusiones.modelos import Exclusion

    e.db.add(Exclusion(numero_e164=NUMERO, motivo="solicitud_titular", aplica_a="todas", canal="whatsapp",
                       origen="sistema", creado_en=e.reloj() + timedelta(seconds=10)))  # fmt: skip
    e.db.commit()
    e.reloj.avanzar(seconds=60)
    e.correr(e.reloj())
    e.db.expire_all()
    m = mensajes_de(e.db, e.conv().id, "ia")[0]
    assert m.estado == "fallido" and m.error_codigo == "CLIENTE_OPT_OUT"


def test_t29_arrendamiento_ajeno_reprograma(e):
    from app.modulos.agente_ia import arrendamiento
    from app.modulos.agente_ia.contexto import RefInteraccion

    llm = usar_llm([{"texto": "Hola"}])
    entrante(e.client, e.firmar, NUMERO, "hola")
    e.correr(e.reloj())
    ref = RefInteraccion("conversacion", e.conv().id)
    arrendamiento.adquirir(e.db, ref, "otro:1", e.reloj() + timedelta(seconds=4))
    e.db.commit()
    e.reloj.avanzar(seconds=5)
    e.correr(e.reloj(), 1)
    t = e.db.scalar(select(Trabajo).where(Trabajo.tipo == "ia.turno"))
    assert llm.llamadas == 0 and t.estado == "pendiente" and t.intentos == 0
    e.reloj.avanzar(seconds=400)  # el arrendamiento caducó
    e.correr(e.reloj())
    assert llm.llamadas == 1


def test_t30_t31_stop_y_asesor(e):
    llm = usar_llm([])
    e.decir("STOP")
    assert e.conv().motivo_cierre == "opt_out" and llm.llamadas == 0
    assert e.db.scalar(select(Trabajo).where(Trabajo.tipo == "ia.turno")) is None


def test_t31_asesor_deriva_sin_modelo(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario
):
    from app.modulos.consola.modelos import EstadoAgente

    ctx = escenario_ia(esc, crear_usuario, db)
    llm = usar_llm([])
    escribir(client, firmar_twilio, correr_trabajos, reloj, "asesor")
    fila = db.scalar(select(ColaAtencion))
    assert (
        fila.motivo == "solicitud_cliente"
        and fila.prioridad == 1
        and "pidió hablar con un asesor" in fila.resumen
    )
    sis = mensajes_de(db, fila.conversacion_id, "sistema")
    assert sis and "espera" in sis[0].cuerpo.lower() or "responderá" in sis[0].cuerpo
    assert llm.llamadas == 0
    db.add(
        EstadoAgente(
            usuario_id=ctx.agente.id, estado="disponible", desde=reloj(), actualizado_en=reloj()
        )
    )
    db.commit()


def test_t32_campana_pausada(e):
    e.ctx.campana.estado = "pausada"
    e.db.commit()
    llm = usar_llm([])
    entrante(e.client, e.firmar, NUMERO, "hola")
    e.correr(e.reloj())
    assert e.conv().atendida_por == "sin_asignar" and llm.llamadas == 0
