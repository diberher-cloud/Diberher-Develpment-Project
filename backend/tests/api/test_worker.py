"""Worker (`python -m app.worker`), latido, healthcheck y `GET /supervision/trabajos`."""

import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from alembic import command
from alembic.config import Config
from app import worker
from app.modulos.auditoria.modelos import Auditoria
from app.trabajos import cola, registro
from app.trabajos.modelos import LatidoWorker, Trabajo

RAIZ = Path(__file__).parent.parent.parent
T0 = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


@pytest.fixture()
def manejadores():
    antes = dict(registro.MANEJADORES)
    registro.cargar_manejadores()
    vistos: list = []
    registro.MANEJADORES["test.ok"] = lambda db, p, ahora: vistos.append(p["n"])
    yield vistos
    registro.MANEJADORES.clear()
    registro.MANEJADORES.update(antes)


def trabajador(session_factory, ahora=T0):
    return worker.Trabajador(fabrica=session_factory, reloj=lambda: ahora, nombre="w-test-1")


def test_vuelta_registra_el_latido_programa_periodicos_y_ejecuta(session_factory, db, manejadores):
    for n in (1, 2, 3):
        cola.encolar(db, "test.ok", {"n": n}, ahora=T0)
    db.commit()
    w = trabajador(session_factory)
    assert w.vuelta() == 3
    assert manejadores == [1, 2, 3]
    db.expire_all()
    latido = db.get(LatidoWorker, "w-test-1")
    assert latido.ultimo_latido == T0 and latido.iniciado_en == T0 and latido.version
    tipos = {t.tipo for t in db.scalars(select(Trabajo).where(Trabajo.estado == "pendiente"))}
    assert tipos == {"conversaciones.cerrar_inactivas", "trabajos.purgar"}
    # Segunda vuelta más tarde: actualiza el latido sin duplicar la fila.
    w2 = trabajador(session_factory, T0 + timedelta(seconds=10))
    assert w2.vuelta() == 0
    db.expire_all()
    assert len(db.scalars(select(LatidoWorker)).all()) == 1
    assert db.get(LatidoWorker, "w-test-1").ultimo_latido == T0 + timedelta(seconds=10)
    assert db.get(LatidoWorker, "w-test-1").iniciado_en == T0


def test_el_lote_limita_cuantos_trabajos_toma_por_vuelta(
    session_factory, db, manejadores, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "worker_lote", 2)
    for n in range(5):
        cola.encolar(db, "test.ok", {"n": n}, ahora=T0)
    db.commit()
    w = trabajador(session_factory)
    assert w.vuelta() == 2 and w.vuelta() == 2 and w.vuelta() == 1


def test_sigterm_termina_el_trabajo_en_curso_y_devuelve_los_demas(session_factory, db, manejadores):
    w = trabajador(session_factory)
    for n in (1, 2, 3):
        cola.encolar(db, "test.ok", {"n": n}, ahora=T0)
    db.commit()

    def pide_parar(_db, payload, _ahora):
        manejadores.append(payload["n"])
        w.parar.set()  # llega SIGTERM durante el primer trabajo

    registro.MANEJADORES["test.ok"] = pide_parar
    assert w.vuelta() == 1
    assert manejadores == [1]  # terminó el trabajo en curso
    db.expire_all()
    estados = {
        t.payload["n"]: (t.estado, t.intentos)
        for t in db.scalars(select(Trabajo).where(Trabajo.tipo == "test.ok"))
    }
    assert estados == {1: ("completado", 1), 2: ("pendiente", 0), 3: ("pendiente", 0)}


def test_healthcheck(session_factory, db):
    assert worker.healthcheck(lambda: T0, session_factory) == 1  # sin latidos
    trabajador(session_factory).vuelta()
    assert worker.healthcheck(lambda: T0 + timedelta(seconds=59), session_factory) == 0
    assert worker.healthcheck(lambda: T0 + timedelta(seconds=61), session_factory) == 1


def test_healthcheck_con_la_bd_caida_devuelve_1():
    def rota():
        raise RuntimeError("sin BD")

    assert worker.healthcheck(lambda: T0, rota) == 1


def test_trabajo_fallido_deja_auditoria_y_evento_sin_texto(session_factory, db, manejadores):
    def malo(_db, _p, _a):
        raise registro.ErrorTrabajo("63003", transitorio=False)

    registro.MANEJADORES["test.ok"] = malo
    cola.encolar(db, "test.ok", {"n": 1}, ahora=T0)
    db.commit()
    trabajador(session_factory).vuelta()
    db.expire_all()
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "trabajo.fallido"))
    assert aud.detalle["codigo"] == "63003" and aud.detalle["tipo"] == "test.ok"


# ---- Supervisión -------------------------------------------------------------------------------
def test_supervision_de_trabajos(
    client, db, session_factory, h_supervisor, h_agente, reloj, manejadores
):
    ahora = reloj()
    w = trabajador(session_factory, ahora)
    w.vuelta()
    otro = LatidoWorker(
        trabajador="w-viejo",
        iniciado_en=ahora - timedelta(hours=1),
        ultimo_latido=ahora - timedelta(seconds=120),
        version="x",
    )
    db.add(otro)
    cola.encolar(db, "test.ok", {"n": 1}, ahora=ahora, disponible_desde=ahora + timedelta(hours=1))
    viejo = cola.encolar(db, "test.ok", {"n": 2}, ahora=ahora)
    reciente = cola.encolar(db, "test.ok", {"n": 3}, ahora=ahora)
    for t, delta in ((viejo, timedelta(hours=25)), (reciente, timedelta(hours=1))):
        t.estado, t.ultimo_error, t.intentos, t.actualizado_en = (
            "fallido",
            "ErrorTrabajo:63003",
            1,
            ahora - delta,
        )
    db.commit()
    r = client.get("/api/v1/supervision/trabajos", headers=h_supervisor)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {(t["trabajador"], t["activo"]) for t in cuerpo["trabajadores"]} == {
        ("w-test-1", True),
        ("w-viejo", False),
    }
    assert {"tipo": "test.ok", "estado": "pendiente", "total": 1} in cuerpo["por_estado"]
    assert {"tipo": "test.ok", "estado": "fallido", "total": 2} in cuerpo["por_estado"]
    assert [f["id"] for f in cuerpo["fallidos_recientes"]] == [reciente.id]  # solo las últimas 24 h
    assert cuerpo["fallidos_recientes"][0] == {
        "id": reciente.id, "tipo": "test.ok", "ultimo_error": "ErrorTrabajo:63003", "intentos": 1,
        "actualizado_en": "2026-10-23T14:15:00Z",
    }  # fmt: skip
    assert client.get("/api/v1/supervision/trabajos", headers=h_agente).status_code == 403
    assert client.get("/api/v1/supervision/trabajos").status_code == 401


def test_supervision_limita_a_20_fallidos(client, db, h_admin, reloj):
    for n in range(25):
        t = cola.encolar(db, "test.ok", {"n": n}, ahora=reloj())
        t.estado, t.actualizado_en = "fallido", reloj() - timedelta(minutes=n)
    db.commit()
    assert (
        len(
            client.get("/api/v1/supervision/trabajos", headers=h_admin).json()["fallidos_recientes"]
        )
        == 20
    )


# ---- Proceso real ------------------------------------------------------------------------------
def _entorno(ruta):
    return {
        **os.environ, "ENTORNO": "test", "DATABASE_URL": f"sqlite:///{ruta}", "BCRYPT_COSTE": "4",
        "WORKER_INTERVALO_SEGUNDOS": "0.1",
    }  # fmt: skip


def _migrar(ruta):
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{ruta}")
    command.upgrade(cfg, "head")


def test_proceso_real_latido_healthcheck_y_sigterm_con_salida_0(tmp_path):
    ruta = tmp_path / "w.db"
    _migrar(ruta)
    env = _entorno(ruta)
    # Sin latido el healthcheck falla.
    sin = subprocess.run(
        [sys.executable, "-m", "app.worker", "--healthcheck"], cwd=RAIZ, env=env, timeout=60
    )
    assert sin.returncode == 1
    proc = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=RAIZ, env=env)
    try:
        for _ in range(100):
            with sqlite3.connect(ruta) as con:
                if con.execute("select count(*) from latidos_worker").fetchone()[0]:
                    break
            time.sleep(0.2)
        else:
            pytest.fail("el worker no registró latido")
        con_latido = subprocess.run(
            [sys.executable, "-m", "app.worker", "--healthcheck"], cwd=RAIZ, env=env, timeout=60
        )
        assert con_latido.returncode == 0
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    with sqlite3.connect(ruta) as con:
        periodicos = {
            f[0] for f in con.execute("select tipo from trabajos where estado='pendiente'")
        }
    assert periodicos == {"conversaciones.cerrar_inactivas", "trabajos.purgar"}


def test_proceso_real_ejecuta_un_trabajo_encolado(tmp_path):
    ruta = tmp_path / "w2.db"
    _migrar(ruta)
    ahora = (datetime.now(UTC) - timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S.%f")
    with sqlite3.connect(ruta) as con:
        con.execute(
            "insert into trabajos(tipo,payload,estado,intentos,max_intentos,"
            "disponible_desde,creado_en,actualizado_en)"
            " values('trabajos.purgar','{}','pendiente',0,5,?,?,?)",
            (ahora, ahora, ahora),
        )
    proc = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=RAIZ, env=_entorno(ruta))
    try:
        for _ in range(100):
            with sqlite3.connect(ruta) as con:
                estado = con.execute(
                    "select estado from trabajos where tipo='trabajos.purgar' order by id limit 1"
                ).fetchone()
            if estado and estado[0] == "completado":
                break
            time.sleep(0.2)
        else:
            pytest.fail("el trabajo no se completó")
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0
