"""QA 2B: texto hostil (NUL, sustitutos sueltos, bidi, emojis de 4 bytes) en webhooks y API.
Pensado para correr también con `SUITE_DATABASE_URL` (PostgreSQL rechaza NUL en `text`)."""

import pytest
from escenario import cab
from sqlalchemy import select
from wa import RUTA_ENTRANTE, clave, contexto, crear_conv, params_entrante

from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion
from app.trabajos.modelos import Trabajo

API = "/api/v1"
HOSTILES = [
    "hola\x00mundo",
    "\x00",
    "‮odnum aloh",
    "zero​width⁠joiner",
    "emoji 😀👨‍👩‍👧‍👦 🏳️‍🌈",
    "<script>alert(1)</script><img src=x onerror=alert(2)>",
    "'; DROP TABLE mensajes; --",
    "{{1}} {{saldo_mora}} %s %(x)s ${jndi:ldap://x}",
    "\r\n\r\nX-Header: inyectado",
]


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


@pytest.mark.parametrize("hostil", HOSTILES)
def test_webhook_entrante_con_texto_hostil_no_rompe_ni_deja_trabajos_fallidos(
    client, firmar_twilio, correr_trabajos, db, ctx, hostil
):
    p = params_entrante(texto=hostil, ProfileName=hostil[:50])
    r = client.post(RUTA_ENTRANTE, **firmar_twilio(RUTA_ENTRANTE, p))
    assert r.status_code == 200, (hostil, r.status_code, r.text[:200])
    correr_trabajos()
    db.expire_all()
    assert [t.estado for t in db.scalars(select(Trabajo)) if t.estado == "fallido"] == []


@pytest.mark.parametrize("hostil", HOSTILES)
def test_texto_del_agente_hostil_se_guarda_tal_cual_o_se_rechaza_con_422(
    client, db, ctx, reloj, hostil
):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.post(
        f"{API}/conversaciones/{conv.id}/mensajes",
        json={"texto": hostil, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code in (202, 422), (hostil, r.status_code, r.text[:200])
    if r.status_code == 202:
        assert r.json()["cuerpo"] == hostil.strip()


@pytest.mark.parametrize("hostil", ["evidencia\x00 oculta"])
def test_evidencia_y_observacion_hostiles_no_producen_500(client, db, ctx, reloj, hostil):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.post(
        f"{API}/conversaciones/{conv.id}/autorizacion",
        json={"finalidad": "cobranza", "evidencia": hostil},
        headers=cab(ctx.agente),
    )
    assert r.status_code in (201, 422), (r.status_code, r.text[:200])
    r = client.post(
        f"{API}/conversaciones/{conv.id}/cerrar",
        json={"tipificacion": {"resultado": "contactado", "observacion": hostil}},
        headers=cab(ctx.agente),
    )
    assert r.status_code in (200, 422), (r.status_code, r.text[:200])
    assert db.scalar(select(Conversacion.id)) is not None


def test_json_con_sustituto_suelto_escapado_no_produce_500(client, db, ctx, reloj):
    """`"\\ud800"` es JSON válido pero no UTF-8 válido: debe rechazarse o limpiarse."""
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    cuerpo = ('{"texto": "a\\ud800b", "idempotencia_clave": "' + clave() + '"}').encode()
    r = client.post(
        f"{API}/conversaciones/{conv.id}/mensajes",
        content=cuerpo,
        headers={**cab(ctx.agente), "content-type": "application/json"},
    )
    assert r.status_code in (202, 422), (r.status_code, r.text[:200])


@pytest.mark.parametrize("n", [4096, 4097, 200_000, 3_000_000])
def test_limites_del_texto_del_agente(client, db, ctx, reloj, n):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.post(
        f"{API}/conversaciones/{conv.id}/mensajes",
        json={"texto": "ñ" * n, "idempotencia_clave": clave()},
        headers=cab(ctx.agente),
    )
    assert r.status_code == (202 if n <= 4096 else 422) or r.status_code == 413, (n, r.status_code)


def test_texto_solo_de_espacios_o_saltos_es_422(client, db, ctx, reloj):
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    for vacio in ("", "   ", "\n\t \r\n", " "):
        r = client.post(
            f"{API}/conversaciones/{conv.id}/mensajes",
            json={"texto": vacio, "idempotencia_clave": clave()},
            headers=cab(ctx.agente),
        )
        assert r.status_code == 422, (repr(vacio), r.status_code)
