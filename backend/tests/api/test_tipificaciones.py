from datetime import UTC, date, datetime, timedelta

import pytest
from escenario import cab, telefono_de
from voz import contexto

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import EstadoAgente, PromesaPago, Tipificacion, Venta
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.telefonia.modelos import Llamada

K = "/api/v1/consola"
S = "/api/v1/telefonia/simulacion"


def llamada_terminada(client, ctx, db, resultado="completed", contestar=True, posicion=0):
    """Recorre simulación: llamar -> (contestar) -> finalizar. Devuelve el id de la llamada."""
    h = cab(ctx.agente)
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc, posicion).id},
        headers=h,
    )
    assert r.json()["permitida"], r.text
    lid = r.json()["llamada_id"]
    if contestar:
        client.post(f"{S}/llamadas/{lid}/eventos", json={"evento": "contestada"}, headers=h)
    body = {"evento": "finalizada", "resultado": resultado, "duracion_segundos": 30}
    client.post(f"{S}/llamadas/{lid}/eventos", json=body, headers=h)
    return lid


@pytest.fixture()
def ctx(esc, crear_usuario, reloj):
    return contexto(esc, crear_usuario, reloj)


def tipificar(client, ctx, lid, resultado, **extra):
    return client.post(
        f"{K}/tipificaciones",
        json={"llamada_id": lid, "resultado": resultado, **extra},
        headers=cab(ctx.agente),
    )


def campos(r):
    return [d["campo"] for d in r.json()["error"]["detalles"]]


def test_promesa_de_pago_efectos_completos(client, ctx, db, reloj):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "promesa_pago", observacion="  Paga el viernes  ",
        promesa={"monto": "250000.50", "fecha_pago": "2026-10-30"},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["resultado"] == "promesa_pago" and t["contacto_directo"] is True
    assert t["canal"] == "voz" and t["origen"] == "agente" and t["usuario_id"] == ctx.agente.id
    assert t["observacion"] == "Paga el viernes"
    assert t["promesa"] == {
        "id": t["promesa"]["id"], "monto": "250000.50", "fecha_pago": "2026-10-30",
        "numero_cuotas": 1, "descuento_porcentaje": "0.00", "estado": "vigente",
    }  # fmt: skip
    assert t["registro"] == {"estado": "gestionado", "intentos": 1, "proximo_intento_en": None}
    assert t["venta"] is None and t["creado_en"] == "2026-10-23T15:15:00Z"
    db.expire_all()
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert (cc.estado, cc.intentos, cc.ultimo_resultado, cc.reservado_por) == (
        "gestionado", 1, "promesa_pago", None,
    )  # fmt: skip
    assert cc.ultima_gestion_en == reloj() and cc.reservado_hasta is None
    intento = db.query(IntentoContacto).one()
    assert (intento.contacto_directo, intento.resultado) == (True, "promesa_pago")
    ag = db.get(EstadoAgente, ctx.agente.id)
    assert (ag.estado, ag.llamada_id) == ("disponible", None)
    assert db.query(PromesaPago).one().origen == "agente"
    aud = db.query(Auditoria).filter_by(accion="tipificacion.crear").one()
    assert aud.detalle == {
        "tipificacion_id": t["id"],
        "llamada_id": lid,
        "resultado": "promesa_pago",
    }
    assert "Paga el viernes" not in str([a.detalle for a in db.query(Auditoria)])
    est = client.get(f"{K}/estado", headers=cab(ctx.agente)).json()
    assert est["estado"] == "disponible" and est["tipificacion_pendiente"] is None
    assert client.get(f"{K}/llamadas/{lid}", headers=cab(ctx.agente)).json()["tipificada"] is True


@pytest.mark.parametrize("resultado", ["contactado", "rechazo"])
def test_contactado_y_rechazo(client, ctx, db, resultado):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, resultado)
    assert r.status_code == 201 and r.json()["contacto_directo"] is True
    assert r.json()["registro"]["estado"] == "gestionado"
    assert db.query(PromesaPago).count() == 0 and db.query(Venta).count() == 0


def test_venta(client, esc, crear_usuario, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj, tipo="venta", saldo_total=None)
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "venta", venta={"producto": "  Seguro   hogar ", "valor": "89900.00"}
    )
    assert r.status_code == 201, r.text
    venta = r.json()["venta"]
    assert venta == {
        "id": venta["id"],
        "producto": "Seguro hogar",
        "valor": "89900.00",
        "unidades": 1,
    }
    assert r.json()["registro"]["estado"] == "gestionado"
    assert db.query(Venta).one().origen == "agente"


def test_no_contesta_reprograma_en_ventana(client, ctx, db, reloj):
    reloj.fijar(datetime(2026, 10, 23, 23, 30, tzinfo=UTC))  # vie 18:30 Bogotá
    ctx.cc.reservado_hasta = reloj() + timedelta(minutes=15)
    db.commit()
    lid = llamada_terminada(client, ctx, db, resultado="no-answer", contestar=False)
    r = tipificar(client, ctx, lid, "no_contesta")
    assert r.status_code == 201, r.text
    assert r.json()["contacto_directo"] is False
    # 18:30 + 60 min = 19:30 -> fuera de franja -> sábado 08:00 Bogotá
    assert r.json()["registro"] == {
        "estado": "pendiente", "intentos": 1, "proximo_intento_en": "2026-10-24T13:00:00Z",
    }  # fmt: skip
    intento = db.query(IntentoContacto).one()
    assert (intento.contacto_directo, intento.resultado) == (False, "no_contesta")


def test_no_contesta_alcanza_max_intentos(client, ctx, db):
    ctx.cc.intentos = 2
    db.commit()
    lid = llamada_terminada(client, ctx, db, resultado="no-answer", contestar=False)
    r = tipificar(client, ctx, lid, "no_contesta")
    assert r.json()["registro"] == {
        "estado": "gestionado",
        "intentos": 3,
        "proximo_intento_en": None,
    }


def test_numero_errado_con_otros_telefonos(client, esc, crear_usuario, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj, numeros=("+573001234567", "+573109876543"))
    lid = llamada_terminada(client, ctx, db, resultado="busy", contestar=False)
    r = tipificar(client, ctx, lid, "numero_errado")
    assert r.status_code == 201, r.text
    assert r.json()["registro"] == {
        "estado": "pendiente",
        "intentos": 1,
        "proximo_intento_en": None,
    }
    ex = db.query(Exclusion).one()
    assert (ex.numero_e164, ex.motivo, ex.aplica_a, ex.creado_por) == (
        "+573001234567", "numero_errado", "todas", ctx.agente.id,
    )  # fmt: skip
    aud = db.query(Auditoria).filter_by(accion="exclusion.crear").one()
    assert aud.detalle == {"motivo": "numero_errado", "aplica_a": "todas"}
    assert "573001234567" not in str([a.detalle for a in db.query(Auditoria)])


def test_numero_errado_sin_otros_telefonos_descarta(client, ctx, db):
    lid = llamada_terminada(client, ctx, db, resultado="failed", contestar=False)
    r = tipificar(client, ctx, lid, "numero_errado")
    assert r.json()["registro"]["estado"] == "descartado"


def test_numero_errado_otro_telefono_ya_excluido_descarta(client, esc, crear_usuario, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj, numeros=("+573001234567", "+573109876543"))
    db.add(Exclusion(numero_e164="+573109876543", motivo="rne", aplica_a="cobranza", creado_por=1))
    db.commit()
    lid = llamada_terminada(client, ctx, db, resultado="failed", contestar=False)
    assert tipificar(client, ctx, lid, "numero_errado").json()["registro"]["estado"] == "descartado"


def test_numero_errado_no_duplica_exclusion_existente(client, ctx, db):
    db.add(Exclusion(numero_e164="+573001234567", motivo="manual", aplica_a="todas", creado_por=1))
    db.commit()
    # La exclusión impide llamar; se inserta la llamada directamente.
    ll = Llamada(
        campana_cliente_id=ctx.cc.id, telefono_id=telefono_de(db, ctx.cc).id,
        usuario_id=ctx.agente.id, call_sid="CAx", estado="fallida",
        iniciada_en=datetime(2026, 10, 23, 15, 0, tzinfo=UTC),
    )  # fmt: skip
    db.add(ll)
    db.commit()
    assert tipificar(client, ctx, ll.id, "numero_errado").status_code == 201
    assert db.query(Exclusion).count() == 1
    assert db.query(Auditoria).filter_by(accion="exclusion.crear").count() == 0


def test_falla_la_exclusion_no_queda_tipificacion(client, ctx, db, monkeypatch):
    from app.modulos.consola import tipificacion as modulo

    lid = llamada_terminada(client, ctx, db, resultado="failed", contestar=False)

    def boom(*a, **k):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(modulo.auditoria, "registrar", boom)
    r = tipificar(client, ctx, lid, "numero_errado")
    assert r.status_code == 500
    db.expire_all()
    assert db.query(Tipificacion).count() == 0 and db.query(Exclusion).count() == 0
    cc = db.get(CampanaCliente, ctx.cc.id)
    assert cc.intentos == 0 and cc.estado == "en_gestion"
    assert db.get(EstadoAgente, ctx.agente.id).estado == "tipificando"


def test_volver_a_llamar(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    cuando = "2026-10-26T10:00:00-05:00"
    r = tipificar(
        client, ctx, lid, "volver_a_llamar", volver_a_llamar_en=cuando, contacto_directo=True
    )
    assert r.status_code == 201, r.text
    assert r.json()["contacto_directo"] is True
    assert r.json()["volver_a_llamar_en"] == "2026-10-26T15:00:00Z"
    assert r.json()["registro"] == {
        "estado": "pendiente", "intentos": 1, "proximo_intento_en": "2026-10-26T15:00:00Z",
    }  # fmt: skip


def test_volver_a_llamar_sin_contacto_directo(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "volver_a_llamar",
        volver_a_llamar_en="2026-10-26T10:00:00-05:00", contacto_directo=False,
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["contacto_directo"] is False
    assert db.query(IntentoContacto).one().contacto_directo is False


def test_volver_a_llamar_fuera_de_franja(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "volver_a_llamar",
        volver_a_llamar_en="2026-10-25T10:00:00-05:00", contacto_directo=True,
    )  # fmt: skip
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VOLVER_A_LLAMAR_FUERA_DE_FRANJA"
    assert r.json()["error"]["detalles"] == [
        {
            "campo": "volver_a_llamar_en",
            "mensaje": "Fuera de franja. Próxima ventana: 2026-10-26T07:00:00-05:00",
        }
    ]
    assert db_sin_tipificaciones(client, ctx)


def db_sin_tipificaciones(client, ctx):
    return client.get(f"{K}/estado", headers=cab(ctx.agente)).json()["estado"] == "tipificando"


@pytest.mark.parametrize(
    "cuando",
    [
        "2026-10-23T10:18:00-05:00",
        "2026-11-30T10:00:00-05:00",
        "2026-10-26T10:00:00",
        "no-es-fecha",
    ],
)
def test_volver_a_llamar_limites_y_formato(client, ctx, db, cuando):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client, ctx, lid, "volver_a_llamar", volver_a_llamar_en=cuando, contacto_directo=True
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert campos(r) == ["volver_a_llamar_en"]


@pytest.mark.parametrize(
    ("resultado", "extra", "esperados"),
    [
        ("promesa_pago", {}, ["promesa"]),
        ("rechazo", {"promesa": {"monto": "1", "fecha_pago": "2026-10-30"}}, ["promesa"]),
        ("rechazo", {"venta": {"producto": "xx", "valor": "1"}}, ["venta"]),
        ("rechazo", {"volver_a_llamar_en": "2026-10-26T10:00:00-05:00"}, ["volver_a_llamar_en"]),
        ("rechazo", {"contacto_directo": True}, ["contacto_directo"]),
        ("volver_a_llamar", {}, ["volver_a_llamar_en", "contacto_directo"]),
        ("volver_a_llamar", {"contacto_directo": True}, ["volver_a_llamar_en"]),
    ],
)
def test_campos_condicionados(client, ctx, db, resultado, extra, esperados):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, resultado, **extra)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert campos(r) == esperados


def test_venta_exige_objeto_venta(client, esc, crear_usuario, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj, tipo="venta")
    lid = llamada_terminada(client, ctx, db)
    assert campos(tipificar(client, ctx, lid, "venta")) == ["venta"]


@pytest.mark.parametrize(
    "resultado", ["contactado", "promesa_pago", "venta", "rechazo", "volver_a_llamar"]
)
@pytest.mark.parametrize("terminal", ["busy", "no-answer", "failed", "canceled"])
def test_resultado_incoherente_con_llamada_no_contestada(client, ctx, db, resultado, terminal):
    lid = llamada_terminada(client, ctx, db, resultado=terminal, contestar=False)
    extra = {
        "promesa_pago": {"promesa": {"monto": "1000", "fecha_pago": "2026-10-30"}},
        "venta": {"venta": {"producto": "Seguro", "valor": "1000"}},
        "volver_a_llamar": {
            "volver_a_llamar_en": "2026-10-26T10:00:00-05:00",
            "contacto_directo": True,
        },
    }.get(resultado, {})
    r = tipificar(client, ctx, lid, resultado, **extra)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_INCOHERENTE"


def test_resultado_no_permitido_por_tipo(client, esc, crear_usuario, reloj, db):
    ctx = contexto(esc, crear_usuario, reloj)  # cobranza
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "venta", venta={"producto": "Seguro", "valor": "1000"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_NO_PERMITIDO"
    ctx2 = contexto(esc, crear_usuario, reloj, tipo="venta")
    lid2 = llamada_terminada(client, ctx2, db)
    r = tipificar(
        client, ctx2, lid2, "promesa_pago", promesa={"monto": "1", "fecha_pago": "2026-10-30"}
    )
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "RESULTADO_NO_PERMITIDO"


@pytest.mark.parametrize(
    ("promesa", "campo"),
    [
        ({"monto": "1500000.01", "fecha_pago": "2026-10-30"}, "promesa.monto"),  # > saldo_total
        ({"monto": "0", "fecha_pago": "2026-10-30"}, "promesa.monto"),
        ({"monto": "-5", "fecha_pago": "2026-10-30"}, "promesa.monto"),
        ({"monto": "10.123", "fecha_pago": "2026-10-30"}, "promesa.monto"),
        ({"monto": "abc", "fecha_pago": "2026-10-30"}, "promesa.monto"),
        ({"monto": "NaN", "fecha_pago": "2026-10-30"}, "promesa.monto"),
        ({"monto": "1000", "fecha_pago": "2026-10-22"}, "promesa.fecha_pago"),  # pasada
        ({"monto": "1000", "fecha_pago": "2026-12-23"}, "promesa.fecha_pago"),  # > 60 días
        ({"monto": "1000", "fecha_pago": "31/10/2026"}, "promesa.fecha_pago"),
    ],
)
def test_validaciones_de_promesa(client, ctx, db, promesa, campo):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "promesa_pago", promesa=promesa)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
    assert campo in campos(r)


def test_promesa_limites_validos(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    # hoy_local = 2026-10-23; +60 días = 2026-12-22; monto = saldo_total exacto
    r = tipificar(
        client,
        ctx,
        lid,
        "promesa_pago",
        promesa={"monto": "1500000.00", "fecha_pago": "2026-12-22"},
    )
    assert r.status_code == 201, r.text


def test_promesa_hoy_es_valida(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(
        client,
        ctx,
        lid,
        "promesa_pago",
        promesa={"monto": "10", "fecha_pago": str(date(2026, 10, 23))},
    )
    assert r.status_code == 201


@pytest.mark.parametrize(
    "venta",
    [{"producto": "x", "valor": "10"}, {"producto": "Seguro", "valor": "0"},
     {"producto": "Seguro", "valor": "10.001"}, {"producto": "S" * 121, "valor": "10"}],
)  # fmt: skip
def test_validaciones_de_venta(client, esc, crear_usuario, reloj, db, venta):
    ctx = contexto(esc, crear_usuario, reloj, tipo="venta")
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "venta", venta=venta)
    assert r.status_code == 422 and campos(r)[0].startswith("venta.")


def test_observacion_vacia_es_null_y_larga_es_422(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "rechazo", observacion="   ")
    assert r.status_code == 201 and r.json()["observacion"] is None


def test_observacion_demasiado_larga(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    r = tipificar(client, ctx, lid, "rechazo", observacion="x" * 1001)
    assert r.status_code == 422 and campos(r) == ["observacion"]


def test_estados_de_llamada_409(client, ctx, db, esc, reloj):
    h = cab(ctx.agente)
    r = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=h,
    )
    lid = r.json()["llamada_id"]
    en_curso = tipificar(client, ctx, lid, "rechazo")
    assert en_curso.status_code == 409 and en_curso.json()["error"]["codigo"] == "LLAMADA_EN_CURSO"
    client.post(f"{S}/llamadas/{lid}/eventos", json={"evento": "contestada"}, headers=h)
    client.post(
        f"{S}/llamadas/{lid}/eventos",
        json={"evento": "finalizada", "resultado": "completed"},
        headers=h,
    )
    assert tipificar(client, ctx, lid, "rechazo").status_code == 201
    doble = tipificar(client, ctx, lid, "rechazo")
    assert doble.status_code == 409 and doble.json()["error"]["codigo"] == "LLAMADA_YA_TIPIFICADA"
    assert db.query(Tipificacion).count() == 1
    # bloqueada
    esc.estado(ctx.agente, "pausa", reloj())
    ctx.cc.estado = "pendiente"
    db.commit()
    esc.reservar(ctx.cc, ctx.agente, reloj())
    b = client.post(
        f"{S}/llamadas",
        json={"campana_cliente_id": ctx.cc.id, "telefono_id": telefono_de(db, ctx.cc).id},
        headers=h,
    ).json()
    assert b["permitida"] is False
    r = tipificar(client, ctx, b["llamada_id"], "rechazo")
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "LLAMADA_BLOQUEADA"


def test_llamada_ajena_o_inexistente_404(client, ctx, db, crear_usuario):
    lid = llamada_terminada(client, ctx, db)
    otro = crear_usuario("agente")
    r = client.post(
        f"{K}/tipificaciones", json={"llamada_id": lid, "resultado": "rechazo"}, headers=cab(otro)
    )
    assert r.status_code == 404
    assert tipificar(client, ctx, 99999, "rechazo").status_code == 404
    assert tipificar(client, ctx, lid, "inventado").status_code == 422


def test_tras_tipificar_se_puede_tomar_y_llamar_otro(client, ctx, db, esc):
    lid = llamada_terminada(client, ctx, db)
    # Mientras hay tipificación pendiente no se puede tomar otro registro.
    otro = esc.registro(ctx.campana)
    r = client.post(f"{K}/registros/{otro.id}/tomar", headers=cab(ctx.agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "TIPIFICACION_PENDIENTE"
    tipificar(client, ctx, lid, "rechazo")
    assert client.post(f"{K}/registros/{otro.id}/tomar", headers=cab(ctx.agente)).status_code == 200


def test_historial_en_la_ficha_tras_tipificar(client, ctx, db):
    lid = llamada_terminada(client, ctx, db)
    tipificar(
        client, ctx, lid, "volver_a_llamar", volver_a_llamar_en="2026-10-26T10:00:00-05:00",
        contacto_directo=False, observacion="Pidió llamar luego",
    )  # fmt: skip
    ficha = client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=cab(ctx.agente))
    # el registro tiene proximo_intento_en futuro: no disponible, pero la ficha propia se reabre
    assert ficha.status_code == 409
    ctx.cc.proximo_intento_en = None
    db.commit()
    ficha = client.post(f"{K}/registros/{ctx.cc.id}/tomar", headers=cab(ctx.agente)).json()
    h = ficha["historial"]
    assert len(h) == 1 and h[0]["resultado"] == "volver_a_llamar"
    assert (
        h[0]["agente_nombre"] == ctx.agente.nombre and h[0]["observacion"] == "Pidió llamar luego"
    )
    assert h[0]["volver_a_llamar_en"] == "2026-10-26T15:00:00Z"
    assert ficha["ultimo_resultado"] == "volver_a_llamar" and ficha["intentos"] == 1


# ---- Listado por campaña ---------------------------------------------------------------------
def test_listado_de_tipificaciones_por_campana(client, ctx, db, h_admin, h_supervisor, reloj):
    lid = llamada_terminada(client, ctx, db)
    tipificar(client, ctx, lid, "rechazo", observacion="No le interesa")
    r = client.get(f"/api/v1/campanas/{ctx.campana.id}/tipificaciones", headers=h_admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 1 and cuerpo["page"] == 1
    t = cuerpo["items"][0]
    assert t["resultado"] == "rechazo" and t["cliente_nombre"] == "María Pérez"
    assert t["agente_nombre"] == ctx.agente.nombre and "registro" not in t
    base = f"/api/v1/campanas/{ctx.campana.id}/tipificaciones"
    assert client.get(f"{base}?resultado=venta", headers=h_supervisor).json()["total"] == 0
    assert client.get(f"{base}?origen=agente_ia", headers=h_admin).json()["total"] == 0
    assert (
        client.get(f"{base}?desde=2026-10-23&hasta=2026-10-23", headers=h_admin).json()["total"]
        == 1
    )
    assert client.get(f"{base}?desde=2026-10-24", headers=h_admin).json()["total"] == 0
    assert client.get(f"{base}?hasta=2026-10-22", headers=h_admin).json()["total"] == 0
    assert client.get(f"{base}?resultado=otro", headers=h_admin).status_code == 422
    assert client.get(f"{base}?desde=0001-01-01", headers=h_admin).status_code == 422
    assert client.get("/api/v1/campanas/9999/tipificaciones", headers=h_admin).status_code == 404
    assert client.get(base, headers=cab(ctx.agente)).status_code == 403


def test_listado_borde_de_dia_local(client, ctx, db, h_admin, reloj):
    """23:30 en Bogotá del 23 cae en el día local 23 aunque en UTC ya sea el 24."""
    reloj.fijar(datetime(2026, 10, 24, 4, 30, tzinfo=UTC))
    ctx.cc.reservado_hasta = reloj() + timedelta(minutes=15)
    db.commit()
    reloj.fijar(datetime(2026, 10, 23, 15, 15, tzinfo=UTC))
    lid = llamada_terminada(client, ctx, db)
    reloj.fijar(datetime(2026, 10, 24, 4, 30, tzinfo=UTC))
    tipificar(client, ctx, lid, "rechazo")
    base = f"/api/v1/campanas/{ctx.campana.id}/tipificaciones"
    assert (
        client.get(f"{base}?desde=2026-10-23&hasta=2026-10-23", headers=h_admin).json()["total"]
        == 1
    )
    assert client.get(f"{base}?desde=2026-10-24", headers=h_admin).json()["total"] == 0
