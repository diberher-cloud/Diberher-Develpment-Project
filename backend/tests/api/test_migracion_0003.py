"""Migración 0003 (WhatsApp y bandeja) en SQLite: datos de 2A, CHECK y UNIQUE por restricción."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from app.db import crear_engine
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, EventoMensaje, Mensaje
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal, PlantillaWhatsApp
from app.trabajos.modelos import Trabajo

RAIZ = Path(__file__).parent.parent.parent
AHORA = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)


def _cfg(ruta) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{ruta}")
    return cfg


def sembrar_2a(ruta) -> None:
    """Datos de 2A (esquema 0002) para comprobar que la migración no los toca."""
    d = "2026-01-01"
    filas = [
        (
            "usuarios",
            ("email", "nombre", "rol", "password_hash", "activo", "creado_en", "actualizado_en"),
            ("a@a.co", "A", "agente", "x", 1, d, d),
        ),
        (
            "campanas",
            (
                "nombre",
                "tipo",
                "estado",
                "max_intentos",
                "intervalo_reintento_minutos",
                "creado_por",
                "creado_en",
                "actualizado_en",
            ),
            ("c", "cobranza", "activa", 3, 60, 1, d, d),
        ),
        (
            "clientes",
            ("tipo_documento", "numero_documento", "nombre", "creado_en", "actualizado_en"),
            ("CC", "1", "N", d, d),
        ),
        (
            "telefonos",
            ("cliente_id", "numero_e164", "tipo_linea", "prioridad", "creado_en"),
            (1, "+573001234567", "movil", 1, d),
        ),
        (
            "campana_clientes",
            ("campana_id", "cliente_id", "estado", "datos_adicionales", "intentos", "creado_en"),
            (1, 1, "pendiente", "{}", 2, d),
        ),
        ("campana_agentes", ("campana_id", "usuario_id", "creado_en"), (1, 1, d)),
        (
            "llamadas",
            (
                "campana_cliente_id",
                "telefono_id",
                "usuario_id",
                "canal",
                "direccion",
                "call_sid",
                "estado",
                "motivos_bloqueo",
                "iniciada_en",
            ),
            (1, 1, 1, "voz", "saliente", "CA1", "completada", "[]", d),
        ),
        (
            "tipificaciones",
            (
                "campana_cliente_id",
                "canal",
                "origen",
                "usuario_id",
                "llamada_id",
                "resultado",
                "contacto_directo",
                "creado_en",
            ),
            (1, "voz", "agente", 1, 1, "promesa_pago", 1, d),
        ),
        (
            "promesas_pago",
            (
                "tipificacion_id",
                "campana_cliente_id",
                "monto",
                "fecha_pago",
                "numero_cuotas",
                "descuento_porcentaje",
                "estado",
                "origen",
                "creado_en",
            ),
            (1, 1, 100, "2026-11-01", 1, 0, "vigente", "agente", d),
        ),
        (
            "exclusiones",
            ("numero_e164", "motivo", "aplica_a", "creado_por", "creado_en"),
            ("+573009999999", "rne", "venta", 1, d),
        ),
        (
            "exclusiones",
            ("numero_e164", "motivo", "aplica_a", "creado_por", "creado_en"),
            ("+573008888888", "manual", "todas", 1, d),
        ),
    ]
    with sqlite3.connect(ruta) as con:
        con.execute("pragma foreign_keys=on")
        for tabla, columnas, valores in filas:
            marcas = ",".join("?" * len(columnas))
            con.execute(f"insert into {tabla}({','.join(columnas)}) values({marcas})", valores)


def insertar_exclusion(con, numero, motivo, canal, origen, creado_por) -> None:
    con.execute(
        "insert into exclusiones(numero_e164,motivo,aplica_a,canal,origen,creado_por,creado_en)"
        " values(?,?,?,?,?,?,?)",
        (numero, motivo, "todas", canal, origen, creado_por, "2026-01-01"),
    )


def test_upgrade_conserva_los_datos_de_2a_incluidas_las_hijas_en_cascada(tmp_path):
    ruta = tmp_path / "m.db"
    cfg = _cfg(ruta)
    command.upgrade(cfg, "0002")
    sembrar_2a(ruta)
    command.upgrade(cfg, "head")
    with sqlite3.connect(ruta) as con:
        # `campanas` y `tipificaciones` se recrean (batch): sus hijas NO deben borrarse.
        assert con.execute("select count(*) from campana_clientes").fetchone()[0] == 1
        assert con.execute("select count(*) from campana_agentes").fetchone()[0] == 1
        assert con.execute("select count(*) from promesas_pago").fetchone()[0] == 1
        assert con.execute("select count(*) from tipificaciones").fetchone()[0] == 1
        assert con.execute(
            "select whatsapp_habilitado, plantilla_inicial_id from campanas"
        ).fetchone() == (0, None)
        assert con.execute("select conversacion_id from tipificaciones").fetchone() == (None,)
        filas = con.execute(
            "select numero_e164, canal, origen, creado_por from exclusiones order by id"
        ).fetchall()
        assert filas == [
            ("+573009999999", "todos", "usuario", 1),
            ("+573008888888", "todos", "usuario", 1),
        ]
        assert con.execute("pragma foreign_key_check").fetchall() == []


def test_downgrade_a_0002_borra_solo_los_opt_outs_de_whatsapp_y_de_sistema_y_conserva_el_resto(
    tmp_path,
):
    ruta = tmp_path / "m2.db"
    cfg = _cfg(ruta)
    command.upgrade(cfg, "0002")
    sembrar_2a(ruta)
    command.upgrade(cfg, "head")
    with sqlite3.connect(ruta) as con:
        insertar_exclusion(con, "+573001111111", "solicitud_titular", "whatsapp", "usuario", 1)
        insertar_exclusion(con, "+573002222222", "solicitud_titular", "todos", "sistema", None)
        insertar_exclusion(con, "+573003333333", "manual", "todos", "usuario", 1)
    command.downgrade(cfg, "0002")
    with sqlite3.connect(ruta) as con:
        numeros = {f[0] for f in con.execute("select numero_e164 from exclusiones")}
        assert numeros == {"+573009999999", "+573008888888", "+573003333333"}
        columnas = {c[1] for c in con.execute("pragma table_info(exclusiones)")}
        assert not {"canal", "origen", "conversacion_id"} & columnas
        assert con.execute("select count(*) from campana_clientes").fetchone()[0] == 1
        assert con.execute("select count(*) from promesas_pago").fetchone()[0] == 1
        assert "conversaciones" not in {f[0] for f in con.execute("select name from sqlite_master")}
    command.upgrade(cfg, "head")  # sube de nuevo sin problemas


# ---- Un test por restricción ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def sesion(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("chk") / "chk.db"
    cfg = _cfg(ruta)
    command.upgrade(cfg, "0002")
    sembrar_2a(ruta)
    command.upgrade(cfg, "head")
    engine = crear_engine(f"sqlite:///{ruta}")
    with Session(engine) as s:
        s.add(conversacion(clave_abierta="padre|x"))  # id 1: padre de mensajes y de la cola
        s.flush()
        s.add_all(filas_validas())
        s.commit()
        yield s
    engine.dispose()


def plantilla(**kw):
    base = dict(
        content_sid="HX0",
        nombre="n",
        idioma="es",
        categoria="utility",
        estado_aprobacion="aprobada",
        cuerpo="c",
        variables=[],
        botones=[],
        tiene_boton_baja=False,
        mapeo_variables={},
        finalidad="cobranza",
        activa=False,
        sincronizada_en=AHORA,
        actualizado_en=AHORA,
    )
    return PlantillaWhatsApp(**{**base, **kw})


def conversacion(**kw):
    base = dict(
        clave_abierta="+57300|+57301",
        numero_cliente_e164="+573001234567",
        numero_empresa_e164="+573000000001",
        estado="abierta",
        atendida_por="sin_asignar",
        iniciada_por="cliente",
        ultimo_mensaje_en=AHORA,
        abierta_en=AHORA,
    )
    return Conversacion(**{**base, **kw})


def mensaje(**kw):
    base = dict(
        conversacion_id=None,
        numero_cliente_e164="+573001234567",
        direccion="entrante",
        autor="cliente",
        tipo="texto",
        estado="recibido",
        creado_en=AHORA,
    )
    return Mensaje(**{**base, **kw})


def autorizacion(**kw):
    base = dict(
        numero_e164="+573001234567",
        canal="whatsapp",
        finalidad="cobranza",
        origen="importacion",
        evidencia="e",
        otorgada_en=AHORA,
        clave_vigente="k",
        creado_en=AHORA,
    )
    return AutorizacionCanal(**{**base, **kw})


def cola(**kw):
    base = dict(
        conversacion_id=1, motivo="entrante", prioridad=2, estado="pendiente", creado_en=AHORA
    )
    return ColaAtencion(**{**base, **kw})


def trabajo(**kw):
    base = dict(
        tipo="t",
        payload={},
        estado="pendiente",
        intentos=0,
        max_intentos=5,
        disponible_desde=AHORA,
        creado_en=AHORA,
        actualizado_en=AHORA,
    )
    return Trabajo(**{**base, **kw})


def exclusion(**kw):
    base = dict(
        numero_e164="+573007777777",
        motivo="rne",
        aplica_a="venta",
        canal="todos",
        origen="usuario",
        creado_por=1,
    )
    return Exclusion(**{**base, **kw})


INVALIDOS = [
    ("plantilla categoria", lambda: plantilla(categoria="otra")),
    ("plantilla estado_aprobacion", lambda: plantilla(estado_aprobacion="otra")),
    ("plantilla finalidad", lambda: plantilla(finalidad="otra")),
    ("plantilla activa sin aprobar", lambda: plantilla(activa=True, estado_aprobacion="pendiente")),
    ("plantilla activa sin finalidad", lambda: plantilla(activa=True, finalidad=None)),
    ("conversacion estado", lambda: conversacion(estado="otra")),
    ("conversacion atendida_por", lambda: conversacion(atendida_por="otra")),
    ("conversacion iniciada_por", lambda: conversacion(iniciada_por="otra")),
    ("conversacion motivo_cierre", lambda: conversacion(motivo_cierre="otra")),
    ("conversacion mensajes_sin_leer", lambda: conversacion(mensajes_sin_leer=-1)),
    ("conversacion abierta sin clave", lambda: conversacion(clave_abierta=None)),
    ("conversacion cerrada con clave", lambda: conversacion(estado="cerrada", cerrada_en=AHORA)),
    ("conversacion cerrada sin fecha", lambda: conversacion(estado="cerrada", clave_abierta=None)),
    ("conversacion humano sin usuario", lambda: conversacion(atendida_por="humano")),
    ("conversacion sin_asignar con usuario", lambda: conversacion(usuario_asignado_id=1)),
    ("conversacion ia con usuario", lambda: conversacion(atendida_por="ia", usuario_asignado_id=1)),
    ("conversacion registro sin campaña", lambda: conversacion(campana_cliente_id=1, cliente_id=1)),
    ("mensaje direccion", lambda: mensaje(direccion="otra")),
    ("mensaje autor", lambda: mensaje(autor="otro")),
    ("mensaje tipo", lambda: mensaje(tipo="otro")),
    ("mensaje estado", lambda: mensaje(estado="otro")),
    (
        "mensaje agente sin usuario",
        lambda: mensaje(
            direccion="saliente", autor="agente", estado="pendiente", conversacion_id=1
        ),
    ),
    (
        "mensaje saliente sin conversacion",
        lambda: mensaje(direccion="saliente", autor="sistema", estado="pendiente"),
    ),
    ("mensaje entrante de agente", lambda: mensaje(autor="agente", usuario_id=1)),
    ("mensaje entrante no recibido", lambda: mensaje(estado="enviado")),
    (
        "mensaje saliente recibido",
        lambda: mensaje(direccion="saliente", autor="sistema", conversacion_id=1),
    ),
    (
        "mensaje saliente de cliente",
        lambda: mensaje(direccion="saliente", estado="pendiente", conversacion_id=1),
    ),
    ("autorizacion canal", lambda: autorizacion(canal="sms")),
    ("autorizacion finalidad", lambda: autorizacion(finalidad="otra")),
    ("autorizacion origen", lambda: autorizacion(origen="otro")),
    (
        "autorizacion motivo_revocacion",
        lambda: autorizacion(motivo_revocacion="otro", revocada_en=AHORA, clave_vigente=None),
    ),
    ("autorizacion vigente revocada", lambda: autorizacion(revocada_en=AHORA)),
    ("autorizacion sin vigencia", lambda: autorizacion(clave_vigente=None)),
    ("autorizacion agente sin usuario", lambda: autorizacion(origen="agente")),
    ("autorizacion cliente sin usuario", lambda: autorizacion(origen="cliente")),
    ("cola motivo", lambda: cola(motivo="otro")),
    ("cola prioridad 0", lambda: cola(prioridad=0)),
    ("cola prioridad 4", lambda: cola(prioridad=4)),
    ("cola estado", lambda: cola(estado="otro")),
    ("trabajo estado", lambda: trabajo(estado="otro")),
    ("trabajo max_intentos 0", lambda: trabajo(max_intentos=0)),
    ("trabajo max_intentos 21", lambda: trabajo(max_intentos=21)),
    ("exclusion canal", lambda: exclusion(canal="sms")),
    ("exclusion origen", lambda: exclusion(origen="otro")),
    ("exclusion usuario sin creador", lambda: exclusion(creado_por=None)),
]


@pytest.mark.parametrize(("nombre", "fabrica"), INVALIDOS, ids=[n for n, _ in INVALIDOS])
def test_los_check_rechazan_combinaciones_invalidas(sesion, nombre, fabrica):
    sesion.add(fabrica())
    with pytest.raises(IntegrityError) as e:
        sesion.flush()
    sesion.rollback()
    assert "CHECK" in str(e.value).upper(), nombre


def filas_validas():
    return [
        plantilla(content_sid="HXok1", activa=True),
        conversacion(clave_abierta="a|b", atendida_por="humano", usuario_asignado_id=1),
        conversacion(
            clave_abierta=None, estado="cerrada", cerrada_en=AHORA, motivo_cierre="agente"
        ),
        mensaje(proveedor_id="SMok1"),
        mensaje(
            direccion="saliente",
            autor="agente",
            usuario_id=1,
            estado="pendiente",
            conversacion_id=1,
        ),
        autorizacion(clave_vigente="ok1"),
        autorizacion(origen="agente", registrada_por=1, clave_vigente="ok2"),
        autorizacion(clave_vigente=None, revocada_en=AHORA, motivo_revocacion="opt_out"),
        cola(clave_activa="1", conversacion_id=1),
        trabajo(clave_unica="ok"),
        exclusion(creado_por=None, origen="sistema", numero_e164="+573006666666"),
    ]


def test_los_check_aceptan_las_combinaciones_validas(sesion):
    """Las filas válidas de `filas_validas()` se insertaron al preparar el esquema."""
    assert sesion.query(PlantillaWhatsApp).count() == 1
    assert sesion.query(Conversacion).count() == 3
    assert sesion.query(Mensaje).count() == 2
    assert sesion.query(AutorizacionCanal).count() == 3
    assert sesion.query(ColaAtencion).count() == 1 and sesion.query(Trabajo).count() == 1


UNICOS = [
    ("conversaciones.clave_abierta", lambda: conversacion(clave_abierta="a|b")),
    ("mensajes.proveedor_id", lambda: mensaje(proveedor_id="SMok1")),
    ("autorizaciones.clave_vigente", lambda: autorizacion(clave_vigente="ok1")),
    ("cola.clave_activa", lambda: cola(clave_activa="1", conversacion_id=1)),
    ("trabajos.clave_unica", lambda: trabajo(clave_unica="ok")),
    ("plantillas.content_sid", lambda: plantilla(content_sid="HXok1")),
    (
        "exclusiones numero+aplica_a+canal",
        lambda: exclusion(numero_e164="+573009999999", aplica_a="venta", canal="todos"),
    ),
]


@pytest.mark.parametrize(("nombre", "fabrica"), UNICOS, ids=[n for n, _ in UNICOS])
def test_unicidad(sesion, nombre, fabrica):
    sesion.add(fabrica())
    with pytest.raises(IntegrityError) as e:
        sesion.flush()
    sesion.rollback()
    assert "UNIQUE" in str(e.value).upper(), nombre


def test_los_unicos_de_exclusion_distinguen_el_canal_y_los_eventos(sesion):
    sesion.add(exclusion(numero_e164="+573009999999", aplica_a="venta", canal="whatsapp"))
    sesion.add(EventoMensaje(proveedor_id="SMx", estado_proveedor="sent", recibido_en=AHORA))
    sesion.add(EventoMensaje(proveedor_id="SMx", estado_proveedor="read", recibido_en=AHORA))
    sesion.commit()
    sesion.add(EventoMensaje(proveedor_id="SMx", estado_proveedor="sent", recibido_en=AHORA))
    with pytest.raises(IntegrityError):
        sesion.flush()
    sesion.rollback()
