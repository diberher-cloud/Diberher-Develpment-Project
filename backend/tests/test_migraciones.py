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
    assert _tablas(ruta) == TABLAS
    with sqlite3.connect(ruta) as con:
        filas = con.execute(
            "select tipo_campana, version, activa from politicas_cumplimiento order by tipo_campana"
        ).fetchall()
        assert filas == [("cobranza", 1, 1), ("venta", 1, 1)]
        assert con.execute("select count(*) from festivos").fetchone()[0] == 0
    command.downgrade(cfg, "base")
    assert _tablas(ruta) == set()


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
