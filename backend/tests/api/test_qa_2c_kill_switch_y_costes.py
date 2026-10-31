"""QA 2C: kill switch en tres niveles aun DURANTE un turno, presupuesto a mitad de turno y
costes exactos (T25)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from ia import NUMERO_PEDRO, escenario_ia, escribir, herramienta, mensajes_de, usar_llm
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from wa import NUMERO

from app.config import get_settings
from app.modulos.agente_ia.modelos import (
    AccionIA,
    ConfiguracionGlobal,
    ConfiguracionIACampana,
    UsoIA,
)
from app.modulos.campanas.modelos import Campana
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion

VERIFICAR = herramienta("verificar_identidad", numero_documento="1020304050")
SIM = herramienta("simular_acuerdo_pago", monto_total="270000.00", numero_cuotas=3,
                  fecha_primer_pago="2026-10-30", periodicidad="quincenal")  # fmt: skip
REG = herramienta("registrar_acuerdo_pago", monto_total="270000.00", numero_cuotas=3,
                  fecha_primer_pago="2026-10-30", periodicidad="quincenal",
                  confirmacion_cliente="Sí, acepto")  # fmt: skip


def apagar(nivel, db, campana_id, monkeypatch):
    """Apaga la IA en el nivel pedido desde OTRA sesión (como lo haría otro proceso)."""
    if nivel == "entorno":
        monkeypatch.setattr(get_settings(), "ia_habilitada", False)
        return
    with Session(bind=db.get_bind()) as s:
        if nivel == "campana":
            s.get(ConfiguracionIACampana, campana_id).activa = False
        elif nivel == "global":
            fila = s.get(ConfiguracionGlobal, "ia_activa")
            if fila is None:
                s.add(
                    ConfiguracionGlobal(
                        clave="ia_activa",
                        valor=False,
                        actualizado_en=datetime(2026, 10, 23, tzinfo=UTC),
                    )
                )
            else:
                fila.valor = False
        elif nivel == "pausada":
            s.get(Campana, campana_id).estado = "pausada"
        elif nivel == "sin_whatsapp":
            s.get(Campana, campana_id).whatsapp_habilitado = False
        s.commit()


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
        conv=lambda numero=NUMERO: db.scalar(
            select(Conversacion).where(Conversacion.numero_cliente_e164 == numero)
            .order_by(Conversacion.id.desc())),
        cola=lambda: db.scalar(select(ColaAtencion).order_by(ColaAtencion.id.desc())),
    )  # fmt: skip


NIVELES = ["campana", "global", "entorno", "pausada", "sin_whatsapp"]


@pytest.mark.parametrize("nivel", NIVELES)
def test_kill_switch_durante_la_llamada_descarta_la_respuesta(e, nivel, monkeypatch):
    llm = usar_llm(
        [
            dict(
                {"texto": "Su saldo es otra cosa, no debe salir"},
                antes=lambda _p: apagar(nivel, e.db, e.ctx.campana.id, monkeypatch),
            )
        ]
    )
    e.decir("hola")
    assert llm.llamadas == 1
    assert [m for m in mensajes_de(e.db, e.conv().id, "ia")] == []
    assert e.conv().atendida_por == "sin_asignar" and e.cola().motivo == "ia_desactivada"


@pytest.mark.parametrize("nivel", NIVELES)
def test_kill_switch_antes_de_ejecutar_un_registro_lo_impide(e, nivel, monkeypatch):
    """La respuesta con `registrar_acuerdo_pago` ya se generó cuando se apaga la IA: la
    herramienta NO se ejecuta (ni promesa, ni constancia) y la conversación pasa a humano."""
    import app.modulos.agente_ia.bucle as bucle

    usar_llm([VERIFICAR, SIM, {"texto": "Plan: 3 cuotas de $ 90.000, total $ 270.000."}, REG,
              {"texto": "Registrado."}])  # fmt: skip
    e.decir("Quiero 270 mil en 3 cuotas")
    original = bucle.ejecutar_herramienta

    def con_corte(sesion, canal, ctx, tool_use, *a, **k):
        if tool_use["name"] == "registrar_acuerdo_pago":
            apagar(nivel, e.db, e.ctx.campana.id, monkeypatch)
        return original(sesion, canal, ctx, tool_use, *a, **k)

    monkeypatch.setattr(bucle, "ejecutar_herramienta", con_corte)
    e.decir("Sí, acepto")
    assert e.db.scalar(select(PromesaPago)) is None and e.db.scalar(select(Tipificacion)) is None
    assert not any("Constancia" in (m.cuerpo or "") for m in mensajes_de(e.db, e.conv().id))
    assert not any("Registrado" in (m.cuerpo or "") for m in mensajes_de(e.db, e.conv().id))
    assert e.conv().atendida_por == "sin_asignar" and e.cola().motivo == "ia_desactivada"


@pytest.mark.parametrize("nivel", NIVELES)
def test_kill_switch_antes_del_turno_ni_llama_al_modelo(e, nivel, monkeypatch):
    llm = usar_llm([])
    apagar(nivel, e.db, e.ctx.campana.id, monkeypatch)
    e.decir("hola")
    assert llm.llamadas == 0
    assert mensajes_de(e.db, e.conv().id, "ia") == []
    assert e.conv().atendida_por == "sin_asignar"


def test_kill_switch_entre_dos_herramientas_del_mismo_turno(e, monkeypatch):
    """Dos `tool_use` en la misma respuesta; la IA se apaga tras la primera: la segunda no corre."""
    import app.modulos.agente_ia.bucle as bucle

    usar_llm([{"herramientas": [VERIFICAR["herramientas"][0],
                                {"name": "consultar_obligacion", "input": {}}]},
              {"texto": "Su saldo es $ 300.000"}])  # fmt: skip
    original = bucle.ejecutar_herramienta
    vistas = []

    def con_corte(sesion, canal, ctx, tool_use, *a, **k):
        r = original(sesion, canal, ctx, tool_use, *a, **k)
        vistas.append(tool_use["name"])
        if tool_use["name"] == "verificar_identidad":
            apagar("campana", e.db, e.ctx.campana.id, monkeypatch)
        return r

    monkeypatch.setattr(bucle, "ejecutar_herramienta", con_corte)
    e.decir("mi cédula 1020304050")
    acciones = [a.herramienta for a in e.db.scalars(select(AccionIA))]
    assert "consultar_obligacion" not in acciones
    assert mensajes_de(e.db, e.conv().id, "ia") == []
    assert e.conv().atendida_por == "sin_asignar"


# ---- Presupuesto a mitad de turno y en tres niveles ----
def test_presupuesto_de_conversacion_cruzado_a_mitad_de_turno_corta_el_bucle(e):
    e.ctx.cfg.max_costo_conversacion_usd = Decimal("0.0100")
    e.db.commit()
    caro = {"uso": {"input_tokens": 5000, "output_tokens": 500}}  # 0.03 USD con Opus
    llm = usar_llm([dict(VERIFICAR, **caro), {"texto": "no debe pedirse"}])
    e.decir("mi cédula 1020304050")
    assert llm.llamadas == 1
    assert e.cola().motivo == "presupuesto_excedido"
    assert not any(m.autor == "ia" for m in mensajes_de(e.db, e.conv().id))


def test_presupuesto_mensual_cruzado_por_otra_conversacion_desactiva_la_campana(e):
    """Otro gasto de la campaña ya agotó el mes: el siguiente turno no llama al modelo."""
    llm = usar_llm([{"texto": "Hola Pedro"}])
    e.decir("hola", numero=NUMERO_PEDRO)
    pedro = e.conv(NUMERO_PEDRO)
    e.db.add(
        UsoIA(
            conversacion_id=pedro.id,
            llamada_id=None,
            campana_id=e.ctx.campana.id,
            canal="whatsapp_mensaje",
            modelo="claude-opus-5-5",
            modelo_servido="claude-opus-5-5",
            esfuerzo="medium",
            respuesta_id="x",
            iteracion=1,
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            costo_usd=Decimal("250.000000"),
            duracion_ms=1,
            creado_en=e.reloj() - timedelta(hours=1),
        )
    )
    e.db.commit()
    e.decir("hola")
    assert llm.llamadas == 1
    cfg = e.db.get(ConfiguracionIACampana, e.ctx.campana.id)
    assert cfg.activa is False and cfg.desactivada_motivo == "presupuesto"


def test_limite_de_turnos_por_conversacion(e):
    e.ctx.cfg.max_turnos_conversacion = 2
    e.db.commit()
    llm = usar_llm([{"texto": "uno"}, {"texto": "dos"}, {"texto": "tres"}])
    e.decir("a")
    e.decir("b")
    e.decir("c")
    assert llm.llamadas == 2 and e.cola().motivo == "presupuesto_excedido"


# ---- T25: costes exactos ----
USO = {"input_tokens": 1234, "output_tokens": 567, "cache_creation_input_tokens": 800,
       "cache_read_input_tokens": 9000}  # fmt: skip


def test_t25_coste_exacto_opus_ttl_5m(e):
    usar_llm([dict({"texto": "Hola"}, uso=USO)])
    e.decir("hola")
    u = e.db.scalar(select(UsoIA))
    # (1234*4 + 567*20 + 800*5 + 9000*0.4) / 1e6 = 23.876 / 1000
    assert u.costo_usd == Decimal("0.023876")
    assert (u.input_tokens, u.output_tokens, u.cache_creation_input_tokens,
            u.cache_read_input_tokens) == (1234, 567, 800, 9000)  # fmt: skip
    assert e.conv().costo_usd_acumulado == Decimal("0.023876") and e.conv().turnos_ia == 1


def test_t25_coste_ttl_1h_y_modelo_servido_distinto(e, monkeypatch):
    monkeypatch.setattr(get_settings(), "ia_cache_ttl", "1h")
    usar_llm([dict({"texto": "Hola"}, uso=USO, modelo_servido="claude-sonnet-5-5")])
    e.decir("hola")
    u = e.db.scalar(select(UsoIA))
    assert u.modelo == "claude-opus-5-5" and u.modelo_servido == "claude-sonnet-5-5"
    # Sonnet: 1234*2 + 567*10 + 800*4 (escritura 1 h) + 9000*0.2 = 2468+5670+3200+1800 = 13138
    assert u.costo_usd == Decimal("0.013138")


def test_t25_acumulado_suma_todas_las_iteraciones_y_turnos(e):
    usar_llm([dict(VERIFICAR, uso=USO), dict({"texto": "Gracias"}, uso=USO),
              dict({"texto": "De nada"}, uso=USO)])  # fmt: skip
    e.decir("mi cédula 1020304050")
    e.decir("gracias")
    usos = list(e.db.scalars(select(UsoIA).order_by(UsoIA.id)))
    assert len(usos) == 3 and [u.iteracion for u in usos] == [1, 2, 1]
    assert sum(u.costo_usd for u in usos) == Decimal("0.071628")
    assert e.conv().costo_usd_acumulado == Decimal("0.071628") and e.conv().turnos_ia == 2


def test_uso_en_error_no_se_cobra_y_respuesta_vacia_si(e):
    """Un error del proveedor no deja fila de uso; una respuesta vacía (end_turn) sí."""
    usar_llm([{"error": "HTTP_400"}])
    e.decir("hola")
    assert e.db.scalar(select(UsoIA)) is None
    e.db.execute(update(Conversacion).values(costo_usd_acumulado=Decimal(0)))
