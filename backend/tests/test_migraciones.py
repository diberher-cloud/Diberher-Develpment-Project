import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config

RAIZ = Path(__file__).parent.parent
TABLAS = {
    "usuarios", "campanas", "clientes", "telefonos", "campana_clientes", "importaciones",
    "importacion_errores", "exclusiones", "politicas_cumplimiento", "festivos", "auditoria",
}  # fmt: skip
TABLAS_2A = {
    "campana_agentes", "estados_agente", "historial_estados_agente", "intentos_contacto",
    "llamadas", "eventos_llamada", "grabaciones", "tipificaciones", "promesas_pago", "ventas",
}  # fmt: skip


def _config(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tablas(ruta: Path) -> set[str]:
    with sqlite3.connect(ruta) as con:
        filas = con.execute("select name from sqlite_master where type='table'").fetchall()
    return {f[0] for f in filas} - {"alembic_version"}


def test_upgrade_downgrade_y_semillas(tmp_path):
    ruta = tmp_path / "mig.db"
    cfg = _config(f"sqlite:///{ruta}")
    command.upgrade(cfg, "head")
    assert _tablas(ruta) == TABLAS | TABLAS_2A
    with sqlite3.connect(ruta) as con:
        filas = con.execute(
            "select tipo_campana, version, activa from politicas_cumplimiento order by tipo_campana"
        ).fetchall()
        assert filas == [("cobranza", 1, 1), ("venta", 1, 1)]
        assert con.execute("select count(*) from festivos").fetchone()[0] == 0
    command.downgrade(cfg, "base")
    assert _tablas(ruta) == set()


def test_0002_upgrade_downgrade_upgrade_conserva_datos_de_fase_1(tmp_path):
    ruta = tmp_path / "m2.db"
    cfg = _config(f"sqlite:///{ruta}")
    command.upgrade(cfg, "0001")
    with sqlite3.connect(ruta) as con:
        con.execute(
            "insert into usuarios(email,nombre,rol,password_hash,activo,creado_en,actualizado_en)"
            " values('a@a.co','A','administrador','x',1,'2026-01-01','2026-01-01')"
        )
        con.execute(
            "insert into campanas(nombre,tipo,estado,max_intentos,intervalo_reintento_minutos,"
            "creado_por,creado_en,actualizado_en) values('c','cobranza','activa',3,60,1,"
            "'2026-01-01','2026-01-01')"
        )
        con.execute(
            "insert into clientes(tipo_documento,numero_documento,nombre,creado_en,actualizado_en)"
            " values('CC','1','N','2026-01-01','2026-01-01')"
        )
        con.execute(
            "insert into campana_clientes(campana_id,cliente_id,estado,datos_adicionales,intentos,"
            "creado_en) values(1,1,'pendiente','{}',2,'2026-01-01')"
        )
    command.upgrade(cfg, "head")
    assert _tablas(ruta) == TABLAS | TABLAS_2A
    with sqlite3.connect(ruta) as con:
        fila = con.execute(
            "select estado, intentos, reservado_por, reservado_hasta, ultimo_resultado,"
            " ultima_gestion_en from campana_clientes"
        ).fetchone()
        assert fila == ("pendiente", 2, None, None, None, None)
        ddl = con.execute("select sql from sqlite_master where name='campana_clientes'").fetchone()[
            0
        ]
        assert "ck_campana_clientes_estado" in ddl and "ck_campana_clientes_ultimo_resultado" in ddl
        # Las políticas de Fase 1 no se reescriben.
        cfg_pol = con.execute("select configuracion from politicas_cumplimiento").fetchone()[0]
        assert "entrantes" not in cfg_pol
    command.downgrade(cfg, "0001")
    assert _tablas(ruta) == TABLAS
    with sqlite3.connect(ruta) as con:
        columnas = {c[1] for c in con.execute("pragma table_info(campana_clientes)")}
        assert "reservado_por" not in columnas and "ultimo_resultado" not in columnas
        assert con.execute("select intentos from campana_clientes").fetchone() == (2,)
    command.upgrade(cfg, "head")
    assert _tablas(ruta) == TABLAS | TABLAS_2A


def test_sin_diferencias_entre_modelos_y_migracion(tmp_path):
    ruta = tmp_path / "check.db"
    cfg = _config(f"sqlite:///{ruta}")
    command.upgrade(cfg, "head")
    command.check(cfg)  # lanza CommandError si hay diferencias


def test_cli_extremo_a_extremo(tmp_path):
    ruta = tmp_path / "cli.db"
    env = {
        **os.environ,
        "ENTORNO": "test",
        "DATABASE_URL": f"sqlite:///{ruta}",
        "ADMIN_PASSWORD": "ClaveSegura123",
        "BCRYPT_COSTE": "4",
    }

    def correr(*args):
        return subprocess.run(
            [sys.executable, *args], cwd=RAIZ, env=env, capture_output=True, text=True, timeout=120
        )

    assert correr("-m", "alembic", "upgrade", "head").returncode == 0
    r = correr(
        "-m", "app.cli", "crear-admin", "--email", "admin@empresa.co", "--nombre", "Ana Admin"
    )
    assert r.returncode == 0, r.stderr
    again = correr(
        "-m", "app.cli", "crear-admin", "--email", "admin@empresa.co", "--nombre", "Ana Admin"
    )
    assert again.returncode == 1
    r = correr("-m", "app.cli", "generar-festivos", "--desde", "2025", "--hasta", "2028")
    assert r.returncode == 0 and "2026: creados=18" in r.stdout
    r = correr("-m", "app.cli", "generar-festivos", "--desde", "2025", "--hasta", "2028")
    assert "2026: creados=0 existentes=18" in r.stdout
    assert (
        correr("-m", "app.cli", "generar-festivos", "--desde", "1900", "--hasta", "2028").returncode
        == 2
    )
    with sqlite3.connect(ruta) as con:
        assert con.execute("select count(*) from festivos").fetchone()[0] == 17 + 18 * 3
        assert con.execute("select rol, activo from usuarios").fetchall() == [("administrador", 1)]


@pytest.mark.postgres
def test_migracion_postgres():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definido")
    cfg = _config(url)
    command.upgrade(cfg, "head")
    command.check(cfg)
    command.downgrade(cfg, "base")
