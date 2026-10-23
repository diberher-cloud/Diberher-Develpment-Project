"""Migración 0001 -> 0002 sobre PostgreSQL real (marcador `postgres`; TEST_DATABASE_URL)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.postgres
RAIZ = Path(__file__).parent.parent
TABLAS_2A = {
    "campana_agentes", "estados_agente", "historial_estados_agente", "intentos_contacto",
    "llamadas", "eventos_llamada", "grabaciones", "tipificaciones", "promesas_pago", "ventas",
}  # fmt: skip


POLITICAS = (
    "select tipo_campana, version, configuracion::text from politicas_cumplimiento order by 1"
)


def _cfg(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def url_pg():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definido")
    cfg = _cfg(url)
    command.downgrade(cfg, "base")
    yield url
    command.downgrade(cfg, "base")


def _sembrar_fase_1(conn):
    conn.execute(
        text(
            "insert into usuarios(email,nombre,rol,password_hash,activo,creado_en,"
            "actualizado_en) values('a@a.co','A','administrador','x',true,now(),now())"
        )
    )
    conn.execute(
        text(
            "insert into campanas(nombre,tipo,estado,max_intentos,intervalo_reintento_minutos,"
            "creado_por,creado_en,actualizado_en) "
            "values('c','cobranza','activa',3,60,1,now(),now())"
        )
    )
    conn.execute(
        text(
            "insert into clientes(tipo_documento,numero_documento,nombre,creado_en,actualizado_en)"
            " values('CC','1','N',now(),now())"
        )
    )
    conn.execute(
        text(
            "insert into campana_clientes(campana_id,cliente_id,estado,datos_adicionales,intentos,"
            "creado_en) values(1,1,'en_gestion','{}',2,now())"
        )
    )


def test_0001_a_0002_conserva_datos_y_downgrade_los_restaura(url_pg):
    cfg = _cfg(url_pg)
    command.upgrade(cfg, "0001")
    engine = create_engine(url_pg)
    with engine.begin() as conn:
        _sembrar_fase_1(conn)
        politicas_antes = conn.execute(text(POLITICAS)).all()

    command.upgrade(cfg, "head")
    command.check(cfg)  # sin diferencias entre modelos y migración
    insp = inspect(engine)
    assert TABLAS_2A <= set(insp.get_table_names())
    with engine.begin() as conn:
        fila = conn.execute(
            text(
                "select estado, intentos, reservado_por, reservado_hasta, ultimo_resultado,"
                " ultima_gestion_en from campana_clientes"
            )
        ).one()
        assert tuple(fila) == ("en_gestion", 2, None, None, None, None)
        # Las políticas de Fase 1 no se reescriben.
        assert conn.execute(text(POLITICAS)).all() == politicas_antes

    # Restricciones reales de PostgreSQL (CHECK / UNIQUE / FK).
    def intentar(sql, **params):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(sql), params)

    intentar(
        "insert into estados_agente(usuario_id,estado,desde,actualizado_en)"
        " values(1,'volando',now(),now())"
    )
    intentar("update campana_clientes set ultimo_resultado='inventado' where id=1")
    intentar("insert into campana_agentes(campana_id,usuario_id,creado_en) values(1,999,now())")
    with engine.begin() as conn:
        conn.execute(
            text("insert into campana_agentes(campana_id,usuario_id,creado_en) values(1,1,now())")
        )
    intentar("insert into campana_agentes(campana_id,usuario_id,creado_en) values(1,1,now())")
    intentar(
        "insert into llamadas(campana_cliente_id,telefono_id,call_sid,estado,motivos_bloqueo,"
        "iniciada_en) values(1,1,'CA1','bloqueada','[]',now())"
    )  # telefono_id inexistente (FK)

    command.downgrade(cfg, "0001")
    insp = inspect(engine)
    assert not (TABLAS_2A & set(insp.get_table_names()))
    columnas = {c["name"] for c in insp.get_columns("campana_clientes")}
    assert "reservado_por" not in columnas and "ultimo_resultado" not in columnas
    with engine.begin() as conn:
        assert conn.execute(text("select intentos from campana_clientes")).scalar() == 2
    command.upgrade(cfg, "head")
    command.check(cfg)
    engine.dispose()


def test_las_tipificaciones_exigen_usuario_para_origen_agente_y_llamada_unica(url_pg):
    cfg = _cfg(url_pg)
    command.upgrade(cfg, "head")
    engine = create_engine(url_pg)
    with engine.begin() as conn:
        _sembrar_fase_1(conn)
        conn.execute(
            text(
                "insert into telefonos(cliente_id,numero_e164,tipo_linea,prioridad,creado_en)"
                " values(1,'+573001234567','movil',1,now())"
            )
        )
        conn.execute(
            text(
                "insert into llamadas(campana_cliente_id,telefono_id,usuario_id,call_sid,estado,"
                "motivos_bloqueo,iniciada_en) values(1,1,1,'CA1','completada','[]',now())"
            )
        )

    def insertar(origen, usuario, llamada):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into tipificaciones(campana_cliente_id,canal,origen,usuario_id,"
                    "llamada_id,resultado,contacto_directo,creado_en) "
                    "values(1,'voz',:o,:u,:l,'rechazo',true,now())"
                ),
                {"o": origen, "u": usuario, "l": llamada},
            )

    with pytest.raises(IntegrityError):
        insertar("agente", None, None)  # origen agente sin usuario
    insertar("agente", 1, 1)
    with pytest.raises(IntegrityError):
        insertar("agente", 1, 1)  # llamada ya tipificada (UNIQUE)
    insertar("agente_ia", None, None)  # varias sin llamada son válidas
    insertar("agente_ia", None, None)
    engine.dispose()
