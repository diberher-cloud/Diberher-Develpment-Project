"""Cola de atención: listado, prioridad, tomar-siguiente (C6) y visibilidad por rol."""

from datetime import timedelta

import pytest
from escenario import cab
from sqlalchemy import select
from wa import contexto, crear_conv

from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion

COLA = "/api/v1/atencion/cola"
SIGUIENTE = "/api/v1/atencion/tomar-siguiente"


@pytest.fixture()
def ctx(esc, crear_usuario, reloj, db):
    return contexto(esc, crear_usuario, reloj, db)


def abrir(db, esc, camp, reloj, n, motivo="entrante", antiguedad=0, con_registro=True):
    numero = f"+57311555{n:04d}"
    cc = esc.registro(camp, numeros=(numero,)) if con_registro else None
    ahora = reloj() - timedelta(minutes=antiguedad)
    return crear_conv(db, ahora, numero=numero, cc=cc, con_cola=True, motivo_cola=motivo)


def test_cola_vacia_y_tomar_siguiente_204(client, ctx):
    assert client.get(COLA, headers=cab(ctx.agente)).json() == []
    assert client.post(SIGUIENTE, headers=cab(ctx.agente)).status_code == 204


def test_c6_tomar_siguiente_respeta_prioridad_y_antiguedad(client, db, esc, ctx, reloj):
    vieja = abrir(db, esc, ctx.campana, reloj, 1, antiguedad=30)
    nueva = abrir(db, esc, ctx.campana, reloj, 2, antiguedad=5)
    urgente = abrir(db, esc, ctx.campana, reloj, 3, motivo="solicitud_cliente", antiguedad=1)
    orden = [x["conversacion_id"] for x in client.get(COLA, headers=cab(ctx.agente)).json()]
    assert orden == [urgente.id, vieja.id, nueva.id]
    primero = client.get(COLA, headers=cab(ctx.agente)).json()[0]
    assert (primero["prioridad"], primero["motivo"], primero["espera_segundos"]) == (
        1,
        "solicitud_cliente",
        60,
    )
    assert primero["numero_mascara"] == "+57311****003" or primero["numero_mascara"].startswith(
        "+57311"
    )
    tomadas = []
    for _ in range(3):
        r = client.post(SIGUIENTE, headers=cab(ctx.agente))
        assert r.status_code == 200
        tomadas.append(r.json()["id"])
    assert tomadas == [urgente.id, vieja.id, nueva.id]
    assert client.post(SIGUIENTE, headers=cab(ctx.agente)).status_code == 204


def test_tomar_siguiente_no_da_conversaciones_de_campanas_ajenas_ni_sin_campana(
    client, db, esc, ctx, reloj
):
    otra = esc.campana(whatsapp_habilitado=True)
    sin_wa = esc.campana(whatsapp_habilitado=False)
    esc.asignar(sin_wa, ctx.agente)
    abrir(db, esc, otra, reloj, 1)  # campaña a la que el agente no pertenece
    abrir(db, esc, sin_wa, reloj, 2)  # campaña sin WhatsApp
    abrir(db, esc, ctx.campana, reloj, 3, motivo="sin_campana", con_registro=False)
    assert client.get(COLA, headers=cab(ctx.agente)).json() == []
    assert client.post(SIGUIENTE, headers=cab(ctx.agente)).status_code == 204
    propia = abrir(db, esc, ctx.campana, reloj, 4)
    r = client.post(SIGUIENTE, headers=cab(ctx.agente))
    assert r.status_code == 200 and r.json()["id"] == propia.id


def test_el_agente_no_ve_sin_campana_pero_el_supervisor_si(
    client, db, esc, ctx, reloj, h_supervisor
):
    sin = abrir(db, esc, ctx.campana, reloj, 1, motivo="sin_campana", con_registro=False)
    con = abrir(db, esc, ctx.campana, reloj, 2)
    visibles = [x["conversacion_id"] for x in client.get(COLA, headers=cab(ctx.agente)).json()]
    assert visibles == [con.id]
    todo = client.get(COLA, headers=h_supervisor).json()
    assert {x["conversacion_id"] for x in todo} == {sin.id, con.id}
    assert next(x for x in todo if x["conversacion_id"] == sin.id)["campana"] is None
    assert (
        next(x for x in todo if x["conversacion_id"] == con.id)["campana"]["id"] == ctx.campana.id
    )


def test_filtros_de_la_cola(client, db, esc, ctx, reloj, h_supervisor):
    a = abrir(db, esc, ctx.campana, reloj, 1)
    b = abrir(db, esc, ctx.campana, reloj, 2, motivo="queja")
    otra = esc.campana(whatsapp_habilitado=True)
    c = abrir(db, esc, otra, reloj, 3)

    def ids(q):
        return {x["conversacion_id"] for x in client.get(COLA + q, headers=h_supervisor).json()}

    assert ids("") == {a.id, b.id, c.id}
    assert ids("?motivo=queja") == {b.id}
    assert ids(f"?campana_id={otra.id}") == {c.id}
    assert client.get(COLA + "?motivo=inventado", headers=h_supervisor).status_code == 422


def test_solo_el_agente_usa_tomar_siguiente(client, h_supervisor, h_admin):
    assert client.post(SIGUIENTE, headers=h_supervisor).status_code == 403
    assert client.post(SIGUIENTE, headers=h_admin).status_code == 403
    assert client.post(SIGUIENTE).status_code == 401


def test_tomar_siguiente_exige_estar_disponible(client, db, esc, ctx, reloj):
    abrir(db, esc, ctx.campana, reloj, 1)
    esc.estado(ctx.agente, "pausa", reloj(), motivo_pausa="descanso")
    r = client.post(SIGUIENTE, headers=cab(ctx.agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "AGENTE_NO_DISPONIBLE"


def test_la_cola_no_lista_filas_asignadas_ni_cerradas(client, db, esc, ctx, reloj):
    c = abrir(db, esc, ctx.campana, reloj, 1)
    client.post(f"/api/v1/conversaciones/{c.id}/tomar", headers=cab(ctx.agente))
    assert client.get(COLA, headers=cab(ctx.agente)).json() == []
    db.expire_all()
    assert db.scalar(select(ColaAtencion)).estado == "asignada"
    assert db.get(Conversacion, c.id).atendida_por == "humano"


@pytest.mark.parametrize(
    ("motivo", "prioridad"),
    [
        ("entrante", 2), ("sin_campana", 2), ("liberada", 2), ("agente_desconectado", 2),
        ("supervisor", 2), ("solicitud_cliente", 1), ("queja", 1), ("identidad_bloqueada", 1),
        ("ia_no_resuelve", 1), ("ia_rechazo", 1), ("ia_max_tokens", 1), ("ia_iteraciones", 1),
        ("ia_stop_inesperado", 1), ("ia_monto_no_respaldado", 1), ("ia_error", 1),
        ("presupuesto_excedido", 1), ("ia_desactivada", 1),
    ],
)  # fmt: skip
def test_prioridad_por_defecto_segun_el_motivo(motivo, prioridad):
    from app.modulos.conversaciones.atencion import prioridad_de

    assert prioridad_de(motivo) == prioridad
