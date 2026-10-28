"""QA 2B sobre PostgreSQL real: más hilos y carreras adicionales a P1-P10 (marcador `postgres`)."""

import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_postgres_2b import (  # noqa: F401  (`pg` es una fixture)
    AHORA,
    _conv,
    _en_hilos,
    _entrante,
    _esc_whatsapp,
    _usuario,
    pg,
)
from wa import NUMERO

from app.errores import ErrorApp
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.modulos.conversaciones import atencion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, EventoMensaje, Mensaje
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_entrante, servicio_envio, servicio_estado
from app.trabajos import cola, registro
from app.trabajos.modelos import Trabajo

pytestmark = pytest.mark.postgres


def _sin_errores(resultados):
    assert all(not isinstance(x, BaseException) for x in resultados), resultados


def test_q1_ocho_tomar_simultaneos_de_la_misma_conversacion_solo_uno_gana(pg):  # noqa: F811
    _, camp, agentes = _esc_whatsapp(pg, n_agentes=8)
    with pg() as db:
        cid = _conv(db, NUMERO, camp)
    barrera = threading.Barrier(8, timeout=15)

    def tomar(uid):
        def _f():
            with pg() as s:
                u = s.get(Usuario, uid)
                barrera.wait()
                return conversaciones.tomar(s, u, cid, AHORA)

        return _f

    r = _en_hilos([tomar(a) for a in agentes])
    ganadores = [x for x in r if not isinstance(x, BaseException)]
    perdedores = [x for x in r if isinstance(x, BaseException)]
    assert len(ganadores) == 1 and len(perdedores) == 7, r
    assert all(isinstance(x, ErrorApp) and x.codigo == "CONVERSACION_ASIGNADA" for x in perdedores)
    with pg() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(ColaAtencion)
                .where(ColaAtencion.estado == "asignada")
            )
            == 1
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ColaAtencion)
                .where(ColaAtencion.estado == "pendiente")
            )
            == 0
        )


def test_q2_seis_agentes_tomar_siguiente_con_tres_filas_sin_repetir(pg):  # noqa: F811
    _, camp, agentes = _esc_whatsapp(pg, n_agentes=6)
    with pg() as db:
        ids = {_conv(db, f"+57311555000{i}", camp) for i in range(3)}
    barrera = threading.Barrier(6, timeout=15)

    def siguiente(uid):
        def _f():
            with pg() as s:
                u = s.get(Usuario, uid)
                barrera.wait()
                return atencion.tomar_siguiente(s, u, AHORA)

        return _f

    r = _en_hilos([siguiente(a) for a in agentes])
    _sin_errores(r)
    tomadas = [x.id for x in r if x is not None]
    assert sorted(tomadas) == sorted(ids), r
    assert sum(x is None for x in r) == 3


def test_q3_tres_workers_y_150_trabajos_cada_uno_exactamente_una_vez(pg):  # noqa: F811
    vistos: list[int] = []
    bloqueo = threading.Lock()

    def manejador(db, payload, ahora):
        with bloqueo:
            vistos.append(payload["n"])

    registro.MANEJADORES["test.q3"] = manejador
    try:
        with pg() as db:
            for n in range(150):
                cola.encolar(db, "test.q3", {"n": n}, ahora=AHORA)
            db.commit()

        def worker(nombre):
            def _f():
                while True:
                    with pg() as s:
                        tomados = [t.id for t in cola.tomar(s, nombre, AHORA, 5)]
                    if not tomados:
                        return
                    for tid in tomados:
                        cola.ejecutar(pg, tid, lambda: AHORA)

            return _f

        _sin_errores(_en_hilos([worker("a"), worker("b"), worker("c")]))
        assert sorted(vistos) == list(range(150))
        with pg() as s:
            assert s.scalar(select(func.count()).where(Trabajo.estado == "completado")) == 150
    finally:
        registro.MANEJADORES.pop("test.q3", None)


def test_q4_dos_stop_distintos_del_mismo_numero_en_paralelo_una_sola_exclusion(pg):  # noqa: F811
    _esc_whatsapp(pg)
    ids = [_entrante(pg, "STOP", "SMq4a"), _entrante(pg, "stop", "SMq4b")]
    barrera = threading.Barrier(2, timeout=15)

    def procesar(mid):
        def _f():
            with pg() as s:
                barrera.wait()
                servicio_entrante.procesar_entrante(s, {"mensaje_id": mid}, AHORA)
                s.commit()

        return _f

    _sin_errores(_en_hilos([procesar(i) for i in ids]))
    with pg() as s:
        exclusiones = s.scalars(select(Exclusion)).all()
        assert len(exclusiones) == 1 and exclusiones[0].canal == "whatsapp"
        assert {
            m.procesado_en is not None
            for m in s.scalars(select(Mensaje).where(Mensaje.direccion == "entrante"))
        } == {True}
        assert all(c.estado == "cerrada" for c in s.scalars(select(Conversacion)))
        assert (
            s.scalar(
                select(func.count())
                .select_from(Conversacion)
                .where(Conversacion.estado == "abierta")
            )
            == 0
        )


def test_q5_mismo_estado_de_entrega_en_paralelo_un_solo_evento(pg):  # noqa: F811
    from wa import crear_saliente

    _, camp, (a1, _) = _esc_whatsapp(pg)
    with pg() as db:
        cid = _conv(db, NUMERO, camp, dueno=Humano(a1))
        m = crear_saliente(
            db,
            db.get(Conversacion, cid),
            AHORA,
            estado="enviado",
            sid="SMq5",
            autor="agente",
            usuario_id=a1,
        )
        mid = m.id
    barrera = threading.Barrier(6, timeout=15)

    def webhook():
        with pg() as s:
            barrera.wait()
            servicio_estado.procesar_webhook(
                s,
                obtener_proveedor_whatsapp(),
                {"MessageSid": "SMq5", "MessageStatus": "delivered"},
                AHORA,
            )

    _sin_errores(_en_hilos([webhook] * 6))
    with pg() as s:
        assert s.scalar(select(func.count()).select_from(EventoMensaje)) == 1
        assert s.get(Mensaje, mid).estado == "entregado"


def test_q6_texto_del_agente_y_stop_del_cliente_simultaneos_no_envian_tras_la_baja(pg):  # noqa: F811
    from wa import crear_saliente  # noqa: F401

    _, camp, (a1, _) = _esc_whatsapp(pg)
    with pg() as db:
        cid = _conv(db, NUMERO, camp, dueno=Humano(a1))
    stop = _entrante(pg, "STOP", "SMq6")
    barrera = threading.Barrier(2, timeout=15)

    def agente():
        with pg() as s:
            barrera.wait()
            return servicio_envio.enviar_texto(
                s, s.get(Usuario, a1), cid, "TEXTO-DEL-AGENTE", uuid4(), AHORA
            )

    def cliente():
        with pg() as s:
            barrera.wait()
            servicio_entrante.procesar_entrante(s, {"mensaje_id": stop}, AHORA)
            s.commit()

    r = _en_hilos([agente, cliente])
    assert not isinstance(r[1], BaseException), r
    if isinstance(r[0], BaseException):
        assert isinstance(r[0], ErrorApp) and r[0].codigo in (
            "CONVERSACION_CERRADA",
            "CLIENTE_OPT_OUT",
        ), r
    # El worker procesa lo que quede.
    from app.trabajos.cola import ejecutar_pendientes

    with pg() as s:
        ejecutar_pendientes(s, AHORA + timedelta(seconds=5), 50)
    with pg() as s:
        enviados = [e["texto"] for e in obtener_proveedor_whatsapp().enviados]
        assert "TEXTO-DEL-AGENTE" not in enviados, enviados
        propios = s.scalars(select(Mensaje).where(Mensaje.autor == "agente")).all()
        assert all(m.estado in ("cancelado", "fallido") for m in propios), [
            m.estado for m in propios
        ]
        assert s.get(Conversacion, cid).estado == "cerrada"
        assert s.scalar(select(func.count()).select_from(Exclusion)) == 1
        assert (
            s.scalar(select(func.count()).select_from(Trabajo).where(Trabajo.estado == "fallido"))
            == 0
        )


def test_q7_tomar_y_asignar_simultaneos_dejan_un_unico_dueno(pg):  # noqa: F811
    _, camp, (a1, a2) = _esc_whatsapp(pg)
    with pg() as db:
        sup = _usuario(db, "supervisor", 9)
        sup_id = sup.id
        cid = _conv(db, NUMERO, camp)
    barrera = threading.Barrier(2, timeout=15)

    def tomar():
        with pg() as s:
            barrera.wait()
            return conversaciones.tomar(s, s.get(Usuario, a1), cid, AHORA)

    def asignar():
        with pg() as s:
            barrera.wait()
            return conversaciones.asignar(s, s.get(Usuario, sup_id), cid, a2, AHORA)

    r = _en_hilos([tomar, asignar])
    for x in r:
        if isinstance(x, BaseException):
            assert isinstance(x, ErrorApp) and x.codigo in (
                "CONVERSACION_ASIGNADA",
                "AGENTE_NO_DISPONIBLE",
            ), r
    with pg() as s:
        c = s.get(Conversacion, cid)
        assert c.atendida_por == "humano" and c.usuario_asignado_id in (a1, a2)
        assert (
            s.scalar(
                select(func.count())
                .select_from(ColaAtencion)
                .where(ColaAtencion.estado == "pendiente")
            )
            == 0
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ColaAtencion)
                .where(ColaAtencion.estado == "asignada")
            )
            == 1
        )
