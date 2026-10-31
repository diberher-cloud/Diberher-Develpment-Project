"""Evaluación offline obligatoria (fase-2c.md §7): 40 casos con el cliente de Claude falso."""

import pytest

from app.modulos.agente_ia.evaluacion import casos as casos_mod
from app.modulos.agente_ia.evaluacion import harness

CASOS = casos_mod.cargar_casos()


def test_hay_cuarenta_casos_con_ids_unicos():
    ids = [c["id"] for c in CASOS]
    assert len(ids) == 40 and len(set(ids)) == 40


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
def test_caso_offline(caso):
    r = harness.ejecutar_caso(caso)
    assert r.aprobado, r.fallos
