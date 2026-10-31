"""Migración 0004 sobre PostgreSQL real (marcador `postgres`; TEST_DATABASE_URL)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.postgres
RAIZ = Path(__file__).parent.parent.parent
TABLAS_2C = {
    "configuracion_global", "configuracion_ia_campana", "ofertas_campana", "promesa_cuotas",
    "uso_ia", "historial_ia", "acciones_ia", "errores_ia", "instrucciones_supervisor",
    "bloqueos_turno_ia", "evaluaciones_ia",
}  # fmt: skip


def _cfg(url):
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def url_pg():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definido")
    command.downgrade(_cfg(url), "base")
    yield url
    command.downgrade(_cfg(url), "base")


def test_upgrade_downgrade_con_datos_de_2b(url_pg):
    cfg = _cfg(url_pg)
    command.upgrade(cfg, "0003")
    engine = create_engine(url_pg)
    with engine.begin() as c:
        c.execute(
            text(
                "insert into conversaciones(clave_abierta,numero_cliente_e164,numero_empresa_e164,estado,atendida_por,iniciada_por,ultimo_mensaje_en,abierta_en,mensajes_sin_leer,identidad_verificada,identidad_intentos,turnos_ia,costo_usd_acumulado) values('k','+573001234567','+573000000001','abierta','sin_asignar','cliente',now(),now(),0,false,0,0,0)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert TABLAS_2C <= set(inspect(c).get_table_names())
        assert (
            c.execute(
                text("select valor::text from configuracion_global where clave='ia_activa'")
            ).scalar()
            == "true"
        )
        assert c.execute(text("select count(*) from conversaciones")).scalar() == 1
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(
            text(
                "insert into errores_ia(campana_id,codigo,transitorio,creado_en) values(1,'X',false,now())"
            )
        )
    command.downgrade(cfg, "0003")
    with engine.connect() as c:
        assert not (TABLAS_2C & set(inspect(c).get_table_names()))
        assert c.execute(text("select count(*) from conversaciones")).scalar() == 1
    command.upgrade(cfg, "head")
    engine.dispose()
