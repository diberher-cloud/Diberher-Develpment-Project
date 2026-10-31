"""Evaluaciones por API y CLI (casos E2-E5)."""

import json

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.modulos.agente_ia.configuracion import huella_evaluacion
from app.modulos.agente_ia.modelos import EvaluacionIA
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import Cliente
from app.modulos.conversaciones.modelos import Conversacion

API = "/api/v1"


def test_e2_evaluacion_offline_por_api(client, h_admin, correr_trabajos, reloj, db):
    r = client.post(f"{API}/ia/evaluaciones", json={"modo": "offline"}, headers=h_admin)
    assert r.status_code == 202 and r.json()["estado"] == "pendiente"
    assert (
        client.post(f"{API}/ia/evaluaciones", json={"modo": "offline"}, headers=h_admin).json()[
            "error"
        ]["codigo"]
        == "EVALUACION_EN_CURSO"
    )
    antes = (db.scalar(select(func.count(Conversacion.id))), db.scalar(select(func.count(Cliente.id))),
             db.scalar(select(func.count(Campana.id))))  # fmt: skip
    correr_trabajos(reloj())
    j = client.get(f"{API}/ia/evaluaciones/{r.json()['id']}", headers=h_admin).json()
    assert j["estado"] == "completada" and j["aprobada"] is True
    assert (
        j["huella"] == huella_evaluacion(1)
        and j["resumen"]["total"] == 40
        and j["resumen"]["aprobados"] == 40
    )
    assert j["casos"][0].keys() == {"id", "categoria", "aprobado", "fallos"}
    despues = (db.scalar(select(func.count(Conversacion.id))), db.scalar(select(func.count(Cliente.id))),
               db.scalar(select(func.count(Campana.id))))  # fmt: skip
    assert antes == despues == (0, 0, 0)  # E5: la evaluación no toca la BD de la aplicación
    lista = client.get(f"{API}/ia/evaluaciones?modo=offline", headers=h_admin).json()
    assert lista["total"] == 1


def test_e3_online_sin_proveedor(client, h_admin, esc):
    c = esc.campana(tipo="cobranza")
    r = client.post(
        f"{API}/ia/evaluaciones", json={"modo": "online", "campana_id": c.id}, headers=h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_PROVEEDOR_NO_CONFIGURADO"
    assert (
        client.post(f"{API}/ia/evaluaciones", json={"modo": "online"}, headers=h_admin).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/ia/evaluaciones", json={"modo": "offline", "campana_id": c.id}, headers=h_admin
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{API}/ia/evaluaciones", json={"modo": "offline", "extra": 1}, headers=h_admin
        ).status_code
        == 422
    )


def test_evaluacion_con_patron_registra_y_no_cuenta(client, h_admin, correr_trabajos, reloj, db):
    r = client.post(
        f"{API}/ia/evaluaciones", json={"modo": "offline", "casos": "opt_out_*"}, headers=h_admin
    )
    correr_trabajos(reloj())
    e = db.get(EvaluacionIA, r.json()["id"])
    assert e.patron_casos == "opt_out_*" and e.resumen["total"] == 3 and e.aprobada is True


def test_cli_offline_y_real_sin_clave(tmp_path, capsys, monkeypatch):
    from app import evaluacion_ia

    salida = tmp_path / "informe.json"
    assert evaluacion_ia.main(["--casos", "humano_*", "--salida", str(salida)]) == 0
    datos = json.loads(salida.read_text())
    assert datos["modo"] == "offline" and datos["resumen"]["total"] == 2
    assert "2/2 casos aprobados" in capsys.readouterr().out
    assert evaluacion_ia.main(["--real"]) == 2
    assert get_settings().ia_proveedor == "falso"
    assert evaluacion_ia.main(["--casos", "no_existe_*"]) == 2


@pytest.mark.parametrize("campo", ["id", "categoria", "turnos_cliente", "expectativas"])
def test_caso_invalido_se_rechaza(tmp_path, campo):
    from app.modulos.agente_ia.evaluacion import casos

    caso = json.loads(next(casos.DIRECTORIO_CASOS.glob("humano_literal.json")).read_text())
    caso.pop(campo)
    with pytest.raises(casos.CasoInvalido):
        casos.validar(caso, {})
    caso = json.loads(next(casos.DIRECTORIO_CASOS.glob("humano_literal.json")).read_text())
    caso["expectativas"]["inventada"] = True
    with pytest.raises(casos.CasoInvalido):
        casos.validar(caso, {})
