import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect
from voz import contexto

from app.config import get_settings
from app.modulos.consola.modelos import EstadoAgente
from app.seguridad import crear_token
from app.tiempo_real import bus

W = "/api/v1/ws"
K = "/api/v1/consola"


def url(usuario, **kw) -> str:
    token, _ = crear_token(usuario.id, usuario.rol, **kw)
    return f"{W}?token={token}"


def cab_de(usuario):
    token, _ = crear_token(usuario.id, usuario.rol)
    return {"Authorization": f"Bearer {token}"}


def recibir(ws, tipo=None):
    ev = ws.receive_json()
    if tipo is not None:
        assert ev["tipo"] == tipo, ev
    return ev


def test_token_invalido_o_ausente_cierra_con_4401(client, crear_usuario):
    for ruta in (W, f"{W}?token=basura", f"{W}?token="):
        with client.websocket_connect(ruta) as ws, pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401


def test_token_expirado_y_usuario_inactivo_4401(client, crear_usuario):
    agente = crear_usuario("agente")
    vencido = url(agente, ahora=datetime.now(UTC) - timedelta(days=2))
    with client.websocket_connect(vencido) as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_json()
    assert e.value.code == 4401
    inactivo = crear_usuario("agente", activo=False)
    with client.websocket_connect(url(inactivo)) as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_json()
    assert e.value.code == 4401


def test_conexion_lista_y_ping_pong(client, crear_usuario):
    agente = crear_usuario("agente")
    with client.websocket_connect(url(agente)) as ws:
        ev = recibir(ws, "conexion.lista")
        assert ev["datos"] == {"usuario_id": agente.id, "rol": "agente"}
        assert ev["emitido_en"].endswith("Z")
        ws.send_json({"tipo": "ping"})
        pong = recibir(ws, "pong")
        assert pong["datos"] == {}
        ws.send_text("basura")  # mensajes desconocidos se ignoran
        ws.send_json({"tipo": "otra-cosa"})
        ws.send_json({"tipo": "ping"})
        recibir(ws, "pong")


def test_el_token_vence_estando_conectado(client, crear_usuario, monkeypatch):
    agente = crear_usuario("agente")
    ahora = (
        datetime.now(UTC)
        - timedelta(minutes=get_settings().jwt_expiracion_minutos)
        + timedelta(seconds=1)
    )
    with client.websocket_connect(url(agente, ahora=ahora)) as ws:
        recibir(ws, "conexion.lista")
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401


def test_reparto_por_rol(client, crear_usuario):
    a1, a2 = crear_usuario("agente"), crear_usuario("agente")
    sup = crear_usuario("supervisor")
    with (
        client.websocket_connect(url(a1)) as w1,
        client.websocket_connect(url(a2)) as w2,
        client.websocket_connect(url(sup)) as ws,
    ):
        for w in (w1, w2, ws):
            recibir(w, "conexion.lista")
        # a2 cambia de estado: lo ven a2 y el supervisor, no a1
        r = client.put(f"{K}/estado", json={"estado": "disponible"}, headers=cab_de(a2))
        assert r.status_code == 200
        ev = recibir(w2, "agente.estado")
        assert ev["datos"]["usuario_id"] == a2.id and ev["datos"]["estado"] == "disponible"
        assert recibir(ws, "agente.estado")["datos"] == ev["datos"]
        # a1 cambia: el primer evento que ve a1 es el suyo (nada de a2 se le coló antes)
        client.put(
            f"{K}/estado", json={"estado": "pausa", "motivo_pausa": "almuerzo"}, headers=cab_de(a1)
        )
        propio = recibir(w1, "agente.estado")
        assert (
            propio["datos"]["usuario_id"] == a1.id and propio["datos"]["motivo_pausa"] == "almuerzo"
        )
        assert recibir(ws, "agente.estado")["datos"]["usuario_id"] == a1.id


def test_consola_registro_llega_a_todos_los_agentes(client, esc, crear_usuario, reloj, h_admin):
    a1, a2 = crear_usuario("agente"), crear_usuario("agente")
    camp = esc.campana()
    with client.websocket_connect(url(a2)) as w2:
        recibir(w2, "conexion.lista")
        r = client.put(
            f"/api/v1/campanas/{camp.id}/agentes", json={"usuario_ids": [a1.id]}, headers=h_admin
        )
        assert r.status_code == 200
        ev = recibir(w2, "consola.registro")
        assert ev["datos"] == {
            "campana_id": camp.id,
            "campana_cliente_id": None,
            "accion": "asignacion",
        }


def test_flujo_de_llamada_emite_eventos_al_supervisor_y_al_agente(
    client, esc, crear_usuario, reloj, db
):
    ctx = contexto(esc, crear_usuario, reloj)
    sup = crear_usuario("supervisor")
    from escenario import telefono_de

    with client.websocket_connect(url(sup)) as ws, client.websocket_connect(url(ctx.agente)) as wa:
        recibir(ws, "conexion.lista")
        recibir(wa, "conexion.lista")
        r = client.post(
            "/api/v1/telefonia/simulacion/llamadas",
            json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
            headers=cab_de(ctx.agente),
        )
        lid = r.json()["llamada_id"]
        for w in (ws, wa):
            e1 = recibir(w, "agente.estado")
            assert e1["datos"] == {
                "usuario_id": ctx.agente.id, "estado": "en_llamada",
                "desde": "2026-10-23T15:15:00Z", "motivo_pausa": None, "llamada_id": lid,
            }  # fmt: skip
            e2 = recibir(w, "llamada.estado")
            assert e2["datos"]["estado"] == "iniciando" and e2["datos"]["llamada_id"] == lid
            assert e2["datos"]["campana_id"] == ctx.campana.id and e2["datos"]["motivos"] == []


def test_bloqueo_publica_motivos(client, esc, crear_usuario, reloj, db):
    from escenario import telefono_de

    ctx = contexto(esc, crear_usuario, reloj)
    esc.estado(ctx.agente, "pausa", reloj())
    with client.websocket_connect(url(ctx.agente)) as wa:
        recibir(wa, "conexion.lista")
        client.post(
            "/api/v1/telefonia/simulacion/llamadas",
            json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
            headers=cab_de(ctx.agente),
        )
        ev = recibir(wa, "llamada.estado")
        assert ev["datos"]["estado"] == "bloqueada"
        assert [m["codigo"] for m in ev["datos"]["motivos"]] == ["AGENTE_NO_DISPONIBLE"]


def test_evento_solo_tras_commit_y_no_tras_rollback(db):
    memoria = bus.BusMemoria()
    recibidos = []
    memoria.suscribir(recibidos.append)
    bus.establecer_bus(memoria)
    try:
        db.execute(text("SELECT 1"))  # abre la transacción, como cualquier operación real
        bus.publicar(
            db,
            "consola.registro",
            {"campana_id": 1, "campana_cliente_id": None, "accion": "asignacion"},
        )
        assert recibidos == []  # aún no se confirma
        db.rollback()
        db.commit()
        assert recibidos == []  # un rollback no emite
        db.execute(text("SELECT 1"))
        bus.publicar(db, "agente.estado", {"usuario_id": 1})
        db.commit()
        assert [e["tipo"] for e in recibidos] == ["agente.estado"]
        db.commit()
        assert len(recibidos) == 1  # no se reenvía
    finally:
        bus.establecer_bus(None)


def test_error_en_un_endpoint_no_emite_eventos(client, crear_usuario, esc, h_admin, monkeypatch):
    """Si la transacción falla antes del commit no se publica nada."""
    sup = crear_usuario("supervisor")
    camp = esc.campana()
    ag = crear_usuario("agente")
    from app.modulos.campanas import servicio

    def boom(*a, **k):
        raise RuntimeError("fallo")

    monkeypatch.setattr(servicio.auditoria, "registrar", boom)
    with client.websocket_connect(url(sup)) as ws:
        recibir(ws, "conexion.lista")
        r = client.put(
            f"/api/v1/campanas/{camp.id}/agentes", json={"usuario_ids": [ag.id]}, headers=h_admin
        )
        assert r.status_code == 500
        monkeypatch.undo()
        ws.send_json({"tipo": "ping"})
        assert recibir(ws)["tipo"] == "pong"  # lo siguiente que llega es el pong: no hubo eventos


def test_desconexion_prolongada_pasa_a_desconectado(
    client, crear_usuario, esc, reloj, db, monkeypatch
):
    monkeypatch.setattr(get_settings(), "consola_desconexion_segundos", 0)
    agente = crear_usuario("agente")
    esc.estado(agente, "disponible", reloj())
    with client.websocket_connect(url(agente)) as ws:
        recibir(ws, "conexion.lista")
    for _ in range(50):
        db.expire_all()
        if db.get(EstadoAgente, agente.id).estado == "desconectado":
            break
        time.sleep(0.1)
    assert db.get(EstadoAgente, agente.id).estado == "desconectado"


def test_en_llamada_no_se_desconecta_ni_con_reconexion(
    client, crear_usuario, esc, reloj, db, monkeypatch
):
    monkeypatch.setattr(get_settings(), "consola_desconexion_segundos", 0)
    agente = crear_usuario("agente")
    esc.estado(agente, "en_llamada", reloj())
    with client.websocket_connect(url(agente)) as ws:
        recibir(ws, "conexion.lista")
    time.sleep(0.5)
    db.expire_all()
    assert db.get(EstadoAgente, agente.id).estado == "en_llamada"


def test_desconectar_por_inactividad_servicio(db, crear_usuario, esc, reloj):
    from app.modulos.consola import estado

    agente = crear_usuario("agente")
    assert estado.desconectar_por_inactividad(db, agente.id, reloj()) is False  # sin fila
    esc.estado(agente, "pausa", reloj())
    assert estado.desconectar_por_inactividad(db, agente.id, reloj()) is True
    assert estado.desconectar_por_inactividad(db, agente.id, reloj()) is False


@pytest.mark.postgres
def test_notify_llega_a_un_socket_conectado():
    """Requiere PostgreSQL (TEST_DATABASE_URL): un NOTIFY externo se reparte por WebSocket."""
    url_bd = os.environ.get("TEST_DATABASE_URL")
    if not url_bd:
        pytest.skip("TEST_DATABASE_URL no definido")
    import json

    from fastapi.testclient import TestClient
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from app.config import Settings
    from app.db import Base, crear_engine, get_db
    from app.main import create_app
    from app.modulos.usuarios.modelos import Usuario
    from app.seguridad import hash_password

    engine = crear_engine(url_bd)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with fabrica() as db:
            u = Usuario(
                email="a@x.co",
                nombre="A",
                rol="supervisor",
                password_hash=hash_password("ClaveSegura123"),
            )
            db.add(u)
            db.commit()
        app = create_app(Settings(_env_file=None, entorno="test", database_url=url_bd))

        def _sesion():
            with fabrica() as s:
                yield s

        app.dependency_overrides[get_db] = _sesion
        with TestClient(app) as c, c.websocket_connect(url(u)) as ws:
            recibir(ws, "conexion.lista")
            time.sleep(1)  # deja que el LISTEN quede activo
            with engine.begin() as conn:
                evento = {"tipo": "consola.registro", "datos": {"campana_id": 1}, "emitido_en": "x"}
                conn.execute(text("SELECT pg_notify('eventos', :c)"), {"c": json.dumps(evento)})
            assert recibir(ws, "consola.registro")["datos"] == {"campana_id": 1}
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_escucha_convierte_url_de_sqlalchemy_a_libpq():
    from app.tiempo_real.escucha import url_psycopg

    assert url_psycopg("postgresql+psycopg://u:p@db:5432/x") == "postgresql://u:p@db:5432/x"
    assert url_psycopg("postgresql://u@h/x") == "postgresql://u@h/x"


def test_seleccion_del_bus_segun_configuracion(monkeypatch):
    s = get_settings()
    assert bus.crear_bus("sqlite://").nombre == "memoria"
    assert bus.crear_bus("postgresql+psycopg://u:p@h/x").nombre == "postgres"
    monkeypatch.setattr(s, "bus_eventos", "memoria")
    assert bus.crear_bus("postgresql+psycopg://u:p@h/x").nombre == "memoria"
    monkeypatch.setattr(s, "bus_eventos", "postgres")
    assert bus.crear_bus("sqlite://").nombre == "postgres"
