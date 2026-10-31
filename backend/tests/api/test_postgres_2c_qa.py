# ruff: noqa: E501, F811
"""QA 2C sobre PostgreSQL real: concurrencia adicional a P1-P10 (marcador `postgres`).

Mensajes casi simultáneos del cliente, supervisor que toma durante la llamada al modelo, kill
switch (campaña y global) durante un turno con una herramienta de registro en vuelo, presupuesto
agotado por turnos concurrentes y aislamiento entre dos clientes atendidos a la vez."""

import json
import threading
import uuid
from datetime import timedelta

import pytest
from ia import NUMERO_PEDRO
from sqlalchemy import func, select
from test_postgres_2c import (  # noqa: F401,F811  (fixture `pg` y utilidades)
    AHORA,
    REG,
    Mundo,
    _contar,
    _en_hilos,
    _preparar_aceptacion,
    pg,
    reloj,
)
from wa import NUMERO, crear_conv

from app.config import get_settings
from app.integraciones.whatsapp.falso import ProveedorWhatsAppFalso
from app.modulos.agente_ia import configuracion
from app.modulos.agente_ia.llm import establecer_cliente_llm
from app.modulos.agente_ia.llm_falso import ClienteLLMFalso
from app.modulos.agente_ia.modelos import (
    ConfiguracionGlobal,
    ConfiguracionIACampana,
    HistorialIA,
    UsoIA,
)
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import IA
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.whatsapp.servicio_entrante import recibir
from app.trabajos.cola import ejecutar_pendientes
from app.trabajos.modelos import Trabajo

pytestmark = pytest.mark.postgres


def _params(numero, texto):
    return {
        "MessageSid": "SM" + uuid.uuid4().hex,
        "From": f"whatsapp:{numero}",
        "To": f"whatsapp:{get_settings().whatsapp_numero_empresa}",
        "Body": texto,
        "NumMedia": "0",
    }


def _recibir(pg, numero, texto, segundos=2):
    proveedor = ProveedorWhatsAppFalso(get_settings().twilio_auth_token)
    with pg() as db:
        return recibir(db, proveedor, _params(numero, texto), AHORA + timedelta(seconds=segundos))


@pytest.fixture()
def limpiar_llm():
    yield
    establecer_cliente_llm(None)


def test_q1_dos_mensajes_casi_simultaneos_un_solo_turno(pg, limpiar_llm):
    Mundo(pg)
    llm = ClienteLLMFalso([{"texto": "Hola"}] * 4, retardo=0.3)
    establecer_cliente_llm(llm)
    barrera = threading.Barrier(2)

    def enviar(texto):
        barrera.wait()
        return _recibir(pg, NUMERO, texto)

    res = _en_hilos([lambda: enviar("Quiero pagar"), lambda: enviar("en tres cuotas")])
    assert all(not isinstance(r, BaseException) and r is not None for r in res), res

    # procesar entrantes (dos workers a la vez) y, pasado el debounce, el turno (dos workers)
    def correr(segundos):
        with pg() as db:
            return ejecutar_pendientes(db, AHORA + timedelta(seconds=segundos))

    _en_hilos([lambda: correr(3), lambda: correr(3)])
    with pg() as db:
        turnos = list(db.scalars(select(Trabajo).where(Trabajo.tipo == "ia.turno")))
        assert len(turnos) == 1, [t.estado for t in turnos]
        convs = list(db.scalars(select(Conversacion)))
        assert len(convs) == 1 and convs[0].atendida_por == "ia"
    _en_hilos([lambda: correr(60), lambda: correr(60)])
    assert llm.llamadas == 1
    with pg() as db:
        entrantes = list(db.scalars(select(Mensaje).where(Mensaje.direccion == "entrante")))
        assert len(entrantes) == 2 and all(e.procesado_ia_en is not None for e in entrantes)
        bloques = [f for f in db.scalars(select(HistorialIA)) if f.tipo == "entradas_cliente"]
        assert len(bloques) == 1
        texto = json.dumps(bloques[0].contenido, ensure_ascii=False)
        assert texto.count("<mensaje_cliente ") == 2
        n_ia = db.scalar(select(func.count(Mensaje.id)).where(Mensaje.autor == "ia"))
        assert n_ia == 1
        assert db.scalar(select(Conversacion.turnos_ia)) == 1


def test_q2_supervisor_toma_durante_la_llamada_al_modelo(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion()
    llm = ClienteLLMFalso([{"texto": "esto no debe enviarse"}], retardo=1.0)

    def tomar():
        import time

        time.sleep(0.4)
        with pg() as db:
            return conversaciones.tomar(db, m.admin, cid, AHORA + timedelta(seconds=11))

    res = _en_hilos([lambda: m.turno(cid, llm, "w:1"), tomar])
    assert all(not isinstance(r, BaseException) for r in res), res
    with pg() as db:
        assert db.get(Conversacion, cid).atendida_por == "humano"
        assert db.scalar(select(func.count(Mensaje.id)).where(Mensaje.autor == "ia")) == 0
        assert not any(f.rol == "assistant" for f in db.scalars(select(HistorialIA)))
        assert db.scalar(select(func.count(UsoIA.id))) == 1  # el gasto sí queda registrado


@pytest.mark.parametrize("nivel", ["campana", "global"])
def test_q3_kill_switch_durante_un_turno_con_registro_en_vuelo(pg, nivel):
    """La respuesta con `registrar_acuerdo_pago` llega DESPUÉS de apagar la IA: no se ejecuta."""
    m = Mundo(pg)
    cid, _ = m.conversacion()
    _preparar_aceptacion(m, cid)
    llm = ClienteLLMFalso([{"herramientas": [{"id": "toolu_q3", **REG}]}, {"texto": "Listo."}],
                          retardo=1.0)  # fmt: skip

    def apagar():
        import time

        time.sleep(0.4)
        with pg() as db:
            if nivel == "campana":
                configuracion.desactivar(db, m.admin, m.ctx.campana.id, AHORA)
            else:
                fila = db.get(ConfiguracionGlobal, "ia_activa")
                if fila is None:
                    db.add(
                        ConfiguracionGlobal(clave="ia_activa", valor=False, actualizado_en=AHORA)
                    )
                else:
                    fila.valor = False
                db.commit()

    res = _en_hilos([lambda: m.turno(cid, llm, "w:1"), apagar])
    assert all(not isinstance(r, BaseException) for r in res), res
    assert _contar(pg, Tipificacion) == 0 and _contar(pg, PromesaPago) == 0
    with pg() as db:
        assert not any("Constancia" in (x.cuerpo or "") for x in db.scalars(select(Mensaje)))
        assert (
            db.scalar(select(func.count(Mensaje.id)).where(Mensaje.autor == "ia")) == 1
        )  # el previo


def test_q4_presupuesto_agotado_por_dos_turnos_concurrentes(pg):
    """Dos conversaciones cruzan el presupuesto a la vez: sobrepaso <= 2 llamadas, una sola
    desactivación y una sola alerta; el tercer turno ya no llama al modelo."""
    m = Mundo(pg)
    with pg() as db:
        db.get(ConfiguracionIACampana, m.ctx.campana.id).presupuesto_usd_mensual = 0.02
        db.commit()
    a, _ = m.conversacion(numero=NUMERO)
    b, _ = m.conversacion(numero=NUMERO_PEDRO)
    c, _ = m.conversacion(numero="+573007700099")
    caro = {"uso": {"input_tokens": 3000, "output_tokens": 150}}  # 0,015 USD con Opus
    llm = ClienteLLMFalso([dict({"texto": "ok"}, **caro)] * 6, retardo=0.5)
    res = _en_hilos([lambda: m.turno(a, llm, "wa:1"), lambda: m.turno(b, llm, "wb:1")])
    assert all(not isinstance(r, BaseException) for r in res), res
    assert llm.llamadas == 2
    llamadas_antes = llm.llamadas
    m.turno(c, llm, "wc:1")
    assert llm.llamadas == llamadas_antes  # presupuesto cruzado: ya no se llama
    with pg() as db:
        cfg = db.get(ConfiguracionIACampana, m.ctx.campana.id)
        assert cfg.activa is False and cfg.desactivada_motivo == "presupuesto"
        assert db.scalar(select(func.sum(UsoIA.costo_usd))) <= 2 * 0.026  # sobrepaso <= 2 llamadas
        assert (
            db.scalar(select(func.count(Auditoria.id)).where(Auditoria.accion == "ia.desactivar"))
            == 1
        )
        assert db.get(Conversacion, c).atendida_por == "sin_asignar"


def test_q5_dos_clientes_a_la_vez_no_mezclan_datos(pg):
    """María y Pedro (misma campaña) se verifican a la vez con el modelo en modo demo: cada uno
    recibe SOLO su saldo y ninguna petición de María contiene datos de Pedro y viceversa."""
    m = Mundo(pg)
    cm, _ = m.conversacion(numero=NUMERO, entrantes=("Mi cédula es 1020304050",))
    with pg() as db:
        conv_p = crear_conv(db, AHORA, numero=NUMERO_PEDRO, cc=m.ctx.pedro, dueno=IA())
        m.entrante(db, conv_p, "Mi cédula es 99887766", 0)
        cp = conv_p.id
    llm = ClienteLLMFalso(None, retardo=0.2)  # modo demo (determinista)

    def turno(cid):
        return m.turno(cid, llm, f"w{cid}:1")

    res = _en_hilos([lambda: turno(cm), lambda: turno(cp)])
    assert all(not isinstance(r, BaseException) for r in res), res
    with pg() as db:
        for cid, saldo, ajeno in ((cm, "300.000", "777.777"), (cp, "777.777", "300.000")):
            textos = [x.cuerpo for x in db.scalars(select(Mensaje).where(
                Mensaje.conversacion_id == cid, Mensaje.autor == "ia"))]  # fmt: skip
            assert any(saldo in t for t in textos), (cid, textos)
            assert not any(ajeno in t for t in textos)
            filas = json.dumps([f.contenido for f in db.scalars(
                select(HistorialIA).where(HistorialIA.conversacion_id == cid))], ensure_ascii=False)  # fmt: skip
            assert ajeno not in filas and ajeno.replace(".", "") not in filas


def test_q6_mensaje_que_llega_durante_el_turno_se_atiende_en_otro_turno(pg, limpiar_llm):
    m = Mundo(pg)
    cid, ids = m.conversacion(entrantes=("hola",))
    llm = ClienteLLMFalso([{"texto": "primera"}, {"texto": "segunda"}], retardo=0.8)

    def llega_otro():
        import time

        time.sleep(0.3)
        with pg() as db:
            conv = db.get(Conversacion, cid)
            return m.entrante(db, conv, "otra pregunta", 5, segundos=3)

    res = _en_hilos([lambda: m.turno(cid, llm, "w:1"), llega_otro])
    assert all(not isinstance(r, BaseException) for r in res), res
    nuevo = res[1]
    with pg() as db:
        assert db.get(Mensaje, ids[0]).procesado_ia_en is not None
        assert db.get(Mensaje, nuevo).procesado_ia_en is None  # no se pierde ni se consume a medias
    m.turno(cid, llm, "w:2")
    with pg() as db:
        assert db.get(Mensaje, nuevo).procesado_ia_en is not None
        assert llm.llamadas == 2
