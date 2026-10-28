"""`TelefonoFicha.whatsapp` en la ficha de la consola de voz (§4.13)."""

import pytest
from escenario import cab
from wa import NUMERO, autorizar, contexto, crear_conv

from app.modulos.conversaciones.dueno import Humano
from app.modulos.exclusiones.modelos import Exclusion

FICHA = "/api/v1/consola/registros/{}"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    c = contexto(esc, crear_usuario, reloj, db)
    esc.reservar(c.cc, c.agente, reloj())
    return c


def ficha(client, ctx):
    r = client.get(FICHA.format(ctx.cc.id), headers=cab(ctx.agente))
    assert r.status_code == 200, r.text
    return r.json()["telefonos"][0]


def test_whatsapp_nulo_si_la_campana_no_lo_tiene_o_el_telefono_es_fijo(client, db, ctx, esc, reloj):
    ctx.campana.whatsapp_habilitado = False
    db.commit()
    assert ficha(client, ctx)["whatsapp"] is None
    ctx.campana.whatsapp_habilitado = True
    db.commit()
    fijo = esc.registro(ctx.campana, numeros=("+576012345678",))
    esc.reservar(fijo, ctx.agente, reloj())
    r = client.get(FICHA.format(fijo.id), headers=cab(ctx.agente))
    assert r.json()["telefonos"][0]["whatsapp"] is None


def test_sin_autorizacion_no_es_enviable_y_lo_explica(client, ctx):
    w = ficha(client, ctx)["whatsapp"]
    assert (w["autorizado"], w["excluido"], w["enviable"]) == (False, False, False)
    assert [m["codigo"] for m in w["motivos"]] == ["SIN_AUTORIZACION"]
    assert w["conversacion_abierta"] is None


def test_autorizado_en_franja_es_enviable(client, db, ctx):
    autorizar(db)
    w = ficha(client, ctx)["whatsapp"]
    assert (w["autorizado"], w["excluido"], w["enviable"], w["motivos"]) == (True, False, True, [])


def test_excluido_para_whatsapp_pero_no_para_voz(client, db, ctx, admin):
    autorizar(db)
    db.add(
        Exclusion(
            numero_e164=NUMERO,
            motivo="rne",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    t = ficha(client, ctx)
    assert t["excluido"] is False and t["llamable"] is True  # la voz sigue permitida
    assert t["whatsapp"]["excluido"] is True and t["whatsapp"]["enviable"] is False
    assert t["whatsapp"]["motivos"][0]["codigo"] == "EXCLUIDO"


def test_fuera_de_franja_aparece_en_los_motivos(client, db, ctx, reloj, esc):
    from datetime import UTC, datetime

    autorizar(db)
    reloj.fijar(datetime(2026, 10, 25, 15, 0, tzinfo=UTC))  # domingo
    esc.reservar(ctx.cc, ctx.agente, reloj())
    w = ficha(client, ctx)["whatsapp"]
    assert [m["codigo"] for m in w["motivos"]] == ["DIA_SIN_FRANJA"] and w["enviable"] is False


def test_conversacion_abierta_con_ventana_abierta_no_es_enviable(client, db, ctx, reloj):
    autorizar(db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    w = ficha(client, ctx)["whatsapp"]
    assert w["enviable"] is False and w["motivos"] == []
    assert w["conversacion_abierta"] == {
        "id": conv.id,
        "atendida_por": "humano",
        "ventana_abierta": True,
    }


def test_conversacion_abierta_con_ventana_cerrada_si_es_enviable(client, db, ctx, reloj):
    autorizar(db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, iniciada_por="empresa", ventana=False)
    w = ficha(client, ctx)["whatsapp"]
    assert w["enviable"] is True
    assert w["conversacion_abierta"] == {
        "id": conv.id,
        "atendida_por": "sin_asignar",
        "ventana_abierta": False,
    }


def test_la_ficha_de_la_conversacion_incluye_whatsapp(client, db, ctx, reloj):
    autorizar(db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=Humano(ctx.agente.id))
    r = client.get(f"/api/v1/conversaciones/{conv.id}/ficha", headers=cab(ctx.agente))
    assert r.status_code == 200 and r.json()["telefonos"][0]["whatsapp"]["autorizado"] is True
    sin_registro = crear_conv(db, reloj(), numero="+573119998877")
    from escenario import cab as c2

    sup = client.get(f"/api/v1/conversaciones/{sin_registro.id}/ficha", headers=c2(ctx.agente))
    assert sup.status_code == 403  # el agente no es el dueño
