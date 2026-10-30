"""Revisión 2B: cola (S4), proxy de medios (S3) y errores de conexión (S12)."""

import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import requests
from sqlalchemy import select
from urllib3.exceptions import MaxRetryError, NameResolutionError, NewConnectionError, ProtocolError

from app import worker
from app.config import Settings
from app.errores import ErrorApp
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.integraciones.whatsapp.twilio import ProveedorWhatsAppTwilio
from app.trabajos import cola, registro
from app.trabajos.modelos import Trabajo

T0 = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


@pytest.fixture()
def manejadores():
    antes = dict(registro.MANEJADORES), dict(registro.AL_AGOTAR)
    registro.cargar_manejadores()
    yield
    registro.MANEJADORES.clear()
    registro.MANEJADORES.update(antes[0])
    registro.AL_AGOTAR.clear()
    registro.AL_AGOTAR.update(antes[1])


def encolar(db, tipo, payload, **kw):
    t = cola.encolar(db, tipo, payload, ahora=T0, **kw)
    db.commit()
    return t


def test_s4a_el_agotamiento_por_bloqueo_caducado_llama_al_gancho(db, manejadores):
    llamadas = []
    registro.AL_AGOTAR["test.x"] = lambda db_, payload, codigo, ahora: llamadas.append(
        (payload, codigo)
    )
    t = encolar(db, "test.x", {"mensaje_id": 5}, max_intentos=1)
    cola.tomar(db, "w", T0, 1)
    assert cola.tomar(db, "w", T0 + timedelta(seconds=400), 1) == []
    assert db.get(Trabajo, t.id).estado == "fallido"
    assert llamadas == [({"mensaje_id": 5}, "AGOTADO")]


def _worker(session_factory, nombre, reloj=lambda: T0):
    return worker.Trabajador(fabrica=session_factory, reloj=reloj, nombre=nombre)


def test_s4b_libera_instancia_muerta_de_la_misma_maquina_y_no_la_ajena(session_factory, db):
    propio = encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 1}, clave_unica="enviar:1")
    ajeno = encolar(db, "test.x", {})
    cola.tomar(db, "host-100-aaaa", T0, 1)  # instancia anterior, muerta (sin latido)
    cola.tomar(db, "otrohost-7-cccc", T0, 1)  # otra máquina
    w = _worker(session_factory, "host-200-bbbb", reloj=lambda: T0 + timedelta(seconds=400))
    assert w.liberar_propios() == 1
    db.expire_all()
    p, a = db.get(Trabajo, propio.id), db.get(Trabajo, ajeno.id)
    assert (p.estado, p.bloqueado_por, p.clave_unica) == ("pendiente", None, "enviar:1")
    assert (a.estado, a.bloqueado_por) == ("en_proceso", "otrohost-7-cccc")


def test_s4b_dos_workers_vivos_no_se_liberan_trabajos_entre_si(session_factory, db):
    t = encolar(db, "test.x", {})
    cola.tomar(db, "host-100-aaaa", T0, 1)
    vivo = _worker(session_factory, "host-100-aaaa")
    vivo._latir()  # latido reciente: sigue vivo
    vencido = lambda: T0 + timedelta(seconds=400)  # noqa: E731
    vivo._latir()
    otro = _worker(session_factory, "host-200-bbbb", reloj=lambda: T0 + timedelta(seconds=10))
    assert otro.liberar_propios() == 0
    assert vivo.liberar_propios() == 0  # ni el propio en marcha normal
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "en_proceso"
    # Sin latido reciente (60 s) ya se considera muerto.
    tarde = _worker(session_factory, "host-200-bbbb", reloj=vencido)
    assert tarde.liberar_propios() == 1


def test_s4b_no_libera_con_bloqueo_vigente_ni_de_un_host_con_prefijo_parecido(session_factory, db):
    a = encolar(db, "test.x", {})
    b = encolar(db, "test.y", {})
    cola.tomar(db, "host-100-aaaa", T0, 1)  # sin latido, pero con bloqueo vigente
    cola.tomar(db, "host-2-100-aaaa", T0, 1)  # host "host-2", no "host"
    w = _worker(session_factory, "host-200-bbbb", reloj=lambda: T0 + timedelta(seconds=120))
    assert w.liberar_propios() == 0  # bloqueo (300 s) aún vigente
    w = _worker(session_factory, "host-200-bbbb", reloj=lambda: T0 + timedelta(seconds=400))
    assert w.liberar_propios() == 1
    db.expire_all()
    assert (db.get(Trabajo, a.id).estado, db.get(Trabajo, b.id).estado) == (
        "pendiente",
        "en_proceso",
    )


def test_s4b_al_arrancar_libera_sus_propios_trabajos(session_factory, db):
    t = encolar(db, "test.x", {})
    cola.tomar(db, "host-1-aa", T0, 1)
    w = _worker(session_factory, "host-1-aa")
    assert w.liberar_propios() == 0
    assert w.liberar_propios(incluir_propio=True) == 1
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "pendiente"


def test_trabajo_venenoso_se_agota_y_no_entra_en_bucle(session_factory, db, manejadores):
    llamadas = []
    registro.AL_AGOTAR["test.x"] = lambda db_, payload, codigo, ahora: llamadas.append(codigo)
    t = encolar(db, "test.x", {"mensaje_id": 999}, max_intentos=3)
    w = _worker(session_factory, "host-1-aa")
    for _ in range(8):
        with session_factory() as s:
            if not cola.tomar(s, "host-1-aa", T0, 10):
                break  # el trabajo mata al worker (SIGKILL/OOM) tras tomarlo
        w.liberar_propios(incluir_propio=True)
    db.expire_all()
    t = db.get(Trabajo, t.id)
    assert t.estado == "fallido" and t.intentos <= t.max_intentos + 1
    assert llamadas == ["AGOTADO"]


def test_tomar_aplica_max_intentos_a_pendientes_recuperados(db, manejadores):
    llamadas = []
    registro.AL_AGOTAR["test.x"] = lambda db_, payload, codigo, ahora: llamadas.append(codigo)
    t = encolar(db, "test.x", {}, max_intentos=2)
    t.intentos = 2  # ya agotó los intentos pero quedó "pendiente"
    db.commit()
    assert cola.tomar(db, "w", T0, 5) == []
    assert db.get(Trabajo, t.id).estado == "fallido" and llamadas == ["AGOTADO"]


def test_gancho_de_agotamiento_que_falla_no_aborta_tomar(db, manejadores):
    def malo(db_, payload, codigo, ahora):
        db_.add(Trabajo(tipo="test.basura", payload={}, disponible_desde=ahora))
        raise RuntimeError("secreto@x.com")

    registro.AL_AGOTAR["test.x"] = malo
    a = encolar(db, "test.x", {}, max_intentos=1)
    b = encolar(db, "test.y", {})
    cola.tomar(db, "w", T0, 1)  # toma a (intentos=1)
    db.commit()
    tomados = cola.tomar(db, "w2", T0 + timedelta(seconds=400), 5)  # a caducado, b pendiente
    assert [x.id for x in tomados] == [b.id]
    db.commit()
    assert db.get(Trabajo, a.id).estado == "fallido"
    assert db.scalar(select(Trabajo).where(Trabajo.tipo == "test.basura")) is None  # savepoint


def test_worker_ejecuta_trabajo_que_ya_retomo_otro(session_factory, db, manejadores):
    from app.config import get_settings

    ejecutado = []
    registro.MANEJADORES["test.x"] = lambda db_, payload, ahora: ejecutado.append(1)
    t = encolar(db, "test.x", {})
    cola.tomar(db, "A", T0, 10)
    mas_tarde = T0 + timedelta(seconds=get_settings().worker_bloqueo_segundos + 1)
    assert [x.id for x in cola.tomar(db, "B", mas_tarde, 10)] == [t.id]
    db.commit()
    cola.ejecutar(session_factory, t.id, lambda: mas_tarde, "A")  # A llega tarde: no ejecuta
    assert ejecutado == []
    db.expire_all()
    assert db.get(Trabajo, t.id).bloqueado_por == "B"
    cola.ejecutar(session_factory, t.id, lambda: mas_tarde, "B")
    assert ejecutado == [1]
    db.expire_all()
    assert db.get(Trabajo, t.id).estado == "completado"


def test_s4c_ejecutar_renueva_el_bloqueo_al_empezar(db, session_factory, manejadores):
    visto = {}

    def manejador(db_, payload, ahora):
        visto["hasta"] = db_.get(Trabajo, payload["id"]).bloqueado_hasta

    registro.MANEJADORES["test.x"] = manejador
    t = encolar(db, "test.x", {})
    t.payload = {"id": t.id}
    db.commit()
    cola.tomar(db, "w", T0, 1)
    tarde = T0 + timedelta(seconds=250)
    cola.ejecutar(session_factory, t.id, lambda: tarde, "w")
    assert visto["hasta"] == tarde + timedelta(seconds=300)


def test_s4d_reintento_y_reprogramacion_restauran_la_clave_unica(db, session_factory, manejadores):
    def transitorio(*_):
        raise registro.ErrorTrabajo("X", transitorio=True)

    registro.MANEJADORES["whatsapp.enviar_mensaje"] = transitorio
    t = encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 7}, clave_unica="enviar:7")
    assert cola.ejecutar_pendientes(db, T0) == 1
    db.expire_all()
    t = db.get(Trabajo, t.id)
    assert (t.estado, t.clave_unica) == ("pendiente", "enviar:7")
    # Encolar de nuevo el mismo envío ya no duplica: devuelve el pendiente.
    assert (
        cola.encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 7}, clave_unica="enviar:7").id
        == t.id
    )

    def reprograma(*_):
        raise registro.ReprogramarTrabajo(T0 + timedelta(hours=2))

    registro.MANEJADORES["whatsapp.enviar_mensaje"] = reprograma
    cola.ejecutar_pendientes(db, T0 + timedelta(seconds=10))
    db.expire_all()
    assert db.get(Trabajo, t.id).clave_unica == "enviar:7"


def test_s4d_no_restaura_si_ya_hay_otro_pendiente_con_la_clave(db):
    a = encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 9}, clave_unica="enviar:9")
    cola.tomar(db, "w", T0, 1)
    b = encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 9}, clave_unica="enviar:9")
    a = db.get(Trabajo, a.id)
    cola.restaurar_clave(db, a)
    db.commit()
    assert a.clave_unica is None and b.clave_unica == "enviar:9"
    assert len(db.scalars(select(Trabajo)).all()) == 2


# ---- S3 ----------------------------------------------------------------------------------------
def test_s3_el_proxy_limita_las_descargas_simultaneas(db, monkeypatch, esc, crear_usuario, reloj):
    from wa import contexto, crear_conv

    from app.config import get_settings
    from app.modulos.conversaciones.dueno import Humano
    from app.modulos.conversaciones.modelos import Mensaje
    from app.modulos.whatsapp import servicio_medios

    monkeypatch.setattr(get_settings(), "whatsapp_media_concurrencia", 1)
    servicio_medios._semaforos.clear()
    ctx = contexto(esc, crear_usuario, reloj, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    m = Mensaje(
        conversacion_id=conv.id,
        numero_cliente_e164="+573001234567",
        direccion="entrante",
        autor="cliente",
        tipo="media",
        estado="recibido",
        creado_en=reloj(),
        procesado_en=reloj(),
        media=[
            {
                "indice": 0,
                "tipo_contenido": "image/png",
                "categoria": "imagen",
                "url_proveedor": "https://media.falso.invalid/a/image/png",
            }
        ],
    )
    db.add(m)
    db.commit()
    sem = servicio_medios._semaforo()
    assert sem.acquire(blocking=False)  # una descarga en curso
    try:
        with pytest.raises(ErrorApp) as e:
            servicio_medios.descargar(db, ctx.agente, conv.id, m.id, 0, reloj())
        assert (e.value.status, e.value.codigo) == (429, "DEMASIADAS_DESCARGAS")
    finally:
        sem.release()
    assert servicio_medios.descargar(db, ctx.agente, conv.id, m.id, 0, reloj()).contenido
    assert sem.acquire(blocking=False)  # el cupo se libera tras cada descarga
    sem.release()
    assert isinstance(sem, type(threading.BoundedSemaphore()))
    servicio_medios._semaforos.clear()


def test_s3_la_descarga_lenta_se_corta_por_duracion_total(monkeypatch):
    s = Settings(
        _env_file=None,
        entorno="test",
        whatsapp_proveedor="twilio",
        twilio_account_sid="AC" + "1" * 32,
        twilio_auth_token="t",
        twilio_api_key_sid="SK",
        twilio_api_key_secret="s",
        public_base_url="https://x.co",
        whatsapp_media_duracion_segundos=5,
    )
    reloj = iter([0.0, 1.0, 2.0, 100.0, 200.0])
    monkeypatch.setattr("app.integraciones.whatsapp.twilio.time.monotonic", lambda: next(reloj))

    def contenido():
        for _ in range(4):
            yield b"x" * 10

    def manejador(req):
        return httpx.Response(200, content=contenido(), headers={"content-type": "image/png"})

    p = ProveedorWhatsAppTwilio(s, transporte_http=httpx.MockTransport(manejador))
    url = f"https://api.twilio.com/2010-04-01/Accounts/AC{'1' * 32}/Messages/MM1/Media/ME1"
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        p.descargar_media(url, 1000)
    assert (e.value.codigo, e.value.transitorio) == ("PROVEEDOR_NO_DISPONIBLE", True)


# ---- S12 ---------------------------------------------------------------------------------------
def _twilio(error):
    from types import SimpleNamespace

    s = Settings(_env_file=None, entorno="test")

    def crear(**kw):
        raise error

    cliente = SimpleNamespace(messages=SimpleNamespace(create=crear))
    return ProveedorWhatsAppTwilio(s, cliente_rest=lambda: cliente)


@pytest.mark.parametrize(
    ("error", "codigo", "transitorio"),
    [
        (
            requests.ConnectionError(
                MaxRetryError(None, "u", reason=NewConnectionError(None, "x"))
            ),
            "CONEXION",
            True,
        ),
        (
            requests.ConnectionError(
                MaxRetryError(None, "u", reason=NameResolutionError("h", None, OSError()))
            ),
            "CONEXION",
            True,
        ),
        (requests.ConnectionError(ProtocolError("reset")), "ENVIO_INCIERTO", False),
        (requests.ConnectionError("Connection aborted."), "ENVIO_INCIERTO", False),
        (
            requests.ConnectionError(MaxRetryError(None, "u", reason=ProtocolError("x"))),
            "ENVIO_INCIERTO",
            False,
        ),
        (requests.ReadTimeout(), "ENVIO_INCIERTO", False),
    ],
)
def test_s12_errores_de_conexion_previos_al_envio_son_transitorios(error, codigo, transitorio):
    with pytest.raises(ErrorProveedorWhatsApp) as e:
        _twilio(error).enviar_texto(origen="+57300", destino="+57301", texto="x", url_estado="u")
    assert (e.value.codigo, e.value.transitorio) == (codigo, transitorio)


@pytest.mark.parametrize(
    ("estado", "esperado"), [("enviando", "ENVIO_INCIERTO"), ("pendiente", "AGOTADO")]
)
def test_envio_agotado_codigo_segun_estado(db, esc, crear_usuario, reloj, estado, esperado):
    from wa import contexto, crear_conv, crear_saliente

    from app.modulos.conversaciones.dueno import Humano
    from app.modulos.whatsapp import servicio_envio

    ctx = contexto(esc, crear_usuario, reloj, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    m = crear_saliente(db, conv, reloj(), estado=estado, autor="agente", usuario_id=ctx.agente.id)
    servicio_envio.envio_agotado(db, {"mensaje_id": m.id}, "AGOTADO", reloj())
    db.commit()
    db.refresh(m)
    assert m.estado == "fallido" and m.error_codigo == esperado
