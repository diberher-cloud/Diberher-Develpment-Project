from escenario import cab

from app.modulos.auditoria.modelos import Auditoria

C = "/api/v1/campanas"


def test_asignar_reemplaza_conjunto_y_audita(client, esc, crear_usuario, h_admin, db):
    camp = esc.campana()
    a1, a2 = crear_usuario("agente"), crear_usuario("agente")
    r = client.put(
        f"{C}/{camp.id}/agentes", json={"usuario_ids": [a1.id, a2.id, a1.id]}, headers=h_admin
    )
    assert r.status_code == 200, r.text
    assert {a["usuario_id"] for a in r.json()} == {a1.id, a2.id} and len(r.json()) == 2
    assert set(r.json()[0]) == {"usuario_id", "nombre", "email", "activo", "asignado_en"}
    r = client.put(f"{C}/{camp.id}/agentes", json={"usuario_ids": [a2.id]}, headers=h_admin)
    assert [a["usuario_id"] for a in r.json()] == [a2.id]
    assert [
        a["usuario_id"] for a in client.get(f"{C}/{camp.id}/agentes", headers=h_admin).json()
    ] == [a2.id]
    detalles = [x.detalle for x in db.query(Auditoria).filter_by(accion="campana.agentes")]
    assert detalles == [
        {"agregados": sorted([a1.id, a2.id]), "quitados": []},
        {"agregados": [], "quitados": [a1.id]},
    ]
    r = client.put(f"{C}/{camp.id}/agentes", json={"usuario_ids": [a2.id]}, headers=h_admin)
    assert db.query(Auditoria).filter_by(accion="campana.agentes").count() == 2  # sin cambios


def test_validacion_por_indice(client, esc, crear_usuario, h_admin):
    camp = esc.campana()
    ok = crear_usuario("agente")
    sup = crear_usuario("supervisor")
    inactivo = crear_usuario("agente", activo=False)
    r = client.put(
        f"{C}/{camp.id}/agentes",
        json={"usuario_ids": [ok.id, sup.id, 99999, inactivo.id]},
        headers=h_admin,
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert r.json()["error"]["detalles"] == [
        {"campo": f"usuario_ids.{i}", "mensaje": "El usuario no es un agente activo."}
        for i in (1, 2, 3)
    ]
    assert client.get(f"{C}/{camp.id}/agentes", headers=h_admin).json() == []


def test_campana_finalizada_y_inexistente(client, esc, h_admin):
    camp = esc.campana(estado="finalizada")
    r = client.put(f"{C}/{camp.id}/agentes", json={"usuario_ids": []}, headers=h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CAMPANA_FINALIZADA"
    assert client.get(f"{C}/9999/agentes", headers=h_admin).status_code == 404
    assert (
        client.put(f"{C}/9999/agentes", json={"usuario_ids": []}, headers=h_admin).status_code
        == 404
    )


def test_quitar_agente_libera_sus_reservas(client, esc, crear_usuario, h_admin, db, reloj):
    camp = esc.campana()
    ag = crear_usuario("agente")
    esc.asignar(camp, ag)
    cc = esc.registro(camp)
    esc.reservar(cc, ag, reloj())
    r = client.put(f"{C}/{camp.id}/agentes", json={"usuario_ids": []}, headers=h_admin)
    assert r.status_code == 200 and r.json() == []
    db.refresh(cc)
    assert (cc.estado, cc.reservado_por, cc.reservado_hasta) == ("pendiente", None, None)


def test_supervisor_puede_agente_no(client, esc, crear_usuario, h_supervisor):
    camp = esc.campana()
    ag = crear_usuario("agente")
    assert (
        client.put(
            f"{C}/{camp.id}/agentes", json={"usuario_ids": [ag.id]}, headers=h_supervisor
        ).status_code
        == 200
    )
    assert client.get(f"{C}/{camp.id}/agentes", headers=cab(ag)).status_code == 403
    assert (
        client.put(f"{C}/{camp.id}/agentes", json={"usuario_ids": []}, headers=cab(ag)).status_code
        == 403
    )
