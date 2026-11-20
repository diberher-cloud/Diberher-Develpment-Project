"""Evaluaciones por API y CLI (casos E2-E5)."""

import json
import socket

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.modulos.agente_ia.configuracion import huella_evaluacion
from app.modulos.agente_ia.modelos import EvaluacionIA
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import Cliente
from app.modulos.conversaciones.modelos import Conversacion

API = "/api/v1"


def esperar(correr, reloj, db, evaluacion_id, maximo=120):
    """La evaluación corre en un subproceso: el trabajo se reprograma hasta que termina."""
    import time

    for _ in range(maximo * 4):
        correr(reloj())
        db.expire_all()
        e = db.get(EvaluacionIA, evaluacion_id)
        if e.estado in ("completada", "fallida"):
            return e
        reloj.avanzar(seconds=5)
        time.sleep(0.25)
    raise AssertionError("la evaluación no terminó")


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
    esperar(correr_trabajos, reloj, db, r.json()["id"])
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
    e = esperar(correr_trabajos, reloj, db, r.json()["id"])
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


def test_la_evaluacion_no_sustituye_globales_del_worker(
    client, h_admin, correr_trabajos, reloj, db
):
    """El subproceso aísla bus, proveedor de WhatsApp y cliente de IA del proceso principal."""
    from app.integraciones.whatsapp import fabrica
    from app.modulos.agente_ia import llm as llm_mod
    from app.modulos.agente_ia.llm_falso import ClienteLLMFalso
    from app.tiempo_real import bus

    cliente = ClienteLLMFalso([])
    llm_mod.establecer_cliente_llm(cliente)
    bus_antes, prov_antes = bus.obtener_bus(), fabrica._instancia
    r = client.post(
        f"{API}/ia/evaluaciones", json={"modo": "offline", "casos": "humano_*"}, headers=h_admin
    )
    esperar(correr_trabajos, reloj, db, r.json()["id"])
    assert llm_mod._cliente is cliente and bus.obtener_bus() is bus_antes
    assert fabrica._instancia is prov_antes


def test_timeout_mata_el_subproceso_y_marca_fallida(
    client, h_admin, correr_trabajos, reloj, db, monkeypatch
):
    from app.config import get_settings
    from app.modulos.agente_ia.evaluacion import servicio

    monkeypatch.setattr(get_settings(), "ia_evaluacion_timeout_segundos", 30)
    lanzados = []

    def colgado(e):
        import subprocess
        import sys

        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)"], start_new_session=True
        )
        lanzados.append(p)
        return {
            "pid": p.pid,
            "inicio": servicio._inicio_proceso(p.pid),
            "host": socket.gethostname(),
            "ruta": "/tmp/evaluacion_ia_inexistente/informe.json",
        }

    monkeypatch.setattr(servicio, "_lanzar", colgado)
    r = client.post(f"{API}/ia/evaluaciones", json={"modo": "offline"}, headers=h_admin)
    correr_trabajos(reloj())
    reloj.avanzar(seconds=60)
    e = esperar(correr_trabajos, reloj, db, r.json()["id"], maximo=10)
    assert e.estado == "fallida" and e.resumen == {"error": "TIMEOUT"}
    lanzados[0].wait(timeout=10)
    assert lanzados[0].returncode is not None


def test_gancho_de_agotamiento_marca_fallida(db, reloj):
    from datetime import UTC, datetime

    from app.modulos.agente_ia.evaluacion import servicio

    e = EvaluacionIA(modo="offline", canal="chat", prompt_version=1, huella="h", estado="en_curso",
                     resumen={}, casos=[], creado_en=datetime(2026, 10, 23, tzinfo=UTC))  # fmt: skip
    db.add(e)
    db.commit()
    servicio.evaluacion_agotada(db, {"evaluacion_id": e.id}, "AGOTADO", reloj())
    db.commit()
    assert db.get(EvaluacionIA, e.id).estado == "fallida"
