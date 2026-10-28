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


def test_s4b_el_worker_libera_al_arrancar_sus_propios_trabajos_en_proceso(session_factory, db):
    propio = encolar(db, "whatsapp.enviar_mensaje", {"mensaje_id": 1}, clave_unica="enviar:1")
    ajeno = encolar(db, "test.x", {})
    cola.tomar(db, "w-1", T0, 1)  # lo toma "w-1" y el proceso muere
    cola.tomar(db, "otro", T0, 1)
    w = worker.Trabajador(fabrica=session_factory, reloj=lambda: T0, nombre="w-1")
    assert w.liberar_propios() == 1
    db.expire_all()
    p, a = db.get(Trabajo, propio.id), db.get(Trabajo, ajeno.id)
    assert (p.estado, p.bloqueado_por, p.clave_unica) == ("pendiente", None, "enviar:1")
    assert (a.estado, a.bloqueado_por) == ("en_proceso", "otro")


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
    cola.ejecutar(session_factory, t.id, lambda: tarde)
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
