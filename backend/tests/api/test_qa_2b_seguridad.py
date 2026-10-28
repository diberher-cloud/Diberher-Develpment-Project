"""QA 2B, seguridad: firmas de webhooks, IDOR entre agentes, número completo, lista blanca de
variables, simulación y datos personales en logs/auditoría/trabajos."""

import json
import logging
import re

import pytest
from escenario import cab
from sqlalchemy import func, select
from wa import (
    EMPRESA,
    NUMERO,
    RUTA_ENTRANTE,
    RUTA_ESTADO,
    autorizar,
    clave,
    contexto,
    crear_conv,
    entrante,
    params_entrante,
    plantilla,
)

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, EventoMensaje, Mensaje
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.whatsapp.modelos import AutorizacionCanal
from app.trabajos.modelos import Trabajo

API = "/api/v1"
CONV = f"{API}/conversaciones"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def _nada_en_bd(db):
    return (
        db.scalar(select(func.count()).select_from(Mensaje)),
        db.scalar(select(func.count()).select_from(Trabajo)),
        db.scalar(select(func.count()).select_from(EventoMensaje)),
        db.scalar(select(func.count()).select_from(Conversacion)),
    )


# --- firmas de webhooks ---
@pytest.mark.parametrize("ruta", [RUTA_ENTRANTE, RUTA_ESTADO])
def test_firma_calculada_para_otra_url_otro_host_o_otro_token_es_403(
    client, db, firmar_twilio, ruta
):
    from conftest import BASE_URL, firma_independiente

    p = (
        params_entrante()
        if ruta == RUTA_ENTRANTE
        else {"MessageSid": "SMx", "MessageStatus": "delivered"}
    )
    otra = RUTA_ESTADO if ruta == RUTA_ENTRANTE else RUTA_ENTRANTE
    firmas = {
        "otra ruta de WhatsApp": firma_independiente(BASE_URL + otra, p),
        "ruta de voz": firma_independiente(BASE_URL + "/api/v1/telefonia/webhooks/estado", p),
        "otro host": firma_independiente("https://atacante.example" + ruta, p),
        "http en vez de https": firma_independiente(BASE_URL.replace("https", "http") + ruta, p),
        "barra final": firma_independiente(BASE_URL + ruta + "/", p),
        "con query": firma_independiente(BASE_URL + ruta + "?x=1", p),
        "otro token": firma_independiente(BASE_URL + ruta, p, token="otro-token"),
        "parametros alterados": firma_independiente(BASE_URL + ruta, {**p, "Body": "otro"}),
        "vacía": "",
        "basura": "!!!no-es-base64!!!",
        "espacios": "   ",
    }
    for nombre, firma in firmas.items():
        r = client.post(ruta, data=p, headers={"X-Twilio-Signature": firma})
        assert r.status_code == 403, (nombre, r.text)
        assert r.json()["error"]["codigo"] == "FIRMA_INVALIDA", nombre
    assert _nada_en_bd(db) == (0, 0, 0, 0)


@pytest.mark.parametrize("ruta", [RUTA_ENTRANTE, RUTA_ESTADO])
def test_la_query_string_forma_parte_de_lo_firmado(client, db, firmar_twilio, ruta):
    p = (
        params_entrante()
        if ruta == RUTA_ENTRANTE
        else {"MessageSid": "SMx", "MessageStatus": "delivered"}
    )
    kw = firmar_twilio(ruta, p)  # firmada SIN query
    assert client.post(ruta + "?inyectado=1", **kw).status_code == 403
    kw = firmar_twilio(ruta, p, consulta="a=1")
    assert client.post(ruta + "?a=1", **kw).status_code in (200, 204)


@pytest.mark.parametrize("ruta", [RUTA_ENTRANTE, RUTA_ESTADO])
@pytest.mark.parametrize(
    "contenido",
    [
        {"json": {"MessageSid": "SM1"}},
        {"content": b"", "headers": {"content-type": "application/x-www-form-urlencoded"}},
        {
            "content": b"\xff\xfe\x00",
            "headers": {"content-type": "application/x-www-form-urlencoded"},
        },
        {"content": b"--x", "headers": {"content-type": "multipart/form-data; boundary=x"}},
    ],
)
def test_cuerpos_raros_sin_firma_nunca_son_500(client, db, ruta, contenido):
    r = client.post(ruta, **contenido)
    assert r.status_code in (400, 403, 422), r.status_code
    assert _nada_en_bd(db) == (0, 0, 0, 0)


def test_un_entrante_firmado_para_el_numero_de_otro_sender_no_deja_rastro(
    client, db, firmar_twilio, ctx
):
    p = params_entrante()
    p["To"] = "whatsapp:+573119999999"
    from wa import RUTA_ENTRANTE as ruta

    assert client.post(ruta, **firmar_twilio(ruta, p)).status_code == 200
    assert _nada_en_bd(db) == (0, 0, 0, 0)


# --- IDOR entre agentes ---
@pytest.fixture()
def ajena(db, esc, ctx, reloj, crear_usuario):
    """Conversación de OTRO agente (con registro, mensajes y un medio) + el agente atacante."""
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    cc2 = esc.registro(ctx.campana, numeros=("+573112223344",), nombre="Cliente Ajeno")
    conv = crear_conv(db, reloj(), numero="+573112223344", cc=cc2, dueno=Humano(otro.id))
    m = Mensaje(
        conversacion_id=conv.id,
        numero_cliente_e164="+573112223344",
        direccion="entrante",
        autor="cliente",
        tipo="media",
        cuerpo="mi cédula es 1000999888",
        estado="recibido",
        creado_en=reloj(),
        procesado_en=reloj(),
        media=[
            {
                "indice": 0,
                "tipo_contenido": "image/png",
                "categoria": "imagen",
                "url_proveedor": "https://media.falso.invalid/abc/image/png",
            }
        ],
    )
    db.add(m)
    db.commit()
    return conv, m, otro, cc2


def _intentos(conv, m, atacante_id):
    k = clave()
    return [
        ("GET", f"{CONV}/{conv.id}", None),
        ("GET", f"{CONV}/{conv.id}/mensajes", None),
        ("GET", f"{CONV}/{conv.id}/ficha", None),
        ("GET", f"{CONV}/{conv.id}/mensajes/{m.id}/media/0", None),
        ("GET", f"{CONV}/{conv.id}/registros-candidatos", None),
        ("POST", f"{CONV}/{conv.id}/mensajes", {"texto": "intruso", "idempotencia_clave": k}),
        ("POST", f"{CONV}/{conv.id}/plantillas", {"plantilla_id": 1, "idempotencia_clave": k}),
        ("POST", f"{CONV}/{conv.id}/leida", None),
        ("POST", f"{CONV}/{conv.id}/tomar", None),
        ("POST", f"{CONV}/{conv.id}/liberar", None),
        ("POST", f"{CONV}/{conv.id}/cerrar", {}),
        ("POST", f"{CONV}/{conv.id}/opt-out", {"alcance": "todos"}),
        (
            "POST",
            f"{CONV}/{conv.id}/autorizacion",
            {"finalidad": "cobranza", "evidencia": "intruso aquí"},
        ),
        ("PUT", f"{CONV}/{conv.id}/registro", {"campana_cliente_id": 1}),
        ("POST", f"{CONV}/{conv.id}/asignar", {"usuario_id": atacante_id}),
    ]


def test_un_agente_no_ve_ni_modifica_nada_de_la_conversacion_de_otro(client, db, ctx, ajena, reloj):
    conv, m, otro, _ = ajena
    antes = (
        db.scalar(select(func.count()).select_from(Mensaje)),
        db.scalar(select(func.count()).select_from(Exclusion)),
        db.scalar(select(func.count()).select_from(AutorizacionCanal)),
        db.scalar(select(func.count()).select_from(Trabajo)),
        db.scalar(select(func.count()).select_from(Auditoria)),
    )
    for metodo, ruta, cuerpo in _intentos(conv, m, ctx.agente.id):
        r = client.request(metodo, ruta, json=cuerpo, headers=cab(ctx.agente))
        permitidos = (403, 404, 409) if ruta.endswith("/tomar") else (403, 404)
        assert r.status_code in permitidos, (metodo, ruta, r.status_code, r.text)
        txt = r.text
        assert "Cliente Ajeno" not in txt and "1000999888" not in txt, (ruta, txt)
        assert "3112223344" not in txt, (ruta, txt)
    db.expire_all()
    c = db.get(Conversacion, conv.id)
    assert (c.estado, c.atendida_por, c.usuario_asignado_id) == ("abierta", "humano", otro.id)
    assert c.mensajes_sin_leer == 0 or c.mensajes_sin_leer == conv.mensajes_sin_leer
    despues = (
        db.scalar(select(func.count()).select_from(Mensaje)),
        db.scalar(select(func.count()).select_from(Exclusion)),
        db.scalar(select(func.count()).select_from(AutorizacionCanal)),
        db.scalar(select(func.count()).select_from(Trabajo)),
        db.scalar(select(func.count()).select_from(Auditoria)),
    )
    assert despues == antes


def test_el_listado_de_un_agente_ignora_filtros_que_apuntan_a_otro_usuario(
    client, ctx, ajena, db, reloj
):
    conv, _, otro, _ = ajena
    for q in (f"usuario_id={otro.id}", "sin_campana=true", f"campana_id={conv.campana_id}"):
        r = client.get(f"{CONV}?{q}", headers=cab(ctx.agente))
        assert r.status_code == 200 and r.json()["total"] == 0, q
        r = client.get(f"{CONV}?{q}&estado=cerrada", headers=cab(ctx.agente))
        assert r.status_code == 200 and r.json()["total"] == 0, q


def test_un_agente_no_toma_conversaciones_de_campanas_ajenas_ni_sin_campana(
    client, db, esc, ctx, reloj, crear_usuario
):
    intruso = crear_usuario("agente")
    esc.estado(intruso, "disponible", reloj())
    sin = crear_conv(db, reloj(), numero="+573114445566", con_cola=True)
    con = crear_conv(db, reloj(), cc=ctx.cc, con_cola=True)
    for c in (sin, con):
        r = client.post(f"{CONV}/{c.id}/tomar", headers=cab(intruso))
        assert r.status_code == 403, (c.id, r.text)
    assert client.post(f"{API}/atencion/tomar-siguiente", headers=cab(intruso)).status_code == 204
    cola = client.get(f"{API}/atencion/cola", headers=cab(intruso)).json()
    assert cola == []
    db.expire_all()
    assert {c.atendida_por for c in db.scalars(select(Conversacion))} == {"sin_asignar"}


def test_el_medio_de_un_mensaje_no_se_sirve_por_otra_conversacion_propia(
    client, db, ctx, ajena, reloj
):
    conv_ajena, m, _, _ = ajena
    propia = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.get(f"{CONV}/{propia.id}/mensajes/{m.id}/media/0", headers=cab(ctx.agente))
    assert r.status_code == 404


def test_la_clave_de_idempotencia_de_otro_agente_no_filtra_su_mensaje(
    client, db, ctx, reloj, crear_usuario, esc
):
    otro = crear_usuario("agente")
    esc.asignar(ctx.campana, otro)
    esc.estado(otro, "disponible", reloj())
    mia = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    cc2 = esc.registro(ctx.campana, numeros=("+573115556677",), nombre="Cliente Dos")
    suya = crear_conv(db, reloj(), numero="+573115556677", cc=cc2, dueno=Humano(otro.id))
    k = clave()
    assert (
        client.post(
            f"{CONV}/{suya.id}/mensajes",
            json={"texto": "SECRETO-DE-OTRO", "idempotencia_clave": k},
            headers=cab(otro),
        ).status_code
        == 202
    )
    r = client.post(
        f"{CONV}/{mia.id}/mensajes",
        json={"texto": "mio", "idempotencia_clave": k},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IDEMPOTENCIA_CONFLICTO"
    assert "SECRETO-DE-OTRO" not in r.text


def test_el_agente_no_usa_el_endpoint_de_plantilla_de_la_consola_con_registro_ajeno(
    client, db, esc, ctx, reloj, crear_usuario
):
    autorizar(db)
    intruso = crear_usuario("agente")
    esc.estado(intruso, "disponible", reloj())
    r = client.post(
        f"{API}/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={"telefono_id": 1, "plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()},
        headers=cab(intruso),
    )
    assert r.status_code in (403, 404)
    assert db.scalar(select(func.count()).select_from(Mensaje)) == 0


# --- número completo ---
NUM_COMPLETO = re.compile(r"3\d{9}")


def _recorre(valor):
    if isinstance(valor, dict):
        for k, v in valor.items():
            yield k
            yield from _recorre(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _recorre(v)
    elif valor is not None:
        yield str(valor)


def test_el_agente_nunca_recibe_el_numero_completo_en_ninguna_respuesta_del_flujo(
    client, firmar_twilio, db, ctx, reloj, esc, correr_trabajos
):
    """Recorre el flujo completo del agente y busca el número en cualquier parte del JSON."""
    autorizar(db)
    ag = cab(ctx.agente)
    respuestas = []

    def llamar(metodo, ruta, **kw):
        r = client.request(metodo, API + ruta, headers=ag, **kw)
        respuestas.append((metodo, ruta, r))
        return r

    entrante(client, firmar_twilio, texto="hola", ProfileName="Cliente")
    correr_trabajos()
    conv = db.scalar(select(Conversacion))
    llamar("GET", "/atencion/cola")
    llamar("GET", "/conversaciones")
    t = llamar("POST", f"/conversaciones/{conv.id}/tomar")
    assert t.status_code == 200, t.text
    llamar("GET", f"/conversaciones/{conv.id}")
    llamar("GET", f"/conversaciones/{conv.id}/mensajes")
    llamar("GET", f"/conversaciones/{conv.id}/registros-candidatos")
    llamar("PUT", f"/conversaciones/{conv.id}/registro", json={"campana_cliente_id": ctx.cc.id})
    llamar("GET", f"/conversaciones/{conv.id}/ficha")
    llamar("GET", f"/whatsapp/plantillas?campana_id={ctx.campana.id}")
    llamar(
        "POST",
        f"/conversaciones/{conv.id}/mensajes",
        json={"texto": "Hola", "idempotencia_clave": clave()},
    )
    llamar(
        "POST",
        f"/conversaciones/{conv.id}/autorizacion",
        json={"finalidad": "cobranza", "evidencia": "dijo que sí por chat"},
    )
    llamar("POST", f"/conversaciones/{conv.id}/leida")
    esc.reservar(ctx.cc, ctx.agente, reloj())
    llamar("GET", f"/consola/registros/{ctx.cc.id}")
    llamar("GET", "/consola/registros")
    llamar("GET", "/consola/campanas")
    llamar("POST", f"/conversaciones/{conv.id}/opt-out", json={"alcance": "whatsapp"})
    llamar("GET", f"/conversaciones/{conv.id}")
    cerrada = db.scalar(select(Conversacion).where(Conversacion.estado == "cerrada"))
    assert cerrada is not None
    assert len(respuestas) > 10
    for metodo, ruta, r in respuestas:
        if r.headers.get("content-type", "").startswith("application/json"):
            for texto in _recorre(r.json()):
                assert not NUM_COMPLETO.search(texto) or texto.strip() == "", (
                    metodo,
                    ruta,
                    texto,
                )
        assert "+573001234567" not in r.text, (metodo, ruta)
        assert "3001234567" not in r.text, (metodo, ruta)


def test_el_supervisor_si_ve_el_numero_completo_pero_el_agente_solo_la_mascara(
    client, db, ctx, reloj, h_supervisor
):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    sup = client.get(f"{CONV}/{conv.id}", headers=h_supervisor).json()
    ag = client.get(f"{CONV}/{conv.id}", headers=cab(ctx.agente)).json()
    assert NUMERO in json.dumps(sup)
    assert NUMERO not in json.dumps(ag)


# --- lista blanca de variables ---
@pytest.mark.parametrize(
    "campo",
    [
        "saldo_total",
        "saldo_mora",
        "monto",
        "deuda",
        "dias_mora",
        "numero_documento",
        "documento",
        "telefono",
        "nombre",
        "Primer_Nombre",
        "primer_nombre ",
        "{{saldo_mora}}",
        "__class__",
        "",
        "empresa;DROP TABLE x",
    ],
)
def test_el_mapeo_rechaza_todo_lo_que_no_este_en_la_lista_blanca(client, db, h_admin, campo):
    p = plantilla(db, sid="HXlista", mapeo={}, activa=False)
    r = client.put(
        f"{API}/whatsapp/plantillas/{p.id}",
        json={"mapeo_variables": {"1": campo, "2": "empresa"}},
        headers=h_admin,
    )
    assert r.status_code == 422, (campo, r.text)
    assert r.json()["error"]["codigo"] in ("PLANTILLA_MAPEO_INVALIDO", "VALIDACION")


def test_una_plantilla_con_mapeo_prohibido_en_la_bd_no_se_envia_ni_se_lista(
    client, db, ctx, esc, reloj
):
    """Defensa en profundidad: aunque alguien escriba `saldo_mora` directo en la BD."""
    autorizar(db)
    ctx.plantilla.mapeo_variables = {"1": "primer_nombre", "2": "saldo_mora"}
    db.commit()
    esc.reservar(ctx.cc, ctx.agente, reloj())
    r = client.post(
        f"{API}/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={"telefono_id": 1, "plantilla_id": ctx.plantilla.id, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PLANTILLA_NO_DISPONIBLE"
    lista = client.get(
        f"{API}/whatsapp/plantillas?campana_id={ctx.campana.id}", headers=cab(ctx.agente)
    ).json()
    assert lista == []
    assert db.scalar(select(func.count()).select_from(Mensaje)) == 0


def test_los_valores_enviados_nunca_contienen_montos_y_no_se_reinterpretan(
    client, db, ctx, esc, reloj, correr_trabajos, proveedor_whatsapp
):
    autorizar(db)
    ctx.cc.producto = "Tarjeta {{1}}\n{{2}}\tOro"
    ctx.cc.saldo_total = 1500000
    db.commit()
    esc.reservar(ctx.cc, ctx.agente, reloj())
    from escenario import telefono_de

    r = client.post(
        f"{API}/consola/registros/{ctx.cc.id}/whatsapp/plantilla",
        json={
            "telefono_id": telefono_de(db, ctx.cc).id,
            "plantilla_id": ctx.plantilla.id,
            "idempotencia_clave": clave(),
        },
        headers=cab(ctx.agente),
    )
    assert r.status_code == 200 and r.json()["permitido"], r.text
    m = db.scalar(select(Mensaje))
    assert set(m.variables) == {"1", "2"}
    texto = json.dumps(m.variables) + (m.cuerpo or "")
    for monto in ("1500000", "1.500.000", "250000", "250.000", "45"):
        assert monto not in texto.replace("Tarjeta Oro", ""), monto
    correr_trabajos()
    enviado = proveedor_whatsapp.enviados[0]
    assert "1500000" not in json.dumps(enviado) and "250000" not in json.dumps(enviado)


# --- PII en logs y trabajos ---
def test_los_fallos_del_proveedor_y_del_worker_no_filtran_texto_ni_numero(
    client, firmar_twilio, db, ctx, reloj, correr_trabajos, proveedor_whatsapp, caplog
):
    secreto = "CONFIDENCIAL-9X7"
    with caplog.at_level(logging.DEBUG):
        entrante(
            client, firmar_twilio, texto=f"{secreto} cédula 1000999888", ProfileName="Doña Ana"
        )
        correr_trabajos()
        conv = db.scalar(select(Conversacion))
        client.post(f"{CONV}/{conv.id}/tomar", headers=cab(ctx.agente))
        r = client.post(
            f"{CONV}/{conv.id}/mensajes",
            json={"texto": f"RESP-{secreto}", "idempotencia_clave": clave()},
            headers=cab(ctx.agente),
        )
        assert r.status_code == 202
        # El proveedor se rompe con un error inesperado que lleva el texto y el número.
        original = proveedor_whatsapp.enviar_texto

        def roto(**kw):
            raise RuntimeError(f"boom {kw['texto']} {kw['destino']}")

        proveedor_whatsapp.enviar_texto = roto
        for _ in range(3):
            correr_trabajos()
            reloj.avanzar(minutes=30)
        proveedor_whatsapp.enviar_texto = original
    for t in db.scalars(select(Trabajo)):
        for campo in (t.ultimo_error, json.dumps(t.payload)):
            assert secreto not in (campo or "") and "3001234567" not in (campo or "")
    for a in db.scalars(select(Auditoria)):
        volcado = json.dumps(a.detalle, default=str)
        assert secreto not in volcado and "3001234567" not in volcado and "Doña Ana" not in volcado
    assert secreto not in caplog.text, "texto de mensaje en los logs"
    assert "3001234567" not in caplog.text and "Doña Ana" not in caplog.text


def test_el_nombre_de_perfil_transitorio_se_borra_de_mensajes_variables(
    client, firmar_twilio, db, ctx, correr_trabajos
):
    entrante(client, firmar_twilio, texto="hola", ProfileName="Nombre Transitorio")
    m = db.scalar(select(Mensaje))
    assert m.variables == {"nombre_perfil": "Nombre Transitorio"}  # antes del worker
    correr_trabajos()
    db.expire_all()
    assert db.scalar(select(Mensaje)).variables is None
    assert db.scalar(select(Conversacion)).nombre_perfil == "Nombre Transitorio"


def test_ni_los_eventos_del_bus_llevan_texto(client, firmar_twilio, db, ctx, correr_trabajos):
    from app.tiempo_real import bus

    visto = []
    original = bus.publicar

    def espia(db_, tipo, datos, *a, **k):
        visto.append((tipo, json.dumps(datos, default=str)))
        return original(db_, tipo, datos, *a, **k)

    bus.publicar = espia
    try:
        entrante(client, firmar_twilio, texto="TEXTO-EN-EVENTO-77", ProfileName="Perfil Evento")
        correr_trabajos()
    finally:
        bus.publicar = original
    assert visto
    for tipo, volcado in visto:
        assert "TEXTO-EN-EVENTO-77" not in volcado and "3001234567" not in volcado, tipo


# --- simulación ---
def test_la_simulacion_con_twilio_no_crea_filas_ni_siquiera_con_rol_administrador():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.seguridad import crear_token

    app = create_app(
        Settings(
            _env_file=None,
            entorno="desarrollo",
            jwt_secreto="x" * 32,
            whatsapp_proveedor="twilio",
            whatsapp_numero_empresa=EMPRESA,
            twilio_account_sid="AC1",
            twilio_auth_token="t",
            twilio_api_key_sid="SK1",
            twilio_api_key_secret="s",
            public_base_url="https://x.co",
        )
    )
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + crear_token(1, "administrador")[0]}
        for ruta, cuerpo in (
            ("/whatsapp/simulacion/entrante", {"numero": "3001234567", "texto": "x"}),
            ("/whatsapp/simulacion/mensajes/1/estado", {"estado": "read"}),
        ):
            assert c.post(API + ruta, json=cuerpo, headers=h).status_code == 404
            assert c.post(API + ruta, json=cuerpo).status_code in (401, 404)


def test_cola_de_atencion_no_expone_filas_de_conversaciones_cerradas_a_agentes(
    client, db, ctx, reloj
):
    conv = crear_conv(db, reloj(), cc=ctx.cc, con_cola=True)
    assert len(client.get(f"{API}/atencion/cola", headers=cab(ctx.agente)).json()) == 1
    from app.modulos.conversaciones import servicio

    servicio.cerrar(db, conv, "inactividad", None, reloj())
    db.commit()
    assert client.get(f"{API}/atencion/cola", headers=cab(ctx.agente)).json() == []
    assert db.scalar(select(ColaAtencion).where(ColaAtencion.estado == "pendiente")) is None


def test_administrador_y_supervisor_leen_pero_no_escriben_en_nombre_del_agente(
    client, db, ctx, reloj, h_admin, h_supervisor
):
    """§4.1: "A/S deben tomar o asignarse la conversación para escribir en ella"."""
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    k = clave()
    for h in (h_admin, h_supervisor):
        assert client.get(f"{CONV}/{conv.id}", headers=h).status_code == 200
        assert client.get(f"{CONV}/{conv.id}/mensajes", headers=h).status_code == 200
        escrituras = [
            ("POST", f"{CONV}/{conv.id}/mensajes", {"texto": "x", "idempotencia_clave": k}),
            ("POST", f"{CONV}/{conv.id}/plantillas", {"plantilla_id": 1, "idempotencia_clave": k}),
            ("POST", f"{CONV}/{conv.id}/leida", None),
            ("POST", f"{CONV}/{conv.id}/opt-out", {"alcance": "whatsapp"}),
            (
                "POST",
                f"{CONV}/{conv.id}/autorizacion",
                {"finalidad": "cobranza", "evidencia": "no soy el dueño"},
            ),
        ]
        for metodo, ruta, cuerpo in escrituras:
            r = client.request(metodo, ruta, json=cuerpo, headers=h)
            assert r.status_code == 403, (ruta, r.status_code, r.text)
            assert r.json()["error"]["codigo"] == "CONVERSACION_NO_ASIGNADA"
    db.expire_all()
    assert db.get(Conversacion, conv.id).estado == "abierta"
    assert db.scalar(select(func.count()).select_from(Mensaje)) == 0
    assert db.scalar(select(func.count()).select_from(Exclusion)) == 0
