"""Concurrencia real sobre PostgreSQL (marcador `postgres`, requiere TEST_DATABASE_URL).

El esquema se crea con las migraciones reales (`alembic upgrade head`) y se destruye al final.
Cada hilo usa su propia sesión/conexión. Las carreras se fuerzan con una `Barrier` colocada
justo después de las comprobaciones previas y antes de la escritura, de modo que ambos hilos
llegan a la escritura con la misma vista (obsoleta) de los datos.
"""

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from escenario import Escenario, cab, telefono_de
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from app.db import crear_engine, get_db
from app.errores import ErrorApp
from app.main import app
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola import servicio as consola
from app.modulos.consola.modelos import (
    EstadoAgente,
    HistorialEstadoAgente,
    PromesaPago,
    Tipificacion,
)
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.telefonia.modelos import EventoLlamada, Llamada
from app.modulos.usuarios.modelos import Usuario
from app.reloj import get_reloj
from app.seguridad import hash_password

pytestmark = pytest.mark.postgres
RAIZ = Path(__file__).parent.parent.parent
AHORA = datetime(2026, 10, 23, 15, 15, tzinfo=UTC)  # viernes 10:15 Bogotá


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

    def _get_db() -> Iterator[Session]:
        with fabrica() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_reloj] = lambda: (lambda: AHORA)
    try:
        yield fabrica
    finally:
        app.dependency_overrides.clear()
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
    """Ejecuta cada función en su hilo; devuelve los resultados o las excepciones en orden."""
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
        h.join(30)
        assert not h.is_alive(), "hilo colgado (posible interbloqueo)"
    return salidas


def test_dos_agentes_toman_el_mismo_registro_gana_exactamente_uno(pg, monkeypatch):
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        a1, a2 = _usuario(db, "agente", 1), _usuario(db, "agente", 2)
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, a1)
        esc.asignar(campana, a2)
        cc = esc.registro(campana)
        a1_id, a2_id, cc_id = a1.id, a2.id, cc.id

    barrera = threading.Barrier(2, timeout=10)
    original = consola._reservar_atomico

    def con_barrera(*args, **kw):
        barrera.wait()  # ambos ya validaron contra un registro libre
        return original(*args, **kw)

    monkeypatch.setattr(consola, "_reservar_atomico", con_barrera)

    def tomar(uid):
        def _f():
            with pg() as s:
                return consola.tomar(s, s.get(Usuario, uid), cc_id, AHORA)

        return _f

    r = _en_hilos([tomar(a1_id), tomar(a2_id)])
    ganadores = [x for x in r if not isinstance(x, BaseException)]
    perdedores = [x for x in r if isinstance(x, BaseException)]
    assert len(ganadores) == 1, r
    assert len(perdedores) == 1 and isinstance(perdedores[0], ErrorApp), r
    assert perdedores[0].status == 409 and perdedores[0].codigo == "REGISTRO_RESERVADO"
    with pg() as s:
        fila = s.get(CampanaCliente, cc_id)
        ganador = a1_id if not isinstance(r[0], BaseException) else a2_id
        assert (fila.estado, fila.reservado_por) == ("en_gestion", ganador)


def test_tomar_concurrente_por_api_muchas_rondas_un_solo_ganador(pg):
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agentes = [_usuario(db, "agente", i) for i in range(1, 5)]
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        for a in agentes:
            esc.asignar(campana, a)
        registros = [esc.registro(campana).id for _ in range(15)]
        cabs = [cab(a) for a in agentes]

    def ronda(cc_id):
        barrera = threading.Barrier(len(cabs), timeout=10)

        def intento(h):
            def _f():
                with TestClient(app) as c:
                    barrera.wait()
                    return c.post(f"/api/v1/consola/registros/{cc_id}/tomar", headers=h).status_code

            return _f

        return _en_hilos([intento(h) for h in cabs])

    for cc_id in registros:
        codigos = ronda(cc_id)
        assert sorted(codigos) == [200, 409, 409, 409], codigos
    # Una reserva por agente: nadie acabó con dos registros reservados.
    with pg() as s:
        por_agente = s.execute(
            select(CampanaCliente.reservado_por, func.count())
            .where(CampanaCliente.reservado_por.is_not(None))
            .group_by(CampanaCliente.reservado_por)
        ).all()
        assert all(n == 1 for _, n in por_agente), por_agente


def _llamada_terminada_en_pg(pg, resultado="completed"):
    """Escenario con una llamada contestada y finalizada, lista para tipificar."""
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agente = _usuario(db, "agente", 1)
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, agente)
        cc = esc.registro(campana)
        esc.estado(agente, "disponible", AHORA)
        esc.reservar(cc, agente, AHORA)
        h = cab(agente)
        tel_id = telefono_de(db, cc).id
        cc_id, agente_id = cc.id, agente.id
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/telefonia/simulacion/llamadas",
            json={"campana_cliente_id": cc_id, "telefono_id": tel_id},
            headers=h,
        )
        assert r.status_code == 200 and r.json()["permitida"], r.text
        lid = r.json()["llamada_id"]
        c.post(
            f"/api/v1/telefonia/simulacion/llamadas/{lid}/eventos",
            json={"evento": "contestada"},
            headers=h,
        )
        c.post(
            f"/api/v1/telefonia/simulacion/llamadas/{lid}/eventos",
            json={"evento": "finalizada", "resultado": resultado, "duracion_segundos": 30},
            headers=h,
        )
    return h, lid, cc_id, agente_id


def test_flujo_completo_de_simulacion_y_tipificacion_sobre_postgres(pg):
    h, lid, cc_id, agente_id = _llamada_terminada_en_pg(pg)
    with TestClient(app) as c:
        r = c.post(
            "/api/v1/consola/tipificaciones",
            json={
                "llamada_id": lid,
                "resultado": "promesa_pago",
                "promesa": {"monto": "250000.50", "fecha_pago": "2026-10-30"},
            },
            headers=h,
        )
    assert r.status_code == 201, r.text
    assert r.json()["promesa"]["monto"] == "250000.50"
    with pg() as s:
        assert s.get(CampanaCliente, cc_id).estado == "gestionado"
        assert s.get(EstadoAgente, agente_id).estado == "disponible"


def test_doble_tipificacion_concurrente_exactamente_una_gana(pg, monkeypatch):
    h, lid, cc_id, agente_id = _llamada_terminada_en_pg(pg)
    from app.modulos.consola import tipificacion as mod
    from app.modulos.cumplimiento import servicio as cumplimiento_servicio

    barrera = threading.Barrier(2, timeout=1.5)
    original = cumplimiento_servicio.cargar_politica

    def con_barrera(*a, **kw):
        # Se llama tras la comprobación de "sin tipificación previa". Desde la revisión 2 el
        # segundo hilo espera antes (FOR UPDATE de estados_agente/clientes), así que la barrera
        # es oportunista: si se rompe por tiempo, ambos siguen y el resultado no cambia.
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return original(*a, **kw)

    monkeypatch.setattr(mod.cumplimiento, "cargar_politica", con_barrera)
    cuerpo = {
        "llamada_id": lid,
        "resultado": "promesa_pago",
        "promesa": {"monto": "1000.00", "fecha_pago": "2026-10-30"},
    }

    def disparar():
        with TestClient(app) as c:
            r = c.post("/api/v1/consola/tipificaciones", json=cuerpo, headers=h)
            return r.status_code, r.json()

    r = _en_hilos([disparar, disparar])
    codigos = sorted(x[0] for x in r)
    assert codigos == [201, 409], r
    perdedor = next(x for x in r if x[0] == 409)[1]
    assert perdedor["error"]["codigo"] == "LLAMADA_YA_TIPIFICADA"
    with pg() as s:
        assert s.scalar(select(func.count()).select_from(Tipificacion)) == 1
        assert s.scalar(select(func.count()).select_from(PromesaPago)) == 1
        cc = s.get(CampanaCliente, cc_id)
        assert cc.intentos == 1 and cc.estado == "gestionado"  # el intento se cuenta una vez
        assert s.get(EstadoAgente, agente_id).estado == "disponible"


def test_primera_escritura_de_estado_concurrente_no_da_500(pg):
    with pg() as db:
        agente = _usuario(db, "agente", 1)
        h = cab(agente)
    barrera = threading.Barrier(2, timeout=10)

    def disparar():
        with TestClient(app) as c:
            barrera.wait()
            return c.put("/api/v1/consola/estado", json={"estado": "disponible"}, headers=h)

    r = _en_hilos([disparar, disparar])
    codigos = sorted(x.status_code for x in r)
    assert all(c in (200, 409) for c in codigos) and 200 in codigos, [x.text for x in r]
    for x in r:
        if x.status_code == 409:
            assert x.json()["error"]["codigo"] == "ESTADO_CONCURRENTE"
    with pg() as s:
        assert s.get(EstadoAgente, agente.id).estado == "disponible"
        abiertas = s.scalar(
            select(func.count())
            .select_from(HistorialEstadoAgente)
            .where(HistorialEstadoAgente.fin.is_(None))
        )
        assert abiertas == 1


def test_llamar_dos_veces_con_el_mismo_callsid_crea_una_sola_llamada(pg):
    """Idempotencia por CallSid bajo concurrencia real (UNIQUE call_sid)."""
    from conftest import firma_independiente

    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agente = _usuario(db, "agente", 1)
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, agente)
        cc = esc.registro(campana)
        esc.estado(agente, "disponible", AHORA)
        esc.reservar(cc, agente, AHORA)
        params = {
            "CallSid": "CA-carrera",
            "From": f"client:agente_{agente.id}",
            "AccountSid": "ACx",
            "campana_cliente_id": str(cc.id),
            "telefono_id": str(telefono_de(db, cc).id),
        }
    ruta = "/api/v1/telefonia/twiml/saliente"
    firma = firma_independiente("https://pruebas.example.com" + ruta, params)

    def disparar():
        with TestClient(app) as c:
            return c.post(ruta, data=params, headers={"X-Twilio-Signature": firma})

    r = _en_hilos([disparar, disparar])
    assert [x.status_code for x in r] == [200, 200], r
    assert r[0].text == r[1].text and "+573001234567" in r[0].text
    with pg() as s:
        assert s.scalar(select(func.count()).select_from(Llamada)) == 1
        assert s.scalar(select(func.count()).select_from(IntentoContacto)) == 1


def test_webhook_duplicado_concurrente_guarda_un_solo_evento(pg):
    from conftest import firma_independiente

    h, lid, cc_id, agente_id = _llamada_terminada_en_pg(pg)  # solo para tener una llamada
    with pg() as s:
        sid = s.get(Llamada, lid).call_sid
    params = {"CallSid": "CAcli1", "CallStatus": "ringing", "SequenceNumber": "1"}
    consulta = f"llamada_id={lid}"
    ruta = "/api/v1/telefonia/webhooks/estado"
    url = "https://pruebas.example.com" + ruta + "?" + consulta
    firma = firma_independiente(url, params)
    assert sid

    def disparar():
        with TestClient(app) as c:
            return c.post(
                ruta + "?" + consulta, data=params, headers={"X-Twilio-Signature": firma}
            ).status_code

    r = _en_hilos([disparar, disparar, disparar])
    assert r == [204, 204, 204]
    with pg() as s:
        n = s.scalar(
            select(func.count())
            .select_from(EventoLlamada)
            .where(EventoLlamada.estado_proveedor == "ringing")
        )
        assert n == 1


def test_finalizacion_concurrente_por_dos_senales_distintas_ocurre_una_vez(pg, monkeypatch):
    """`dial-terminado` y el estado terminal de la pierna llegan a la vez: una sola finalización."""
    from conftest import firma_independiente

    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agente = _usuario(db, "agente", 1)
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, agente)
        cc = esc.registro(campana)
        esc.estado(agente, "disponible", AHORA)
        esc.reservar(cc, agente, AHORA)
        h = cab(agente)
        tel = telefono_de(db, cc).id
        cc_id = cc.id
    with TestClient(app) as c:
        lid = c.post(
            "/api/v1/telefonia/simulacion/llamadas",
            json={"campana_cliente_id": cc_id, "telefono_id": tel},
            headers=h,
        ).json()["llamada_id"]
        c.post(
            f"/api/v1/telefonia/simulacion/llamadas/{lid}/eventos",
            json={"evento": "contestada"},
            headers=h,
        )
    from app.modulos.telefonia import servicio as tel_servicio

    # Desde la revisión 2 (B1) los webhooks de una misma llamada se serializan con FOR UPDATE al
    # cargarla, así que el segundo hilo no llega a `finalizar` mientras el primero no confirma:
    # la barrera es oportunista (si se rompe por tiempo, ambos siguen) y el resultado esperado
    # (una sola finalización) no cambia.
    barrera = threading.Barrier(2, timeout=1.5)
    original = tel_servicio.finalizar

    def con_barrera(*a, **kw):
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return original(*a, **kw)

    monkeypatch.setattr(tel_servicio, "finalizar", con_barrera)

    def firmado(ruta, params, consulta):
        url = "https://pruebas.example.com" + ruta + "?" + consulta
        return {
            "url": ruta + "?" + consulta,
            "data": params,
            "headers": {"X-Twilio-Signature": firma_independiente(url, params)},
        }

    p_dial = firmado(
        "/api/v1/telefonia/twiml/dial-terminado",
        {"CallSid": "CAsimX", "DialCallStatus": "completed", "DialCallDuration": "30"},
        f"llamada_id={lid}",
    )
    p_est = firmado(
        "/api/v1/telefonia/webhooks/estado",
        {"CallSid": "CAcli9", "CallStatus": "completed", "SequenceNumber": "4"},
        f"llamada_id={lid}",
    )

    def disparar(p):
        def _f():
            with TestClient(app) as c:
                return c.post(p["url"], data=p["data"], headers=p["headers"]).status_code

        return _f

    r = _en_hilos([disparar(p_dial), disparar(p_est)])
    assert sorted(r) == [200, 204]
    with pg() as s:
        llamada = s.get(Llamada, lid)
        assert llamada.estado == "completada"
        # Una sola transición a `tipificando` en el historial del agente.
        n = s.scalar(
            select(func.count())
            .select_from(HistorialEstadoAgente)
            .where(
                HistorialEstadoAgente.estado == "tipificando",
                HistorialEstadoAgente.usuario_id == llamada.usuario_id,
            )
        )
        assert n == 1, f"finalización duplicada: {n} entradas 'tipificando' en el historial"


def test_asignaciones_concurrentes_de_agentes_no_dan_500(pg):
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agentes = [_usuario(db, "agente", i) for i in range(1, 4)]
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, agentes[0])
        ids = [a.id for a in agentes]
        h = cab(admin)
        cid = campana.id
    barrera = threading.Barrier(3, timeout=10)

    def poner(lista):
        def _f():
            with TestClient(app) as c:
                barrera.wait()
                return c.put(
                    f"/api/v1/campanas/{cid}/agentes", json={"usuario_ids": lista}, headers=h
                )

        return _f

    # Todos añaden a los agentes 2 y 3 y quitan al 1 a la vez.
    r = _en_hilos([poner(ids[1:]), poner(ids[1:]), poner([ids[2], ids[1]])])
    for x in r:
        assert x.status_code in (200, 409), x.text
        if x.status_code == 409:
            assert x.json()["error"]["codigo"] == "ASIGNACION_CONCURRENTE"
    assert any(x.status_code == 200 for x in r)
    with pg() as s:
        from app.modulos.campanas.modelos import CampanaAgente

        asignados = sorted(s.scalars(select(CampanaAgente.usuario_id)))
        assert asignados == sorted(ids[1:])


def test_tomar_y_quitar_asignacion_a_la_vez_no_deja_reserva_de_un_agente_desasignado(
    pg, monkeypatch
):
    """Intercalación actual: `tomar` valida y toma `FOR SHARE` sobre la asignación; el PUT del
    supervisor espera a que `tomar` confirme y entonces desasigna y libera la reserva recién hecha.
    Invariante: nunca queda reserva vigente de un agente desasignado."""
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agente = _usuario(db, "agente", 1)
        esc = Escenario(db, admin.id)
        campana = esc.campana()
        esc.asignar(campana, agente)
        cc = esc.registro(campana)
        ha, hg = cab(admin), cab(agente)
        cid, cc_id, uid = campana.id, cc.id, agente.id

    validado = threading.Event()
    quitado = threading.Event()
    original = consola._reservar_atomico

    def reservar_tras_quitar(*args, **kw):
        validado.set()  # ya pasó la comprobación de asignación
        # Desde la revisión 2 `tomar` ya tiene FOR SHARE sobre la asignación, así que el
        # supervisor espera a que `tomar` confirme (no se interbloquean): se espera un momento y
        # se continúa; lo que se comprueba al final es que no queda reserva de un desasignado.
        quitado.wait(0.5)
        return original(*args, **kw)

    monkeypatch.setattr(consola, "_reservar_atomico", reservar_tras_quitar)

    def quitar():
        assert validado.wait(10)
        with TestClient(app) as c:
            r = c.put(f"/api/v1/campanas/{cid}/agentes", json={"usuario_ids": []}, headers=ha)
        quitado.set()
        return r

    def tomar():
        with TestClient(app) as c:
            return c.post(f"/api/v1/consola/registros/{cc_id}/tomar", headers=hg)

    r = _en_hilos([quitar, tomar])
    assert all(x.status_code < 500 for x in r), [x.text for x in r]
    with pg() as s:
        from app.modulos.campanas.modelos import CampanaAgente

        fila = s.get(CampanaCliente, cc_id)
        asignado = s.scalar(select(CampanaAgente.id).where(CampanaAgente.usuario_id == uid))
        assert asignado is None  # el supervisor lo desasignó
        assert fila.reservado_por != uid, "reserva vigente de un agente que ya no está asignado"
