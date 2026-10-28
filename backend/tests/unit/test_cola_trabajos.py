"""Cola de trabajos: deduplicación, toma, reintentos con backoff, recuperación y periódicos."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.modulos.auditoria.modelos import Auditoria
from app.tiempo_real import bus
from app.trabajos import cola, periodicos, registro
from app.trabajos.modelos import Trabajo
from app.trabajos.registro import ErrorTrabajo, ReprogramarTrabajo

T0 = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


@pytest.fixture()
def manejadores():
    """Manejadores de prueba; se restauran al terminar."""
    antes = dict(registro.MANEJADORES)
    llamadas: list = []
    registro.cargar_manejadores()
    registro.MANEJADORES["test.ok"] = lambda db, payload, ahora: llamadas.append(
        ("ok", payload["n"])
    )

    def _transitorio(db, payload, ahora):
        llamadas.append(("transitorio", ahora))
        raise ErrorTrabajo("TEMPORAL", transitorio=True)

    def _permanente(db, payload, ahora):
        raise ErrorTrabajo("MALO", transitorio=False)

    def _inesperado(db, payload, ahora):
        raise ValueError("dato personal: 3001234567")

    def _reprogramar(db, payload, ahora):
        raise ReprogramarTrabajo(ahora + timedelta(hours=1))

    registro.MANEJADORES.update(
        {
            "test.transitorio": _transitorio,
            "test.permanente": _permanente,
            "test.inesperado": _inesperado,
            "test.reprogramar": _reprogramar,
        }
    )
    yield llamadas
    registro.MANEJADORES.clear()
    registro.MANEJADORES.update(antes)


def encolar(db, tipo, payload=None, **kw):
    t = cola.encolar(db, tipo, payload or {}, ahora=T0, **kw)
    db.commit()
    return t


def test_clave_unica_deduplica_solo_mientras_esta_pendiente(db):
    a = encolar(db, "test.ok", {"n": 1}, clave_unica="k")
    b = encolar(db, "test.ok", {"n": 2}, clave_unica="k")
    assert a.id == b.id and len(db.scalars(select(Trabajo)).all()) == 1
    (tomado,) = cola.tomar(db, "w1", T0, 10)
    assert tomado.id == a.id and tomado.clave_unica is None  # se libera al tomarlo
    c = encolar(db, "test.ok", {"n": 3}, clave_unica="k")
    assert c.id != a.id


def test_tomar_respeta_disponible_desde_y_orden(db):
    futuro = encolar(db, "test.ok", {"n": 9}, disponible_desde=T0 + timedelta(minutes=5))
    segundo = encolar(db, "test.ok", {"n": 2}, disponible_desde=T0 - timedelta(minutes=1))
    primero = encolar(db, "test.ok", {"n": 1}, disponible_desde=T0 - timedelta(minutes=2))
    tomados = cola.tomar(db, "w1", T0, 10)
    assert [t.id for t in tomados] == [primero.id, segundo.id]
    assert all(t.estado == "en_proceso" and t.intentos == 1 for t in tomados)
    assert tomados[0].bloqueado_por == "w1" and tomados[0].bloqueado_hasta > T0
    assert db.get(Trabajo, futuro.id).estado == "pendiente"


def test_ejecutar_pendientes_ejecuta_en_orden(db, manejadores):
    for n in (3, 1, 2):
        encolar(db, "test.ok", {"n": n}, disponible_desde=T0 - timedelta(minutes=10 - n))
    assert cola.ejecutar_pendientes(db, T0) == 3
    assert [n for _, n in manejadores] == [1, 2, 3]
    assert {t.estado for t in db.scalars(select(Trabajo))} == {"completado"}


def test_backoff_exacto_y_fallido_al_agotar_intentos(db, manejadores):
    t = encolar(db, "test.transitorio", max_intentos=4)
    esperados = [5, 10, 20]
    ahora = T0
    for i, segundos in enumerate(esperados, start=1):
        assert cola.ejecutar_pendientes(db, ahora) == 1
        db.expire_all()
        t = db.get(Trabajo, t.id)
        assert (t.estado, t.intentos) == ("pendiente", i)
        assert t.disponible_desde == ahora + timedelta(seconds=segundos)
        assert t.ultimo_error == "ErrorTrabajo:TEMPORAL"
        assert cola.ejecutar_pendientes(db, ahora) == 0  # aún no toca
        ahora = t.disponible_desde
    assert cola.ejecutar_pendientes(db, ahora) == 1
    db.expire_all()
    t = db.get(Trabajo, t.id)
    assert (t.estado, t.intentos) == ("fallido", 4)
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "trabajo.fallido"))
    assert aud.detalle == {"trabajo_id": t.id, "tipo": "test.transitorio", "codigo": "TEMPORAL"}


def test_backoff_maximo_de_600_segundos():
    assert [cola.backoff(n).total_seconds() for n in (1, 2, 3, 4, 7, 8, 9, 20)] == [
        5, 10, 20, 40, 320, 600, 600, 600,
    ]  # fmt: skip


def test_error_permanente_falla_de_inmediato_y_publica_evento(db, manejadores):
    recibidos: list = []
    el_bus = bus.BusMemoria()
    el_bus.suscribir(recibidos.append)
    anterior = bus._bus
    bus.establecer_bus(el_bus)
    try:
        t = encolar(db, "test.permanente")
        assert cola.ejecutar_pendientes(db, T0) == 1
    finally:
        bus.establecer_bus(anterior)
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "fallido"
    assert [e["tipo"] for e in recibidos] == ["trabajo.fallido"]
    assert recibidos[0]["datos"] == {
        "trabajo_id": t.id,
        "tipo": "test.permanente",
        "codigo": "MALO",
    }


def test_excepcion_inesperada_cuenta_como_transitoria_y_no_guarda_su_texto(db, manejadores):
    t = encolar(db, "test.inesperado")
    cola.ejecutar_pendientes(db, T0)
    db.expire_all()
    t = db.get(Trabajo, t.id)
    assert t.estado == "pendiente" and t.ultimo_error == "ValueError:INESPERADO"
    assert "3001234567" not in (t.ultimo_error or "")


def test_tipo_desconocido_falla(db, manejadores):
    t = encolar(db, "no.existe")
    cola.ejecutar_pendientes(db, T0)
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "fallido"


def test_reprogramar_no_cuenta_el_intento(db, manejadores):
    t = encolar(db, "test.reprogramar")
    cola.ejecutar_pendientes(db, T0)
    db.expire_all()
    t = db.get(Trabajo, t.id)
    assert (t.estado, t.intentos, t.disponible_desde) == ("pendiente", 0, T0 + timedelta(hours=1))


def test_recupera_bloqueo_caducado(db):
    t = encolar(db, "test.ok", {"n": 1})
    cola.tomar(db, "worker-muerto", T0, 1)
    assert cola.tomar(db, "w2", T0 + timedelta(seconds=10), 5) == []  # el bloqueo sigue vigente
    (recuperado,) = cola.tomar(db, "w2", T0 + timedelta(seconds=301), 5)
    assert recuperado.id == t.id and recuperado.intentos == 2 and recuperado.bloqueado_por == "w2"


def test_bloqueo_caducado_mas_veces_de_las_permitidas_falla(db):
    t = encolar(db, "test.ok", {"n": 1}, max_intentos=2)
    ahora = T0
    for _ in range(2):
        assert cola.tomar(db, "w", ahora, 1)
        ahora += timedelta(seconds=400)
    assert cola.tomar(db, "w", ahora, 1) == []
    assert db.get(Trabajo, t.id).estado == "fallido"


def test_periodicos_no_se_duplican(db, session_factory):
    assert periodicos.programar(db, T0) == len(periodicos.PERIODICOS)
    db.commit()
    assert periodicos.programar(db, T0 + timedelta(seconds=30)) == 0
    filas = {t.tipo: t for t in db.scalars(select(Trabajo))}
    assert filas["conversaciones.cerrar_inactivas"].disponible_desde == T0 + timedelta(seconds=300)
    assert filas["trabajos.purgar"].disponible_desde == T0 + timedelta(hours=24)
    # Tomado el periódico (en proceso) tampoco se duplica; al terminar se programa el siguiente.
    (tomado,) = cola.tomar(db, "w", T0 + timedelta(seconds=301), 5)
    assert periodicos.programar(db, T0 + timedelta(seconds=302)) == 0
    cola.ejecutar(session_factory, tomado.id, lambda: T0 + timedelta(seconds=303))
    db.expire_all()
    assert periodicos.programar(db, T0 + timedelta(seconds=304)) == 1


def test_purgar_borra_terminados_antiguos(db):
    viejo = encolar(db, "test.ok", {"n": 1})
    reciente = encolar(db, "test.ok", {"n": 2})
    fallido_viejo = encolar(db, "test.ok", {"n": 3})
    for t, estado, antiguedad in (
        (viejo, "completado", 8),
        (reciente, "completado", 1),
        (fallido_viejo, "fallido", 8),
    ):
        t.estado, t.actualizado_en = estado, T0 - timedelta(days=antiguedad)
    db.commit()
    from app.trabajos.mantenimiento import purgar

    purgar(db, {}, T0)
    db.commit()
    restantes = {t.id for t in db.scalars(select(Trabajo))}
    assert restantes == {reciente.id, fallido_viejo.id}  # los fallidos se conservan 30 días


def test_payloads_solo_ids(db):
    """Ningún trabajo encolado por 2B lleva texto ni números (se verifica en los tests de API)."""
    t = encolar(db, "test.ok", {"mensaje_id": 5})
    assert set(t.payload) == {"mensaje_id"}


def test_ejecutar_con_sesiones_independientes(db, session_factory, manejadores):
    t = encolar(db, "test.ok", {"n": 7})
    (tomado,) = cola.tomar(db, "w", T0, 1)
    cola.ejecutar(session_factory, tomado.id, lambda: T0)
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "completado"
    assert manejadores == [("ok", 7)]
    assert isinstance(session_factory, sessionmaker)
