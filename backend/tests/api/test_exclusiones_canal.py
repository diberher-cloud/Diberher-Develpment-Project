"""Exclusiones por canal (§4.10): API, aplicabilidad en voz y número errado."""

import pytest
from escenario import cab, telefono_de
from sqlalchemy import select
from voz import RUTA_SALIENTE, llamar, params_saliente
from voz import contexto as ctx_voz

from app.modulos.exclusiones.modelos import Exclusion

API = "/api/v1/exclusiones"


def crear(client, h, numero="3001234567", canal=None, aplica_a="todas", motivo="manual"):
    cuerpo = {"telefono": numero, "motivo": motivo, "aplica_a": aplica_a}
    if canal:
        cuerpo["canal"] = canal
    return client.post(API, json=cuerpo, headers=h)


def test_el_canal_por_defecto_es_todos_y_el_objeto_trae_los_campos_nuevos(client, h_admin):
    r = crear(client, h_admin)
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["canal"], e["origen"], e["conversacion_id"]) == ("todos", "usuario", None)
    assert e["creado_por"] is not None


def test_duplicado_es_el_mismo_numero_finalidad_y_canal(client, h_admin):
    assert crear(client, h_admin, canal="whatsapp").status_code == 201
    assert crear(client, h_admin, canal="voz").status_code == 201
    assert crear(client, h_admin).status_code == 201  # todos
    for canal in ("whatsapp", "voz", None):
        r = crear(client, h_admin, canal=canal)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "EXCLUSION_DUPLICADA"
    assert crear(client, h_admin, canal="whatsapp", aplica_a="venta").status_code == 201


def test_canal_invalido_422(client, h_admin):
    assert crear(client, h_admin, canal="sms").status_code == 422


def test_listado_filtra_por_canal(client, h_admin):
    crear(client, h_admin, numero="3001111111", canal="whatsapp")
    crear(client, h_admin, numero="3002222222", canal="voz")
    crear(client, h_admin, numero="3003333333")
    r = client.get(f"{API}?canal=whatsapp", headers=h_admin).json()
    assert [x["canal"] for x in r["items"]] == ["whatsapp"]
    assert client.get(API, headers=h_admin).json()["total"] == 3
    assert client.get(f"{API}?canal=todos", headers=h_admin).json()["total"] == 1
    assert client.get(f"{API}?canal=otro", headers=h_admin).status_code == 422


def csv(numeros):
    return ("telefono\n" + "\n".join(numeros) + "\n").encode()


def test_importacion_con_canal(client, h_admin, db):
    r = client.post(
        f"{API}/importar",
        files={"archivo": ("x.csv", csv(["3001111111", "3002222222"]), "text/csv")},
        data={"motivo": "rne", "aplica_a": "venta", "canal": "whatsapp"},
        headers=h_admin,
    )
    assert r.status_code == 200 and r.json()["creadas"] == 2
    assert {e.canal for e in db.scalars(select(Exclusion))} == {"whatsapp"}
    # Mismo archivo con otro canal: no son duplicadas.
    r = client.post(
        f"{API}/importar",
        files={"archivo": ("x.csv", csv(["3001111111"]), "text/csv")},
        data={"motivo": "rne", "aplica_a": "venta", "canal": "voz"},
        headers=h_admin,
    )
    assert r.json()["creadas"] == 1 and r.json()["duplicadas"] == 0
    # Sin canal: `todos`; repetir el mismo canal duplica.
    for esperadas in (1, 0):
        r = client.post(
            f"{API}/importar",
            files={"archivo": ("x.csv", csv(["3001111111"]), "text/csv")},
            data={"motivo": "rne", "aplica_a": "venta"},
            headers=h_admin,
        )
        assert r.json()["creadas"] == esperadas
    r = client.post(
        f"{API}/importar",
        files={"archivo": ("x.csv", csv(["3001111111"]), "text/csv")},
        data={"motivo": "rne", "aplica_a": "venta", "canal": "sms"},
        headers=h_admin,
    )
    assert r.status_code == 422


# ---- La voz respeta `todos`/`voz` e ignora `whatsapp` ----------------------------------
@pytest.mark.parametrize(
    ("canal", "bloquea"), [("whatsapp", False), ("voz", True), ("todos", True)]
)
def test_twiml_saliente_segun_el_canal_de_la_exclusion(
    client, firmar_twilio, db, esc, crear_usuario, reloj, admin, canal, bloquea
):
    ctx = ctx_voz(esc, crear_usuario, reloj)
    numero = telefono_de(db, ctx.cc).numero_e164
    db.add(
        Exclusion(
            numero_e164=numero, motivo="rne", aplica_a="todas", canal=canal, creado_por=admin.id
        )
    )
    db.commit()
    r = llamar(client, firmar_twilio, params_saliente(ctx, db))
    assert r.status_code == 200
    assert ("<Reject" in r.text or "<Say" in r.text and "<Dial" not in r.text) == bloquea
    assert ("<Dial" in r.text) == (not bloquea)
    assert RUTA_SALIENTE


def test_la_ficha_de_voz_ignora_exclusiones_de_whatsapp(
    client, db, esc, crear_usuario, reloj, admin
):
    ctx = ctx_voz(esc, crear_usuario, reloj)
    numero = telefono_de(db, ctx.cc).numero_e164
    db.add(
        Exclusion(
            numero_e164=numero,
            motivo="rne",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    ficha = client.get(f"/api/v1/consola/registros/{ctx.cc.id}", headers=cab(ctx.agente)).json()
    assert ficha["telefonos"][0]["excluido"] is False and ficha["telefonos"][0]["llamable"] is True
    db.add(
        Exclusion(
            numero_e164=numero, motivo="rne", aplica_a="todas", canal="voz", creado_por=admin.id
        )
    )
    db.commit()
    ficha = client.get(f"/api/v1/consola/registros/{ctx.cc.id}", headers=cab(ctx.agente)).json()
    assert ficha["telefonos"][0]["excluido"] is True


def test_la_importacion_de_clientes_ignora_exclusiones_de_whatsapp(client, h_admin, db, admin):
    db.add(
        Exclusion(
            numero_e164="+573001234567",
            motivo="rne",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    camp = client.post(
        "/api/v1/campanas", json={"nombre": "Camp X", "tipo": "cobranza"}, headers=h_admin
    ).json()
    contenido = (
        "tipo_documento,numero_documento,nombre,telefono_1\nCC,123456789,Ana Pérez,3001234567\n"
    ).encode()
    r = client.post(
        f"/api/v1/campanas/{camp['id']}/importaciones",
        files={"archivo": ("c.csv", contenido, "text/csv")},
        headers=h_admin,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["filas_importadas"] == 1 and r.json()["filas_excluidas"] == 0


def test_numero_errado_de_voz_sigue_creando_exclusion_para_todos_los_canales(
    client, db, esc, crear_usuario, reloj, admin
):
    from test_tipificaciones import llamada_terminada, tipificar

    ctx = ctx_voz(esc, crear_usuario, reloj)
    numero = telefono_de(db, ctx.cc).numero_e164
    # Una exclusión previa solo de WhatsApp no cuenta como "ya excluido" para el número errado.
    db.add(
        Exclusion(
            numero_e164=numero,
            motivo="rne",
            aplica_a="todas",
            canal="whatsapp",
            creado_por=admin.id,
        )
    )
    db.commit()
    lid = llamada_terminada(client, ctx, db, resultado="failed", contestar=False)
    assert tipificar(client, ctx, lid, "numero_errado").status_code == 201
    db.expire_all()
    filas = {(e.canal, e.motivo) for e in db.scalars(select(Exclusion))}
    assert filas == {("whatsapp", "rne"), ("todos", "numero_errado")}
