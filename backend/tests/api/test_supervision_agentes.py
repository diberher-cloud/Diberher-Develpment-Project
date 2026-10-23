from escenario import cab, telefono_de
from voz import contexto

URL = "/api/v1/supervision/agentes"


def test_lista_todos_los_agentes_activos_ordenados(client, esc, crear_usuario, h_supervisor, reloj):
    b = crear_usuario("agente")
    b.nombre = "Beto"
    a = crear_usuario("agente")
    a.nombre = "Ana"
    crear_usuario("agente", activo=False)
    crear_usuario("supervisor")
    c1, c2 = esc.campana(), esc.campana()
    esc.asignar(c1, a)
    esc.asignar(c2, a)
    esc.estado(a, "pausa", reloj(), motivo_pausa="almuerzo")
    r = client.get(URL, headers=h_supervisor)
    assert r.status_code == 200
    assert r.json() == [
        {
            "usuario_id": a.id, "nombre": "Ana", "estado": "pausa", "desde": "2026-10-23T15:15:00Z",
            "motivo_pausa": "almuerzo", "campanas": sorted([c1.id, c2.id]), "llamada": None,
        },
        {
            "usuario_id": b.id, "nombre": "Beto", "estado": "desconectado",
            "desde": "2026-10-23T15:15:00Z", "motivo_pausa": None, "campanas": [], "llamada": None,
        },
    ]  # fmt: skip


def test_incluye_la_llamada_actual(client, esc, crear_usuario, h_admin, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj)
    r = client.post(
        "/api/v1/telefonia/simulacion/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=cab(ctx.agente),
    )
    lid = r.json()["llamada_id"]
    item = client.get(URL, headers=h_admin).json()[0]
    assert item["estado"] == "en_llamada"
    assert item["llamada"] == {
        "id": lid, "estado": "iniciando", "campana_id": ctx.campana.id,
        "campana_nombre": ctx.campana.nombre,
    }  # fmt: skip


def test_agente_no_puede(client, crear_usuario):
    assert client.get(URL, headers=cab(crear_usuario("agente"))).status_code == 403
    assert client.get(URL).status_code == 401
