import copy

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.cumplimiento.politica import politica_por_defecto

C = "/api/v1/cumplimiento"


def evaluar(client, h, momento=None, tipo="cobranza"):
    cuerpo = {"tipo_campana": tipo}
    if momento:
        cuerpo["momento"] = momento
    return client.post(f"{C}/evaluar", json=cuerpo, headers=h)


def test_politicas_activas(client, h_agente):
    r = client.get(f"{C}/politicas", headers=h_agente)
    assert r.status_code == 200
    datos = r.json()
    assert [p["tipo_campana"] for p in datos] == ["cobranza", "venta"]
    assert datos[0]["version"] == 1 and datos[0]["activa"] and datos[0]["creado_por"] is None
    assert datos[0]["configuracion"] == politica_por_defecto()


def test_put_crea_version_y_desactiva_anterior(client, h_admin, db):
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["sabado"] = []
    r = client.put(f"{C}/politicas/venta", json=cfg, headers=h_admin)
    assert r.status_code == 201
    assert r.json()["version"] == 2 and r.json()["activa"] and r.json()["creado_por"] is not None
    vs = client.get(f"{C}/politicas/venta/versiones", headers=h_admin).json()
    assert [(v["version"], v["activa"]) for v in vs] == [(2, True), (1, False)]
    activas = client.get(f"{C}/politicas", headers=h_admin).json()
    assert {p["tipo_campana"]: p["version"] for p in activas} == {"venta": 2, "cobranza": 1}
    ev = evaluar(client, h_admin, "2026-10-24T10:00:00-05:00", "venta").json()
    assert ev["permitido"] is False and ev["politica_version"] == 2
    assert db.query(Auditoria).filter_by(accion="politica.actualizar").count() == 1


def test_put_invalido(client, h_admin):
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["franjas"]["lunes"] = [{"inicio": "07:00", "fin": "25:00"}]
    r = client.put(f"{C}/politicas/cobranza", json=cfg, headers=h_admin)
    assert r.status_code == 422
    assert r.json()["error"]["detalles"][0]["campo"] == "configuracion.franjas.lunes.0.fin"
    assert client.put(f"{C}/politicas/otro", json=cfg, headers=h_admin).status_code == 422
    assert client.get(f"{C}/politicas/otro/versiones", headers=h_admin).status_code == 422
    assert client.put(f"{C}/politicas/cobranza", json={}, headers=h_admin).status_code == 422


def test_festivos_generar_idempotente_y_listar(client, h_admin, db):
    r = client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)
    assert r.json() == {"anio": 2026, "creados": 18, "existentes": 0}
    r = client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)
    assert r.json() == {"anio": 2026, "creados": 0, "existentes": 18}
    lista = client.get("/api/v1/festivos?anio=2026", headers=h_admin).json()
    assert (
        len(lista) == 18 and lista[0]["fecha"] == "2026-01-01" and lista[0]["origen"] == "calculado"
    )
    assert client.get("/api/v1/festivos", headers=h_admin).status_code == 422
    assert client.get("/api/v1/festivos?anio=1983", headers=h_admin).status_code == 422
    assert (
        client.post("/api/v1/festivos/generar", json={"anio": 2101}, headers=h_admin).status_code
        == 422
    )
    assert db.query(Auditoria).filter_by(accion="festivos.generar").count() == 2


def test_festivo_manual_duplicado_y_desactivar(client, h_admin, db):
    client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)
    r = client.post(
        "/api/v1/festivos", json={"fecha": "2026-12-31", "nombre": "Día cívico"}, headers=h_admin
    )
    assert r.status_code == 201 and r.json()["origen"] == "manual" and r.json()["activo"]
    d = client.post(
        "/api/v1/festivos", json={"fecha": "2026-12-31", "nombre": "Otro"}, headers=h_admin
    )
    assert d.status_code == 409 and d.json()["error"]["codigo"] == "FESTIVO_DUPLICADO"
    d = client.post(
        "/api/v1/festivos", json={"fecha": "2026-11-02", "nombre": "Otro"}, headers=h_admin
    )
    assert d.status_code == 409

    ev = evaluar(client, h_admin, "2026-12-31T10:00:00-05:00").json()
    assert ev["permitido"] is False and ev["motivos"][0]["codigo"] == "FESTIVO"
    fid = r.json()["id"]
    p = client.patch(f"/api/v1/festivos/{fid}", json={"activo": False}, headers=h_admin)
    assert p.status_code == 200 and p.json()["activo"] is False
    assert evaluar(client, h_admin, "2026-12-31T10:00:00-05:00").json()["permitido"] is True
    # Desactivar uno calculado: evaluar lo ignora
    todos = client.get("/api/v1/festivos?anio=2026", headers=h_admin).json()
    nov2 = next(f for f in todos if f["fecha"] == "2026-11-02")
    client.patch(
        f"/api/v1/festivos/{nov2['id']}",
        json={"activo": False, "nombre": "Renombrado"},
        headers=h_admin,
    )
    assert evaluar(client, h_admin, "2026-11-02T10:00:00-05:00").json()["permitido"] is True
    # La generación no revive ni modifica fechas existentes
    client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)
    todos = client.get("/api/v1/festivos?anio=2026", headers=h_admin).json()
    nov2 = next(f for f in todos if f["fecha"] == "2026-11-02")
    assert nov2["activo"] is False and nov2["nombre"] == "Renombrado"
    assert (
        client.patch("/api/v1/festivos/9999", json={"activo": True}, headers=h_admin).status_code
        == 404
    )
    acciones = {a.accion for a in db.query(Auditoria)}
    assert {"festivo.crear", "festivo.actualizar"} <= acciones


def test_evaluar(client, h_agente, h_admin):
    client.post("/api/v1/festivos/generar", json={"anio": 2026}, headers=h_admin)
    r = evaluar(client, h_agente, "2026-11-02T10:00:00-05:00")
    assert r.status_code == 200
    assert r.json() == {
        "permitido": False,
        "motivos": [{"codigo": "FESTIVO", "mensaje": "2026-11-02 es festivo (Todos los Santos)."}],
        "momento_local": "2026-11-02T10:00:00-05:00",
        "proxima_ventana_inicio": "2026-11-03T07:00:00-05:00",
        "politica_version": 1,
    }
    ok = evaluar(client, h_agente, "2026-10-23T12:00:00Z").json()
    assert ok["permitido"] is True and ok["motivos"] == [] and ok["proxima_ventana_inicio"] is None
    assert ok["momento_local"] == "2026-10-23T07:00:00-05:00"
    assert evaluar(client, h_agente).status_code == 200  # momento por defecto: ahora


def test_evaluar_validaciones(client, h_agente):
    r = evaluar(client, h_agente, "2026-11-02T10:00:00")
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert r.json()["error"]["detalles"][0]["campo"] == "momento"
    assert (
        client.post(f"{C}/evaluar", json={"tipo_campana": "x"}, headers=h_agente).status_code == 422
    )


def test_permisos(client, h_supervisor, h_agente):
    cfg = politica_por_defecto()
    assert client.put(f"{C}/politicas/venta", json=cfg, headers=h_supervisor).status_code == 403
    assert (
        client.post(
            "/api/v1/festivos/generar", json={"anio": 2026}, headers=h_supervisor
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/festivos", json={"fecha": "2026-12-31", "nombre": "x"}, headers=h_supervisor
        ).status_code
        == 403
    )
    assert (
        client.patch("/api/v1/festivos/1", json={"activo": False}, headers=h_supervisor).status_code
        == 403
    )
    assert client.get(f"{C}/politicas/venta/versiones", headers=h_supervisor).status_code == 200
    assert client.get(f"{C}/politicas/venta/versiones", headers=h_agente).status_code == 403
    assert client.get("/api/v1/festivos?anio=2026", headers=h_agente).status_code == 200
    assert client.get(f"{C}/politicas", headers=h_agente).status_code == 200


def test_evaluar_usa_festivos_calculados_si_el_anio_no_esta_generado(client, h_agente):
    # 2029 no está en la tabla: 2029-01-01 (lunes) es festivo calculado.
    r = evaluar(client, h_agente, "2029-01-01T10:00:00-05:00").json()
    assert r["permitido"] is False and r["motivos"][0]["codigo"] == "FESTIVO"


def test_evaluar_respeta_tabla_si_el_anio_tiene_filas(client, h_admin):
    client.post("/api/v1/festivos/generar", json={"anio": 2029}, headers=h_admin)
    fid = next(
        f["id"] for f in client.get("/api/v1/festivos?anio=2029", headers=h_admin).json()
        if f["fecha"] == "2029-01-01"
    )  # fmt: skip
    client.patch(f"/api/v1/festivos/{fid}", json={"activo": False}, headers=h_admin)
    assert evaluar(client, h_admin, "2029-01-01T10:00:00-05:00").json()["permitido"] is True


def test_evaluar_fechas_extremas_422(client, h_agente):
    for m in (
        "0001-01-01T00:00:00+00:00",
        "9999-12-31T23:00:00-05:00",
        "0001-01-01T00:00:00+14:00",
    ):
        r = evaluar(client, h_agente, m)
        assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "momento"


def test_ids_enormes_422(client, h_admin):
    r = client.get(f"/api/v1/campanas/{10**25}", headers=h_admin)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"


# ---- Fase 2A: frecuencia y política extendida --------------------------------------------------
def test_politicas_antiguas_se_muestran_con_valores_por_defecto(client, h_agente, db):
    from app.modulos.cumplimiento.modelos import PoliticaCumplimiento

    antigua = copy.deepcopy(politica_por_defecto())
    del antigua["frecuencia"]["contar_intentos_sin_contacto"]
    del antigua["entrantes"]
    for fila in db.query(PoliticaCumplimiento):
        fila.configuracion = antigua
    db.commit()
    for p in client.get(f"{C}/politicas", headers=h_agente).json():
        assert p["configuracion"] == politica_por_defecto()
    db.expire_all()
    assert db.query(PoliticaCumplimiento).first().configuracion == antigua  # no se reescribe
    # y sigue evaluando
    assert evaluar(client, h_agente, "2026-10-23T10:00:00-05:00").json()["permitido"] is True


def test_put_politica_con_campos_nuevos_y_rechazo_de_extras(client, h_admin):
    cfg = copy.deepcopy(politica_por_defecto())
    cfg["frecuencia"]["contar_intentos_sin_contacto"] = False
    cfg["entrantes"]["responder_fuera_de_franja"] = False
    r = client.put(f"{C}/politicas/cobranza", json=cfg, headers=h_admin)
    assert r.status_code == 201 and r.json()["configuracion"] == cfg
    cfg["entrantes"]["otro"] = 1
    r = client.put(f"{C}/politicas/cobranza", json=cfg, headers=h_admin)
    assert (
        r.status_code == 422
        and r.json()["error"]["detalles"][0]["campo"] == "configuracion.entrantes.otro"
    )


def test_put_politica_de_fase_1_sigue_valido(client, h_admin):
    cfg = copy.deepcopy(politica_por_defecto())
    del cfg["frecuencia"]["contar_intentos_sin_contacto"]
    del cfg["entrantes"]
    r = client.put(f"{C}/politicas/venta", json=cfg, headers=h_admin)
    assert r.status_code == 201 and r.json()["configuracion"] == politica_por_defecto()


def test_evaluar_con_cliente_incluye_frecuencia(client, h_admin, db):
    from datetime import UTC, datetime

    from app.modulos.campanas.modelos import Campana
    from app.modulos.clientes.modelos import Cliente
    from app.modulos.cumplimiento.modelos import IntentoContacto

    cli = Cliente(tipo_documento="CC", numero_documento="777", nombre="Ana Cliente")
    db.add(cli)
    db.commit()
    db.add(
        IntentoContacto(
            cliente_id=cli.id, tipo_campana="cobranza", canal="voz", iniciado_por="empresa",
            momento=datetime(2026, 10, 23, 13, 0, tzinfo=UTC), contacto_directo=True,
        )
    )  # fmt: skip
    db.commit()
    cuerpo = {
        "tipo_campana": "cobranza",
        "momento": "2026-10-23T10:00:00-05:00",
        "cliente_id": cli.id,
    }
    r = client.post(f"{C}/evaluar", json=cuerpo, headers=h_admin)
    assert r.status_code == 200
    assert [m["codigo"] for m in r.json()["motivos"]] == ["FRECUENCIA_DIA"]
    assert r.json()["proxima_ventana_inicio"] == "2026-10-24T08:00:00-05:00"
    # otro canal el sábado -> medios
    cuerpo.update(canal="whatsapp_mensaje", momento="2026-10-24T10:00:00-05:00")
    r = client.post(f"{C}/evaluar", json=cuerpo, headers=h_admin)
    assert [m["codigo"] for m in r.json()["motivos"]] == ["FRECUENCIA_MEDIOS"]
    assert r.json()["proxima_ventana_inicio"] == "2026-10-26T07:00:00-05:00"
    # el tipo de campaña distinto no ve el intento
    cuerpo.update(tipo_campana="venta", canal="voz", momento="2026-10-23T10:00:00-05:00")
    assert client.post(f"{C}/evaluar", json=cuerpo, headers=h_admin).json()["permitido"] is True
    # sin cliente_id: solo horario, como en Fase 1
    sin = {"tipo_campana": "cobranza", "momento": "2026-10-23T10:00:00-05:00"}
    assert client.post(f"{C}/evaluar", json=sin, headers=h_admin).json()["permitido"] is True
    assert Campana is not None


def test_evaluar_cliente_inexistente_canal_invalido(client, h_admin):
    base = {"tipo_campana": "cobranza", "momento": "2026-10-23T10:00:00-05:00"}
    assert (
        client.post(f"{C}/evaluar", json={**base, "cliente_id": 99999}, headers=h_admin).status_code
        == 404
    )
    assert (
        client.post(f"{C}/evaluar", json={**base, "canal": "sms"}, headers=h_admin).status_code
        == 422
    )
    assert (
        client.post(f"{C}/evaluar", json={**base, "cliente_id": 0}, headers=h_admin).status_code
        == 422
    )
    assert (
        client.post(f"{C}/evaluar", json={**base, "cliente_id": 2**40}, headers=h_admin).status_code
        == 422
    )
