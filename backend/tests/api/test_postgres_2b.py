"""Concurrencia real de 2B sobre PostgreSQL (marcador `postgres`, P1-P10 de fase-2b.md §6).

El esquema se crea con las migraciones reales. Cada hilo usa su propia sesión/conexión."""

import os
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from escenario import Escenario, telefono_de
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from wa import EMPRESA, NUMERO, autorizar, crear_saliente, params_entrante, plantilla

from alembic import command
from alembic.config import Config
from app.db import crear_engine
from app.errores import ErrorApp
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.modulos.consola.esquemas import TipificacionDatos
from app.modulos.conversaciones import atencion, cierre
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import Humano, SinAsignar
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, EventoMensaje, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto, PoliticaCumplimiento
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_entrante, servicio_envio, servicio_estado
from app.modulos.whatsapp.modelos import PlantillaWhatsApp
from app.seguridad import hash_password
from app.trabajos import cola, registro
from app.trabajos.modelos import Trabajo

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
        h.join(60)
        assert not h.is_alive(), "hilo colgado (posible interbloqueo)"
    return salidas


def _esc_whatsapp(pg, n_agentes=2):
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        agentes = [_usuario(db, "agente", i + 1) for i in range(n_agentes)]
        esc = Escenario(db, admin.id)
        camp = esc.campana(whatsapp_habilitado=True)
        for a in agentes:
            esc.asignar(camp, a)
            esc.estado(a, "disponible", AHORA)
        return admin.id, camp.id, [a.id for a in agentes]


def _conv(db, numero, camp_id, cc=None, motivo="entrante", dueno=None):
    conv = conversaciones.crear_conversacion(
        db,
        numero_cliente=numero,
        numero_empresa=EMPRESA,
        iniciada_por="cliente",
        ahora=AHORA,
        dueno=dueno or SinAsignar(),
        cliente_id=cc.cliente_id if cc else None,
        campana_id=camp_id,
        campana_cliente_id=cc.id if cc else None,
    )
    conv.ultimo_entrante_en, conv.ventana_expira_en = AHORA, AHORA + timedelta(hours=24)
    if dueno is None:
        conversaciones.cambiar_dueno(db, conv, SinAsignar(), motivo, None, AHORA)
    db.commit()
    return conv.id


def test_p1_dos_tomar_simultaneos_una_gana_y_la_otra_409(pg):
    _, camp, (a1, a2) = _esc_whatsapp(pg)
    with pg() as db:
        cid = _conv(db, NUMERO, camp)
    barrera = threading.Barrier(2, timeout=10)

    def tomar(uid):
        def _f():
            with pg() as s:
                u = s.get(Usuario, uid)
                barrera.wait()
                return conversaciones.tomar(s, u, cid, AHORA)

        return _f

    r = _en_hilos([tomar(a1), tomar(a2)])
    ok = [x for x in r if not isinstance(x, BaseException)]
    mal = [x for x in r if isinstance(x, BaseException)]
    assert len(ok) == 1 and len(mal) == 1, r
    assert isinstance(mal[0], ErrorApp) and mal[0].codigo == "CONVERSACION_ASIGNADA"
    with pg() as s:
        c = s.get(Conversacion, cid)
        assert c.atendida_por == "humano" and c.usuario_asignado_id in (a1, a2)
        assert (
            s.scalars(select(ColaAtencion).where(ColaAtencion.estado == "asignada")).all().__len__()
            == 1
        )


def test_p2_tomar_siguiente_con_una_fila_y_con_dos(pg):
    _, camp, (a1, a2) = _esc_whatsapp(pg)
    with pg() as db:
        c1 = _conv(db, "+573115550001", camp)

    def siguiente(uid):
        def _f():
            with pg() as s:
                return atencion.tomar_siguiente(s, s.get(Usuario, uid), AHORA)

        return _f

    r = _en_hilos([siguiente(a1), siguiente(a2)])
    assert sorted(x is None for x in r) == [False, True], r  # una conversación y un "204"
    with pg() as db:
        c2 = _conv(db, "+573115550002", camp)
        c3 = _conv(db, "+573115550003", camp)
    r = _en_hilos([siguiente(a1), siguiente(a2)])
    # Con dos filas libres cada uno se lleva una distinta (sin esperar).
    asignadas = {x.id for x in r if x is not None}
    assert len(asignadas) == 2 and asignadas <= {c1, c2, c3}, r


def test_p3_dos_workers_ejecutan_cada_trabajo_exactamente_una_vez(pg):
    vistos: list[int] = []
    bloqueo = threading.Lock()

    def manejador(db, payload, ahora):
        with bloqueo:
            vistos.append(payload["n"])

    registro.MANEJADORES["test.p3"] = manejador
    try:
        with pg() as db:
            for n in range(50):
                cola.encolar(db, "test.p3", {"n": n}, ahora=AHORA)
            db.commit()

        def worker(nombre):
            def _f():
                while True:
                    with pg() as s:
                        tomados = [t.id for t in cola.tomar(s, nombre, AHORA, 3)]
                    if not tomados:
                        return
                    for tid in tomados:
                        cola.ejecutar(pg, tid, lambda: AHORA)

            return _f

        r = _en_hilos([worker("w1"), worker("w2")])
        assert all(not isinstance(x, BaseException) for x in r), r
        assert sorted(vistos) == list(range(50))
        with pg() as s:
            assert s.scalar(select(func.count()).where(Trabajo.estado == "completado")) == 50
        # Un trabajo con bloqueo caducado lo recupera el otro worker.
        with pg() as db:
            t = cola.encolar(db, "test.p3", {"n": 99}, ahora=AHORA)
            db.commit()
            tid = t.id
        with pg() as s:
            assert [x.id for x in cola.tomar(s, "muerto", AHORA, 1)] == [tid]
        with pg() as s:
            assert cola.tomar(s, "w2", AHORA + timedelta(seconds=10), 1) == []
            assert [x.id for x in cola.tomar(s, "w2", AHORA + timedelta(seconds=400), 1)] == [tid]
    finally:
        registro.MANEJADORES.pop("test.p3", None)


def test_p4_mismo_webhook_entrante_en_paralelo_una_fila_y_un_trabajo(pg):
    _esc_whatsapp(pg)
    params = params_entrante(sid="SMp4")
    barrera = threading.Barrier(5, timeout=10)

    def recibir():
        with pg() as s:
            barrera.wait()
            return servicio_entrante.recibir(s, obtener_proveedor_whatsapp(), params, AHORA)

    r = _en_hilos([recibir] * 5)
    assert all(not isinstance(x, BaseException) for x in r), r
    assert sum(x is not None for x in r) == 1
    with pg() as s:
        assert s.scalar(select(func.count(Mensaje.id))) == 1
        assert s.scalar(select(func.count(Trabajo.id))) == 1


def _entrante(pg, texto, sid):
    with pg() as s:
        m = servicio_entrante.recibir(
            s, obtener_proveedor_whatsapp(), params_entrante(texto=texto, sid=sid), AHORA
        )
        return m.id


def test_p5_dos_entrantes_de_un_numero_nuevo_una_sola_conversacion(pg):
    _esc_whatsapp(pg)
    ids = [_entrante(pg, "uno", "SMp5a"), _entrante(pg, "dos", "SMp5b")]
    barrera = threading.Barrier(2, timeout=10)

    def procesar(mid):
        def _f():
            with pg() as s:
                barrera.wait()
                servicio_entrante.procesar_entrante(s, {"mensaje_id": mid}, AHORA)
                s.commit()

        return _f

    r = _en_hilos([procesar(i) for i in ids])
    assert all(not isinstance(x, BaseException) for x in r), r
    with pg() as s:
        convs = s.scalars(select(Conversacion)).all()
        assert len(convs) == 1 and convs[0].mensajes_sin_leer == 2
        assert {m.conversacion_id for m in s.scalars(select(Mensaje))} == {convs[0].id}
        assert s.scalar(select(func.count(ColaAtencion.id))) == 1


def _politica(pg, **frecuencia):
    with pg() as db:
        for fila in db.scalars(select(PoliticaCumplimiento)):
            cfg = dict(fila.configuracion)
            cfg["frecuencia"] = {**cfg["frecuencia"], **frecuencia}
            fila.configuracion = cfg
        db.commit()


def test_p6_plantilla_y_twiml_de_voz_simultaneos_solo_uno_pasa(pg):
    from app.modulos.telefonia import servicio as telefonia

    _politica(pg, max_contactos_dia=1, max_canales_semana=2)
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        ag_voz, ag_wa = _usuario(db, "agente", 1), _usuario(db, "agente", 2)
        esc = Escenario(db, admin.id)
        camp = esc.campana(whatsapp_habilitado=True)
        for a in (ag_voz, ag_wa):
            esc.asignar(camp, a)
            esc.estado(a, "disponible", AHORA)
        cc = esc.registro(camp, producto="Oro")
        esc.reservar(cc, ag_voz, AHORA)
        autorizar(db)
        pl = plantilla(db)
        from app.modulos.cumplimiento import servicio as cumplimiento

        # Lunes: contacto directo de voz (activa la regla "solo tras contacto directo").
        cumplimiento.registrar_intento(
            db,
            cliente_id=cc.cliente_id,
            tipo_campana="cobranza",
            canal="voz",
            iniciado_por="empresa",
            momento=AHORA - timedelta(days=4),
            campana_id=camp.id,
            contacto_directo=True,
        )
        db.commit()
        ids = dict(cc=cc.id, tel=telefono_de(db, cc).id, voz=ag_voz.id, wa=ag_wa.id, pl=pl.id)
    barrera = threading.Barrier(2, timeout=10)

    def voz():
        with pg() as s:
            barrera.wait()
            return telefonia.procesar_saliente(
                s,
                call_sid="CAp6",
                desde=f"client:agente_{ids['voz']}",
                account_sid=None,
                campana_cliente_id=str(ids["cc"]),
                telefono_id=str(ids["tel"]),
                ahora=AHORA,
                verificar_cuenta=False,
            )

    def wa():
        from app.modulos.clientes.modelos import CampanaCliente, Telefono

        with pg() as s:
            barrera.wait()
            return servicio_envio.enviar_plantilla(
                s,
                usuario=s.get(Usuario, ids["wa"]),
                campana_cliente=s.get(CampanaCliente, ids["cc"]),
                telefono=s.get(Telefono, ids["tel"]),
                plantilla=s.get(PlantillaWhatsApp, ids["pl"]),
                conversacion=None,
                idempotencia_clave=uuid.uuid4(),
                ahora=AHORA,
            )

    rv, rw = _en_hilos([voz, wa])
    assert not isinstance(rv, BaseException) and not isinstance(rw, BaseException), (rv, rw)
    assert rv.permitida != rw.permitido, "exactamente uno debe pasar"
    codigos = (
        [m["codigo"] for m in rv.motivos] if not rv.permitida else [m.codigo for m in rw.motivos]
    )
    assert "FRECUENCIA_DIA" in codigos
    with pg() as s:
        hoy = s.scalar(
            select(func.count(IntentoContacto.id)).where(IntentoContacto.momento == AHORA)
        )
        assert hoy == 1


def test_p7_cierre_y_entrante_simultaneos_sin_interbloqueo(pg):
    _, camp, (a1, _) = _esc_whatsapp(pg)
    with pg() as db:
        admin = db.scalar(select(Usuario).where(Usuario.rol == "administrador"))
        esc = Escenario(db, admin.id)
        cc = esc.registro(
            db.get(__import__("app.modulos.campanas.modelos", fromlist=["Campana"]).Campana, camp)
        )
        cid = _conv(db, NUMERO, camp, cc=cc, dueno=Humano(a1))
        db.add(
            Mensaje(
                conversacion_id=cid,
                numero_cliente_e164=NUMERO,
                direccion="entrante",
                autor="cliente",
                tipo="texto",
                cuerpo="hola",
                estado="recibido",
                creado_en=AHORA,
                procesado_en=AHORA,
            )
        )
        db.commit()
    mid = _entrante(pg, "otra", "SMp7")
    barrera = threading.Barrier(2, timeout=10)

    def cerrar():
        with pg() as s:
            barrera.wait()
            return cierre.cerrar_conversacion(
                s, s.get(Usuario, a1), cid, TipificacionDatos(resultado="contactado"), AHORA
            )

    def entrar():
        with pg() as s:
            barrera.wait()
            servicio_entrante.procesar_entrante(s, {"mensaje_id": mid}, AHORA)
            s.commit()

    r = _en_hilos([cerrar, entrar])
    assert all(not isinstance(x, BaseException) for x in r), r
    with pg() as s:
        m = s.get(Mensaje, mid)
        assert m.conversacion_id is not None
        original = s.get(Conversacion, cid)
        assert original.estado == "cerrada"
        if m.conversacion_id != cid:  # el entrante llegó tras el cierre: abre otra
            assert s.get(Conversacion, m.conversacion_id).estado == "abierta"


def test_p8_estado_en_paralelo_con_la_tx2_del_envio(pg):
    _, camp, (a1, _) = _esc_whatsapp(pg)
    with pg() as db:
        cid = _conv(db, NUMERO, camp, dueno=Humano(a1))
        conv = db.get(Conversacion, cid)
        m = crear_saliente(db, conv, AHORA, estado="enviando", autor="agente", usuario_id=a1)
        mid = m.id
    sid = "SMp8"
    barrera = threading.Barrier(2, timeout=10)

    def tx2():
        with pg() as s:
            barrera.wait()
            servicio_envio._tras_exito(s, cid, mid, sid, AHORA)

    def webhook():
        with pg() as s:
            barrera.wait()
            servicio_estado.procesar_webhook(
                s,
                obtener_proveedor_whatsapp(),
                {"MessageSid": sid, "MessageStatus": "delivered"},
                AHORA,
            )

    r = _en_hilos([tx2, webhook])
    assert all(not isinstance(x, BaseException) for x in r), r
    with pg() as s:
        fila = s.get(Mensaje, mid)
        assert (fila.estado, fila.proveedor_id) == ("entregado", sid)
        assert s.scalar(select(EventoMensaje)).mensaje_id == mid


def test_p9_dos_agentes_plantilla_al_mismo_numero_una_conversacion(pg):
    from app.modulos.clientes.modelos import CampanaCliente, Telefono

    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        a1, a2 = _usuario(db, "agente", 1), _usuario(db, "agente", 2)
        esc = Escenario(db, admin.id)
        camp = esc.campana(whatsapp_habilitado=True)
        for a in (a1, a2):
            esc.asignar(camp, a)
            esc.estado(a, "disponible", AHORA)
        cc = esc.registro(camp, producto="Oro")
        autorizar(db)
        pl = plantilla(db)
        ids = dict(cc=cc.id, tel=telefono_de(db, cc).id, pl=pl.id, u=[a1.id, a2.id])
    barrera = threading.Barrier(2, timeout=10)

    def enviar(uid):
        def _f():
            with pg() as s:
                barrera.wait()
                return servicio_envio.enviar_plantilla(
                    s,
                    usuario=s.get(Usuario, uid),
                    campana_cliente=s.get(CampanaCliente, ids["cc"]),
                    telefono=s.get(Telefono, ids["tel"]),
                    plantilla=s.get(PlantillaWhatsApp, ids["pl"]),
                    conversacion=None,
                    idempotencia_clave=uuid.uuid4(),
                    ahora=AHORA,
                )

        return _f

    r = _en_hilos([enviar(u) for u in ids["u"]])
    ok = [x for x in r if not isinstance(x, BaseException)]
    mal = [x for x in r if isinstance(x, BaseException)]
    assert len(ok) == 1 and ok[0].permitido, r
    assert (
        len(mal) == 1 and isinstance(mal[0], ErrorApp) and mal[0].codigo == "CONVERSACION_ASIGNADA"
    )
    with pg() as s:
        assert (
            s.scalar(select(func.count(Conversacion.id)).where(Conversacion.estado == "abierta"))
            == 1
        )


def test_p10_desconectado_y_tomar_del_mismo_agente_son_coherentes(pg):
    from app.modulos.consola import estado as estado_agente

    _, camp, (a1, _) = _esc_whatsapp(pg)
    with pg() as db:
        cid = _conv(db, NUMERO, camp)
    barrera = threading.Barrier(2, timeout=10)

    def tomar():
        with pg() as s:
            barrera.wait()
            return conversaciones.tomar(s, s.get(Usuario, a1), cid, AHORA)

    def desconectar():
        with pg() as s:
            barrera.wait()
            estado_agente.desconectar_por_inactividad(s, a1, AHORA)

    r = _en_hilos([tomar, desconectar])
    if isinstance(r[0], BaseException):
        assert isinstance(r[0], ErrorApp) and r[0].codigo == "AGENTE_NO_DISPONIBLE", r
    assert not isinstance(r[1], BaseException), r
    with pg() as s:
        c = s.get(Conversacion, cid)
        assert (c.atendida_por, c.usuario_asignado_id) == ("sin_asignar", None)
        pendientes = s.scalars(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")).all()
        assert len(pendientes) == 1
