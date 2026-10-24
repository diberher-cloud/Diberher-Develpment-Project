"""Ajustes finales de la revisión: gestión pendiente (4a), liberar-gestion (4b), contador."""

import pytest
from escenario import cab, telefono_de
from voz import contexto

from app import cli
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola import tipificacion
from app.modulos.consola.modelos import EstadoAgente, Tipificacion
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.telefonia.modelos import Llamada

S = "/api/v1/telefonia/simulacion"
K = "/api/v1/consola"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj, numeros=("+573001234567", "+573109876543"))


def iniciar(client, ctx, db):
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(ctx.agente),
    )
    return r.json()["llamada_id"]


def terminar(client, ctx, lid, resultado="busy"):
    client.post(
        f"{S}/llamadas/{lid}/eventos",
        json={"evento": "finalizada", "resultado": resultado},
        headers=cab(ctx.agente),
    )


def desactivar(client, h, uid):
    return client.patch(f"/api/v1/usuarios/{uid}", json={"activo": False}, headers=h)


def test_4a_no_se_desactiva_un_agente_con_llamada_activa_o_sin_tipificar(client, ctx, db, h_admin):
    lid = iniciar(client, ctx, db)
    r = desactivar(client, h_admin, ctx.agente.id)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "USUARIO_CON_GESTION_PENDIENTE"
    assert set(r.json()["error"]) == {"codigo", "mensaje", "detalles"}
    terminar(client, ctx, lid)  # terminada sin tipificar
    assert desactivar(client, h_admin, ctx.agente.id).status_code == 409
    client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": "no_contesta"},
        headers=cab(ctx.agente),
    )
    assert desactivar(client, h_admin, ctx.agente.id).status_code == 200


def test_4a_otros_roles_y_cambios_no_se_ven_afectados(client, ctx, db, h_admin, crear_usuario):
    iniciar(client, ctx, db)
    # Otros cambios sobre el agente con gestión pendiente siguen permitidos.
    r = client.patch(f"/api/v1/usuarios/{ctx.agente.id}", json={"nombre": "Nuevo"}, headers=h_admin)
    assert r.status_code == 200
    sup = crear_usuario("supervisor")
    assert desactivar(client, h_admin, sup.id).status_code == 200


def test_4b_tipificar_sistema_aplica_efectos_y_libera(client, ctx, db, reloj):
    lid = iniciar(client, ctx, db)
    terminar(client, ctx, lid, "failed")
    res = tipificacion.tipificar_sistema(db, lid, "numero_errado", reloj())
    assert res.origen == "sistema" and res.usuario_id is None
    assert res.registro.estado == "pendiente" and res.registro.intentos == 1
    tip = db.query(Tipificacion).one()
    assert (tip.origen, tip.usuario_id, tip.canal) == ("sistema", None, "voz")
    ex = db.query(Exclusion).one()
    assert ex.numero_e164 == "+573001234567" and ex.creado_por == ctx.agente.id
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert cc.reservado_por is None and cc.estado == "pendiente"
    assert db.get(EstadoAgente, ctx.agente.id).estado == "disponible"
    aud = db.query(Auditoria).filter_by(accion="consola.tipificacion_sistema").one()
    assert aud.usuario_id is None
    assert aud.detalle == {
        "tipificacion_id": tip.id,
        "llamada_id": lid,
        "resultado": "numero_errado",
    }
    with pytest.raises(Exception) as e:  # ya tipificada
        tipificacion.tipificar_sistema(db, lid, "numero_errado", reloj())
    assert getattr(e.value, "codigo", "") == "LLAMADA_YA_TIPIFICADA"


def test_4b_cli_liberar_gestion(client, ctx, db, session_factory, monkeypatch, capsys, h_admin):
    lid = iniciar(client, ctx, db)
    terminar(client, ctx, lid)
    monkeypatch.setattr(cli.bd, "SessionLocal", session_factory)
    assert (
        cli.main(["liberar-gestion", "--llamada-id", str(lid), "--resultado", "no_contesta"]) == 0
    )
    assert "tipificada" in capsys.readouterr().out
    db.expire_all()
    assert db.query(Tipificacion).one().origen == "sistema"
    assert desactivar(client, h_admin, ctx.agente.id).status_code == 200  # ya no hay gestión
    # llamada inexistente / resultado inválido
    assert cli.main(["liberar-gestion", "--llamada-id", "9999", "--resultado", "contactado"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["liberar-gestion", "--llamada-id", str(lid), "--resultado", "venta"])


def test_4b_cli_cierra_llamada_atascada(client, ctx, db, session_factory, monkeypatch):
    lid = iniciar(client, ctx, db)  # sigue `iniciando`: webhooks perdidos
    monkeypatch.setattr(cli.bd, "SessionLocal", session_factory)
    assert (
        cli.main(["liberar-gestion", "--llamada-id", str(lid), "--resultado", "no_contesta"]) == 0
    )
    db.expire_all()
    assert db.get(Llamada, lid).estado == "fallida"
    assert db.query(Tipificacion).one().resultado == "no_contesta"
    assert db.get(EstadoAgente, ctx.agente.id).estado == "disponible"


def test_contador_de_intentos_se_incrementa_una_vez_por_tipificacion(client, ctx, db):
    lid = iniciar(client, ctx, db)
    terminar(client, ctx, lid)
    r = client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": "no_contesta"},
        headers=cab(ctx.agente),
    )
    assert r.status_code == 201 and r.json()["registro"]["intentos"] == 1
    db.expire_all()
    assert db.get(CampanaCliente, ctx.cc.id).intentos == 1
