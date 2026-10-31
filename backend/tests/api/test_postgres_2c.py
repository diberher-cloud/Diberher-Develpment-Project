"""Concurrencia real del agente IA sobre PostgreSQL (marcador `postgres`; P1-P10 de §9).

Esquema con las migraciones reales; cada hilo usa su propia sesión. `ClienteLLMFalso` con
retardos simula la latencia del modelo."""

import os
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from escenario import Escenario
from ia import NUMERO_PEDRO, escenario_ia, herramienta
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from wa import NUMERO, crear_conv, plantilla

from alembic import command
from alembic.config import Config
from app.db import crear_engine
from app.errores import ErrorApp
from app.modulos.agente_ia import arrendamiento, bucle, configuracion, derivacion
from app.modulos.agente_ia.canal_chat import CanalChat
from app.modulos.agente_ia.contexto import RefInteraccion, cargar_contexto
from app.modulos.agente_ia.herramientas.ejecutores import EstadoTurno, ejecutar_herramienta
from app.modulos.agente_ia.llm_falso import ClienteLLMFalso
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, HistorialIA, UsoIA
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import Telefono
from app.modulos.consola import tipificacion
from app.modulos.consola.modelos import Tipificacion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import IA, Humano
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_entrante, servicio_envio
from app.seguridad import hash_password
from app.trabajos import registro
from app.trabajos.modelos import Trabajo
from app.trabajos.registro import ReprogramarTrabajo

pytestmark = pytest.mark.postgres
RAIZ = Path(__file__).parent.parent.parent
AHORA = datetime(2026, 10, 23, 15, 15, tzinfo=UTC)


def reloj():
    return AHORA + timedelta(seconds=10)


def _cfg(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def pg() -> Iterator[sessionmaker[Session]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definido")
    cfg = _cfg(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = crear_engine(url)
    fabrica = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    registro.cargar_manejadores()
    try:
        yield fabrica
    finally:
        engine.dispose()
        command.downgrade(cfg, "base")


def _usuario(db: Session, rol: str, n: int) -> Usuario:
    u = Usuario(
        email=f"{rol}{n}@x.co", nombre=f"{rol} {n}", rol=rol, password_hash=hash_password("x" * 12)
    )
    db.add(u)
    db.commit()
    return u


def _en_hilos(funciones):
    salidas = [None] * len(funciones)

    def _correr(i, f):
        try:
            salidas[i] = f()
        except BaseException as exc:  # noqa: BLE001
            salidas[i] = exc

    hilos = [threading.Thread(target=_correr, args=(i, f)) for i, f in enumerate(funciones)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(90)
        assert not h.is_alive(), "hilo colgado (posible interbloqueo)"
    return salidas


class Mundo:
    """Escenario de cobranza con IA activa, un agente y un administrador."""

    def __init__(self, pg):
        self.pg = pg
        with pg() as db:
            self.admin = _usuario(db, "administrador", 0)
            self.agente = _usuario(db, "agente", 1)
            esc = Escenario(db, self.admin.id)
            self.ctx = escenario_ia(esc, lambda rol: self.agente, db)
            esc.estado(self.agente, "disponible", AHORA)
            plantilla(db, finalidad="cobranza")
            db.add(
                Telefono(
                    cliente_id=self.ctx.cc.cliente_id,
                    numero_e164="+573001230000",
                    tipo_linea="movil",
                    prioridad=2,
                )
            )
            db.commit()

    def conversacion(self, numero=NUMERO, entrantes=("hola",), dueno=None):
        with self.pg() as db:
            conv = crear_conv(db, AHORA, numero=numero, cc=self.ctx.cc, dueno=dueno or IA())
            ids = [self.entrante(db, conv, t, i) for i, t in enumerate(entrantes)]
            return conv.id, ids

    def entrante(self, db, conv, texto, i=0, segundos=0):
        m = Mensaje(
            conversacion_id=conv.id, numero_cliente_e164=conv.numero_cliente_e164, direccion="entrante",
            autor="cliente", tipo="texto", cuerpo=texto, estado="recibido",
            creado_en=AHORA + timedelta(seconds=segundos + i), procesado_en=AHORA,
        )  # fmt: skip
        db.add(m)
        db.commit()
        return m.id

    def turno(self, conv_id, llm, trabajador):
        return bucle.ejecutar_turno(
            self.pg, CanalChat(), RefInteraccion("conversacion", conv_id), llm, reloj, trabajador
        )

    def contexto(self, conv_id):
        with self.pg() as db:
            return cargar_contexto(db, RefInteraccion("conversacion", conv_id))


def _contar(pg, modelo, *filtros):
    with pg() as db:
        return db.scalar(select(func.count()).select_from(modelo).where(*filtros))


def test_p1_dos_workers_un_solo_turno(pg):
    m = Mundo(pg)
    cid, ids = m.conversacion()
    llm = ClienteLLMFalso([{"texto": "Hola"}] * 2, retardo=1.0)
    res = _en_hilos([lambda: m.turno(cid, llm, "a:1"), lambda: m.turno(cid, llm, "b:1")])
    reprogramados = [r for r in res if isinstance(r, ReprogramarTrabajo)]
    completados = [r for r in res if not isinstance(r, BaseException)]
    assert len(reprogramados) == 1 and len(completados) == 1 and llm.llamadas == 1
    with pg() as db:
        assert db.get(Mensaje, ids[0]).procesado_ia_en is not None
        usuarios = [f for f in db.scalars(select(HistorialIA)) if f.tipo == "entradas_cliente"]
        assert len(usuarios) == 1


def test_p2_diez_entrantes_dos_workers(pg):
    m = Mundo(pg)
    cid, ids = m.conversacion(entrantes=[f"mensaje {i}" for i in range(10)])
    llm = ClienteLLMFalso([{"texto": "ok"}] * 4, retardo=0.5)
    pendientes = [lambda: m.turno(cid, llm, "a:1"), lambda: m.turno(cid, llm, "b:1")]
    res = _en_hilos(pendientes)
    assert all(not isinstance(r, BaseException) or isinstance(r, ReprogramarTrabajo) for r in res)
    if any(isinstance(r, ReprogramarTrabajo) for r in res):
        m.turno(cid, llm, "b:2")
    assert llm.llamadas <= 2
    with pg() as db:
        texto = "".join(
            str(f.contenido)
            for f in db.scalars(select(HistorialIA))
            if f.tipo == "entradas_cliente"
        )
        for i in ids:
            assert (
                texto.count(f'<mensaje_cliente id=\\"{i}\\"')
                + texto.count(f'<mensaje_cliente id="{i}"')
                == 1
            )
        assert all(db.get(Mensaje, i).procesado_ia_en is not None for i in ids)


def _preparar_aceptacion(m: Mundo, cid):
    """Verifica y simula en un turno; el cliente acepta después."""
    llm = ClienteLLMFalso([
        herramienta("verificar_identidad", numero_documento="1020304050"),
        herramienta("simular_acuerdo_pago", monto_total="270000.00", numero_cuotas=3,
                    fecha_primer_pago="2026-10-30", periodicidad="quincenal"),
        {"texto": "Plan: 3 cuotas quincenales de $ 90.000, total $ 270.000."},
    ])  # fmt: skip
    assert m.turno(cid, llm, "w:0").estado == "completado"
    with m.pg() as db:
        conv = db.get(Conversacion, cid)
        m.entrante(db, conv, "Sí, acepto el plan", 0, segundos=3600)


REG = {
    "name": "registrar_acuerdo_pago",
    "input": {"monto_total": "270000.00", "numero_cuotas": 3, "fecha_primer_pago": "2026-10-30",
              "periodicidad": "quincenal", "confirmacion_cliente": "Sí, acepto el plan"},
}  # fmt: skip


def _ejecutar_tool(m: Mundo, cid, tid, trabajador="w:0"):
    ctx = m.contexto(cid)
    return ejecutar_herramienta(
        m.pg,
        CanalChat(),
        ctx,
        {"id": tid, **REG},
        EstadoTurno(),
        lambda: AHORA + timedelta(hours=2),
        trabajador,
    )


def _lease(m: Mundo, cid):
    with m.pg() as db:
        arrendamiento.adquirir(
            db, RefInteraccion("conversacion", cid), "w:0", AHORA + timedelta(hours=2)
        )
        db.commit()


def test_p3_tomar_durante_registrar_acuerdo(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion()
    _preparar_aceptacion(m, cid)
    llm = ClienteLLMFalso(
        [{"herramientas": [{"id": "toolu_p3", **REG}]}, {"texto": "Listo."}], retardo=0.8
    )

    def tomar():
        time.sleep(0.4)
        with pg() as db:
            return conversaciones.tomar(db, m.admin, cid, reloj())

    res = _en_hilos([lambda: m.turno(cid, llm, "w:1"), tomar])
    assert all(not isinstance(r, BaseException) for r in res), res
    with pg() as db:
        conv = db.get(Conversacion, cid)
        assert conv.atendida_por == "humano"
        n_ia = db.scalar(
            select(func.count(Mensaje.id)).where(
                Mensaje.autor == "ia", Mensaje.conversacion_id == cid
            )
        )
        tips = db.scalar(select(func.count(Tipificacion.id)))
        assert tips in (0, 1) and n_ia == 1  # nunca texto `ia` después de `humano`


def test_p4_registrar_acuerdo_y_tipificacion_de_voz(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion()
    _preparar_aceptacion(m, cid)
    _lease(m, cid)
    with pg() as db:
        tel = db.scalar(select(Telefono.id).where(Telefono.cliente_id == m.ctx.cc.cliente_id))
        ll = Llamada(campana_cliente_id=m.ctx.cc.id, telefono_id=tel, usuario_id=m.agente.id, canal="voz",
                     direccion="saliente", call_sid="CA1", estado="completada", motivos_bloqueo=[],
                     iniciada_en=AHORA, finalizada_en=AHORA)  # fmt: skip
        db.add(ll)
        db.commit()
        lid = ll.id

    def voz():
        with pg() as db:
            return tipificacion.tipificar_sistema(db, lid, "no_contesta", reloj())

    res = _en_hilos([lambda: _ejecutar_tool(m, cid, "toolu_p4"), voz])
    assert not isinstance(res[0], BaseException), res[0]
    assert not isinstance(res[1], BaseException) or isinstance(res[1], ErrorApp)
    assert _contar(pg, Tipificacion) >= 1


def test_p5_dos_registros_distinto_tool_use(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion()
    _preparar_aceptacion(m, cid)
    _lease(m, cid)
    res = _en_hilos(
        [lambda: _ejecutar_tool(m, cid, "toolu_a"), lambda: _ejecutar_tool(m, cid, "toolu_b")]
    )
    assert all(not isinstance(r, BaseException) for r in res), res
    codigos = sorted((r.resultado.get("codigo") or "ok") for r in res)
    assert codigos == ["GESTION_YA_REGISTRADA", "ok"] and _contar(pg, Tipificacion) == 1


def test_p6_mismo_tool_use_id_tres_veces(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion()
    _preparar_aceptacion(m, cid)
    _lease(m, cid)
    res = _en_hilos([lambda: _ejecutar_tool(m, cid, "toolu_uno")] * 3)
    assert all(not isinstance(r, BaseException) for r in res), res
    assert (
        res[0].resultado == res[1].resultado == res[2].resultado and res[0].resultado["registrado"]
    )
    assert _contar(pg, Tipificacion) == 1


def test_p7_desactivar_con_turnos_en_vuelo(pg):
    m = Mundo(pg)
    convs = [m.conversacion(numero=f"+5730077{i:05d}")[0] for i in range(6)]
    inicios: list[float] = []
    llm = ClienteLLMFalso([{"texto": "Hola"}] * 6, retardo=0.8)
    llm.gancho = lambda _p: inicios.append(time.monotonic())
    confirmado: list[float] = []

    def desactivar():
        time.sleep(0.3)
        with pg() as db:
            configuracion.desactivar(db, m.admin, m.ctx.campana.id, reloj())
        confirmado.append(time.monotonic())

    _en_hilos([desactivar] + [(lambda c=c: m.turno(c, llm, f"w{c}:1")) for c in convs])
    assert all(t < confirmado[0] for t in inicios)  # ninguna petición nueva tras la confirmación
    with pg() as db:
        while derivacion.traspasar_campana(db, {"campana_id": m.ctx.campana.id}, reloj()):
            db.commit()
        db.commit()
        assert db.scalar(select(func.count(Mensaje.id)).where(Mensaje.autor == "ia")) == 0
        assert {c.atendida_por for c in db.scalars(select(Conversacion))} == {"sin_asignar"}


def test_p8_presupuesto_al_limite_desactiva_una_vez(pg):
    m = Mundo(pg)
    with pg() as db:
        cfg = db.get(ConfiguracionIACampana, m.ctx.campana.id)
        cfg.presupuesto_usd_mensual = 0.015
        db.commit()
    convs = [m.conversacion(numero=f"+5730088{i:05d}")[0] for i in range(5)]
    llm = ClienteLLMFalso([{"texto": "ok"}] * 20, retardo=0.3)
    _en_hilos([(lambda c=c: m.turno(c, llm, f"w{c}:1")) for c in convs])
    with pg() as db:
        for c in convs:  # segunda ronda: el gasto ya cruzó el límite
            m.entrante(db, db.get(Conversacion, c), "otra", 5, segundos=100)
    res = _en_hilos([(lambda c=c: m.turno(c, llm, f"w{c}:2")) for c in convs])
    assert all(not isinstance(r, BaseException) for r in res), res
    with pg() as db:
        assert (
            db.scalar(select(func.count(Auditoria.id)).where(Auditoria.accion == "ia.desactivar"))
            == 1
        )
        assert db.get(ConfiguracionIACampana, m.ctx.campana.id).desactivada_motivo == "presupuesto"
        gasto = db.scalar(select(func.sum(UsoIA.costo_usd)))
        assert float(gasto) <= 0.015 + 5 * 0.03


def test_p9_devolver_ia_con_entrante_simultaneo(pg):
    m = Mundo(pg)
    cid, _ = m.conversacion(dueno=Humano(m.agente.id))
    with pg() as db:
        conv = db.get(Conversacion, cid)
        mensaje = Mensaje(conversacion_id=None, numero_cliente_e164=conv.numero_cliente_e164,
                          direccion="entrante", autor="cliente", tipo="texto", cuerpo="¿más plazo?",
                          estado="recibido", creado_en=AHORA, proveedor_id="SM1")  # fmt: skip
        db.add(mensaje)
        db.commit()
        mid = mensaje.id

    def devolver():
        with pg() as db:
            return derivacion.devolver_a_ia(db, m.admin, cid, reloj())

    def procesar():
        with pg() as db:
            servicio_entrante.procesar_entrante(db, {"mensaje_id": mid}, reloj())
            db.commit()

    res = _en_hilos([devolver, procesar])
    assert all(not isinstance(r, BaseException) for r in res), res
    with pg() as db:
        msg = db.get(Mensaje, mid)
        assert msg.procesado_en is not None and msg.conversacion_id == cid
        en_bloque = "¿más plazo?" in "".join(
            str(f.contenido) for f in db.scalars(select(HistorialIA)) if f.tipo == "intervencion"
        )
        turno = db.scalar(
            select(Trabajo).where(Trabajo.tipo == "ia.turno", Trabajo.estado == "pendiente")
        )
        assert (msg.procesado_ia_en is not None and en_bloque) or turno is not None
        assert not (msg.procesado_ia_en is not None and turno is not None and not en_bloque)


def test_p10_herramienta_con_efectos_plantilla_y_cierre_humano(pg):
    m = Mundo(pg)
    ia_id, _ = m.conversacion()
    hum_id, _ = m.conversacion(numero="+573001230000", dueno=Humano(m.agente.id))
    _preparar_aceptacion(m, ia_id)
    _lease(m, ia_id)
    with pg() as db:
        pl = plantilla(db, finalidad="cobranza")
        plid = pl.id

    def plantilla_2b():
        with pg() as db:
            return servicio_envio.enviar_plantilla_conversacion(
                db, m.agente, hum_id, plid, __import__("uuid").uuid4(), reloj()
            )

    def cierre_humano():
        from app.modulos.consola.esquemas import TipificacionDatos
        from app.modulos.conversaciones import cierre

        with pg() as db:
            return cierre.cerrar_conversacion(
                db, m.agente, hum_id, TipificacionDatos(resultado="contactado"), reloj()
            )

    res = _en_hilos([lambda: _ejecutar_tool(m, ia_id, "toolu_p10"), plantilla_2b, cierre_humano])
    assert not isinstance(res[0], BaseException), res[0]
    assert all(not isinstance(r, BaseException) or isinstance(r, ErrorApp) for r in res), res
    assert NUMERO_PEDRO
