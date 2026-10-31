"""Supervisión en vivo, acciones, uso, historial, métricas y permisos (casos S)."""

import json

import pytest
from ia import escenario_ia, escribir, herramienta, usar_llm
from sqlalchemy import select

from app.modulos.agente_ia.modelos import HistorialIA
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.modelos import Conversacion

API = "/api/v1"


@pytest.fixture()
def s(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario, cabeceras, admin):
    from types import SimpleNamespace

    ctx = escenario_ia(esc, crear_usuario, db)
    usar_llm(
        [
            {"herramientas": [{"name": "verificar_identidad", "input": {"numero_documento": "1020304050"}}],
             "thinking": "razono"},
            herramienta("consultar_obligacion"),
            {"texto": "Su saldo en mora es de $ 300.000."},
        ]
    )  # fmt: skip
    escribir(client, firmar_twilio, correr_trabajos, reloj, "Mi cédula es 1020304050")
    db.expire_all()
    cid = db.scalar(select(Conversacion.id))
    return SimpleNamespace(
        client=client, cid=cid, ctx=ctx, h_admin=cabeceras(admin), h_agente=cabeceras(ctx.agente),
        supervisor=crear_usuario("supervisor"), cabeceras=cabeceras, db=db,
    )  # fmt: skip


def test_s1_listado_y_filtros(s):
    h = s.h_admin
    r = s.client.get(f"{API}/supervision/ia/conversaciones", headers=h)
    j = r.json()
    assert r.status_code == 200 and j["total"] == 1
    ia = j["items"][0]["ia"]
    assert ia["identidad_verificada"] and ia["turnos"] == 1 and ia["modelo"] == "claude-opus-5-5"
    assert (
        ia["ultima_accion"]["herramienta"] == "consultar_obligacion"
        and ia["turno_en_curso"] is False
    )
    assert float(ia["costo_usd"]) > 0 and ia["gestion"] is None
    q = lambda p: s.client.get(f"{API}/supervision/ia/conversaciones?{p}", headers=h).json()[
        "total"
    ]  # noqa: E731
    assert q("identidad=verificada") == 1 and q("identidad=no_verificada") == 0
    assert q("con_gestion=true") == 0 and q("con_gestion=false") == 1
    assert (
        q("estado=cerrada") == 0 and q("atendida_por=humano") == 0 and q("atendida_por=todas") == 1
    )
    assert q(f"campana_id={s.ctx.campana.id}") == 1 and q("campana_id=99") == 0
    assert q("desde=2026-10-23&hasta=2026-10-23") == 1 and q("desde=2026-10-24") == 0


def test_s2_acciones_enmascaradas_y_dueno(s):
    r = s.client.get(f"{API}/conversaciones/{s.cid}/acciones-ia", headers=s.h_admin)
    a = r.json()
    assert [x["herramienta"] for x in a] == ["verificar_identidad", "consultar_obligacion"]
    assert a[0]["entrada"] == {"numero_documento": "***4050"} and a[1]["resultado"]["obligacion"]
    # el agente solo ve las suyas; si es dueño no ve resultados de consultas
    assert (
        s.client.get(f"{API}/conversaciones/{s.cid}/acciones-ia", headers=s.h_agente).status_code
        == 403
    )
    s.client.post(
        f"{API}/conversaciones/{s.cid}/asignar",
        json={"usuario_id": s.ctx.agente.id},
        headers=s.h_admin,
    )
    mios = s.client.get(f"{API}/conversaciones/{s.cid}/acciones-ia", headers=s.h_agente).json()
    assert mios[1]["resultado"] is None and mios[0]["resultado"] == {"verificada": True}


def test_s3_uso(s):
    j = s.client.get(f"{API}/conversaciones/{s.cid}/uso-ia", headers=s.h_admin).json()
    assert j["total"]["llamadas"] == 3 and len(j["llamadas"]) == 3
    assert (
        j["total"]["cache_creation_input_tokens"] == 2000
        and j["total"]["cache_read_input_tokens"] == 4000
    )
    t = j["total"]
    esperado = round(4000 / (t["input_tokens"] + 4000 + 2000), 4)
    assert t["tasa_cache"] == esperado
    assert j["llamadas"][0]["request_id"].startswith("req_falso")
    assert len(j["total"]["costo_usd"].split(".")[1]) == 6


def test_s4_metricas(s):
    j = s.client.get(
        f"{API}/supervision/ia/metricas?campana_id={s.ctx.campana.id}&desde=2026-10-23&hasta=2026-10-23",
        headers=s.h_admin,
    ).json()
    assert (
        j["conversaciones"] == 1
        and j["con_identidad_verificada"] == 1
        and j["tasa_verificacion"] == 1.0
    )
    assert (
        j["acuerdos"] == {"numero": 0, "monto_total": "0.00"} and j["costo_por_acuerdo_usd"] is None
    )
    assert j["tokens"]["cache_escritura"] == 2000 and j["tokens"]["cache_lectura"] == 4000
    assert j["tiempo_respuesta_ms"]["p50"] is not None and j["errores"] == {} and j["guardas"] == {}
    assert (
        s.client.get(f"{API}/supervision/ia/metricas?campana_id=999", headers=s.h_admin).status_code
        == 404
    )
    assert (
        s.client.get(
            f"{API}/supervision/ia/metricas?desde=2026-10-25&hasta=2026-10-24", headers=s.h_admin
        ).status_code
        == 422
    )


def test_s5_historial_solo_admin_sin_thinking(s):
    r = s.client.get(f"{API}/conversaciones/{s.cid}/historial-ia", headers=s.h_admin)
    assert r.status_code == 200
    texto = json.dumps(r.json())
    assert '"omitido": true' in texto and "razono" not in texto
    assert s.db.scalar(select(Auditoria).where(Auditoria.accion == "ia.historial_ver")) is not None
    h_sup = s.cabeceras(s.supervisor)
    assert (
        s.client.get(f"{API}/conversaciones/{s.cid}/historial-ia", headers=h_sup).status_code == 403
    )
    # el historial guardado conserva el bloque thinking con su firma
    fila = [f for f in s.db.scalars(select(HistorialIA)) if f.rol == "assistant"][0]
    assert fila.contenido[0]["type"] == "thinking" and fila.contenido[0]["signature"] == "falso"


@pytest.mark.parametrize(
    "metodo,ruta,cuerpo,permitidos",
    [
        ("GET", "/campanas/{c}/ia", None, {"administrador", "supervisor"}),
        ("GET", "/campanas/{c}/ofertas", None, {"administrador", "supervisor"}),
        ("GET", "/configuracion/ia", None, {"administrador", "supervisor"}),
        ("PUT", "/configuracion/ia", {"ia_activa": True}, {"administrador"}),
        ("GET", "/supervision/ia/conversaciones", None, {"administrador", "supervisor"}),
        ("GET", "/supervision/ia/metricas", None, {"administrador", "supervisor"}),
        ("GET", "/conversaciones/{i}/uso-ia", None, {"administrador", "supervisor"}),
        ("GET", "/conversaciones/{i}/instrucciones", None, {"administrador", "supervisor"}),
        ("POST", "/conversaciones/{i}/traspasar", {}, {"administrador", "supervisor"}),
        ("GET", "/conversaciones/{i}/historial-ia", None, {"administrador"}),
        ("GET", "/ia/evaluaciones", None, {"administrador", "supervisor"}),
        ("POST", "/ia/evaluaciones", {"modo": "offline"}, {"administrador"}),
    ],
)
def test_s6_matriz_de_permisos(s, metodo, ruta, cuerpo, permitidos):
    url = API + ruta.format(c=s.ctx.campana.id, i=s.cid)
    cabs = {
        "administrador": s.h_admin,
        "supervisor": s.cabeceras(s.supervisor),
        "agente": s.h_agente,
    }
    for rol, h in cabs.items():
        r = s.client.request(metodo, url, headers=h, json=cuerpo)
        if rol in permitidos:
            assert r.status_code != 403, (rol, r.text)
        else:
            assert r.status_code == 403, (rol, r.status_code)
    assert s.client.request(metodo, url, json=cuerpo).status_code == 401


def test_conversacion_incluye_bloque_ia_y_costo_solo_para_gestores(s):
    j = s.client.get(f"{API}/conversaciones/{s.cid}", headers=s.h_admin).json()["ia"]
    assert j["identidad_verificada"] and j["turnos"] == 1 and j["aviso_enviado"] is True
    assert j["costo_usd"] is not None and j["puede_devolver_ia"] is False and j["gestion"] is None
    s.client.post(
        f"{API}/conversaciones/{s.cid}/asignar",
        json={"usuario_id": s.ctx.agente.id},
        headers=s.h_admin,
    )
    g = s.client.get(f"{API}/conversaciones/{s.cid}", headers=s.h_agente).json()["ia"]
    assert g["costo_usd"] is None and g["modelo"] == "claude-opus-5-5"
    assert g["puede_devolver_ia"] is True and g["motivos_no_devolver"] == []


def test_eventos_ia_no_llegan_a_agentes():
    from app.tiempo_real.conexiones import Conexion, debe_recibir

    ev = {"tipo": "ia.turno", "datos": {"conversacion_id": 1, "usuario_asignado_id": 7}}
    assert debe_recibir(Conexion(1, "supervisor"), ev) and debe_recibir(
        Conexion(2, "administrador"), ev
    )
    assert not debe_recibir(Conexion(7, "agente"), ev)
