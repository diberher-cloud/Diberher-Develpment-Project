from datetime import timedelta

import pytest
from escenario import cab

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.consola.servicio import _reservar_atomico, enmascarar_telefono

K = "/api/v1/consola"


@pytest.fixture()
def agente(crear_usuario):
    return crear_usuario("agente")


@pytest.fixture()
def campana(esc, agente):
    c = esc.campana(
        guion="Buenos días, {{nombre}}. Le habla {{agente}} de {{empresa}}, debe {{saldo_mora}}."
    )
    esc.asignar(c, agente)
    return c


def tomar(client, agente, cc):
    return client.post(f"{K}/registros/{cc.id}/tomar", headers=cab(agente))


def test_mascara():
    assert enmascarar_telefono("+573001234567") == "+57300****567"
    assert enmascarar_telefono("+576012345678") == "+57601****678"


def test_campanas_asignadas_con_pendientes(client, agente, campana, esc, reloj):
    esc.registro(campana)
    esc.registro(campana)
    otra = esc.campana()  # no asignada
    esc.registro(otra)
    inactiva = esc.campana(estado="pausada")
    esc.asignar(inactiva, agente)
    r = client.get(f"{K}/campanas", headers=cab(agente))
    assert r.json() == [
        {"id": campana.id, "nombre": campana.nombre, "tipo": "cobranza", "pendientes": 2}
    ]


def test_lista_de_trabajo_elegibilidad_y_orden(client, agente, campana, esc, reloj, crear_usuario):
    ahora = reloj()
    a = esc.registro(campana, nombre="Ana")
    b = esc.registro(campana, nombre="Beto", proximo_intento_en=ahora - timedelta(hours=1))
    esc.registro(campana, nombre="Futuro", proximo_intento_en=ahora + timedelta(hours=1))
    esc.registro(campana, nombre="Gestionado", estado="gestionado")
    esc.registro(campana, nombre="Agotado", intentos=3)
    otro = crear_usuario("agente")
    ajeno = esc.registro(campana, nombre="Ajeno")
    esc.reservar(ajeno, otro, ahora)
    caducado = esc.registro(campana, nombre="Caducado")
    esc.reservar(caducado, otro, ahora, minutos=-1)
    mio = esc.registro(campana, nombre="Mio")
    esc.reservar(mio, agente, ahora)
    r = client.get(f"{K}/registros", headers=cab(agente))
    assert r.status_code == 200
    nombres = [i["nombre_cliente"] for i in r.json()["items"]]
    # primero el reservado por mí; luego por COALESCE(proximo_intento_en, creado_en), id
    assert nombres[0] == "Mio" and set(nombres) == {"Mio", "Ana", "Beto", "Caducado"}
    assert nombres.index("Beto") < nombres.index("Ana")
    primero = r.json()["items"][0]
    assert primero["reservado_por_mi"] is True and primero["max_intentos"] == 3
    assert r.json()["total"] == 4
    assert set(primero) == {
        "id", "campana_id", "campana_nombre", "tipo_campana", "nombre_cliente", "estado",
        "intentos", "max_intentos", "ultimo_resultado", "ultima_gestion_en", "proximo_intento_en",
        "saldo_mora", "dias_mora", "producto", "reservado_por_mi",
    }  # fmt: skip
    assert primero["saldo_mora"] == "250000.50"
    assert a.id and b.id


def test_filtro_por_campana_no_asignada(client, agente, campana, esc):
    otra = esc.campana()
    r = client.get(f"{K}/registros?campana_id={otra.id}", headers=cab(agente))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"
    assert (
        client.get(f"{K}/registros?campana_id={campana.id}", headers=cab(agente)).status_code == 200
    )


def test_tomar_devuelve_ficha_enmascarada(client, agente, campana, esc, db, reloj):
    cc = esc.registro(campana, numeros=("+573001234567", "+576012345678"))
    r = tomar(client, agente, cc)
    assert r.status_code == 200, r.text
    ficha = r.json()
    assert ficha["estado"] == "en_gestion" and ficha["reservado_hasta"] == "2026-10-23T15:30:00Z"
    assert ficha["guion"] == (
        f"Buenos días, María Pérez. Le habla {agente.nombre} de Mi Empresa S.A.S., "
        "debe $ 250.000,50."
    )
    assert [t["numero_mascara"] for t in ficha["telefonos"]] == ["+57300****567", "+57601****678"]
    assert all(
        t["llamable"] and t["motivos"] == [] and not t["excluido"] for t in ficha["telefonos"]
    )
    assert ficha["cumplimiento"]["permitido"] and ficha["cumplimiento"]["politica_version"] == 1
    assert ficha["cumplimiento"]["momento_local"] == "2026-10-23T10:15:00-05:00"
    assert ficha["saldo_total"] == "1500000.00" and ficha["historial"] == []
    assert "+573001234567" not in r.text and "3001234567" not in r.text
    acciones = [a.accion for a in db.query(Auditoria).filter(Auditoria.accion.like("consola.%"))]
    assert acciones == ["consola.tomar", "consola.ficha_ver"]
    # GET de la ficha exige reserva propia y audita.
    g = client.get(f"{K}/registros/{cc.id}", headers=cab(agente))
    assert g.status_code == 200 and g.json()["id"] == cc.id
    assert db.query(Auditoria).filter_by(accion="consola.ficha_ver").count() == 2
    assert "3001234567" not in g.text


def test_ficha_exige_reserva_propia(client, agente, campana, esc, crear_usuario, reloj):
    cc = esc.registro(campana)
    r = client.get(f"{K}/registros/{cc.id}", headers=cab(agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_NO_RESERVADO"
    assert client.get(f"{K}/registros/9999", headers=cab(agente)).status_code == 404
    otro = crear_usuario("agente")
    esc.asignar(campana, otro)
    assert tomar(client, otro, cc).status_code == 200
    assert client.get(f"{K}/registros/{cc.id}", headers=cab(agente)).status_code == 409


def test_telefono_excluido_y_fuera_de_franja_no_llamable(client, agente, campana, esc, db, reloj):
    from app.modulos.exclusiones.modelos import Exclusion

    cc = esc.registro(campana, numeros=("+573001234567", "+573109876543"))
    db.add(
        Exclusion(
            numero_e164="+573109876543", motivo="numero_errado", aplica_a="todas", creado_por=1
        )
    )
    db.commit()
    ficha = tomar(client, agente, cc).json()
    t1, t2 = ficha["telefonos"]
    assert t1["llamable"] and not t2["llamable"] and t2["excluido"]
    assert t2["motivos"] == [{"codigo": "EXCLUIDO", "mensaje": "Número excluido (numero_errado)."}]
    # Domingo: ninguno es llamable y los motivos de cumplimiento aparecen en cada teléfono.
    from datetime import UTC, datetime

    reloj.fijar(datetime(2026, 10, 25, 15, 0, tzinfo=UTC))
    ficha = tomar(client, agente, cc).json()
    assert ficha["cumplimiento"]["permitido"] is False
    assert [m["codigo"] for m in ficha["telefonos"][0]["motivos"]] == ["DIA_SIN_FRANJA"]
    assert [m["codigo"] for m in ficha["telefonos"][1]["motivos"]] == ["EXCLUIDO", "DIA_SIN_FRANJA"]
    assert not any(t["llamable"] for t in ficha["telefonos"])


def test_excluido_para_otro_tipo_de_campana_sigue_llamable(client, agente, campana, esc, db):
    from app.modulos.exclusiones.modelos import Exclusion

    cc = esc.registro(campana)
    db.add(Exclusion(numero_e164="+573001234567", motivo="manual", aplica_a="venta", creado_por=1))
    db.commit()
    assert tomar(client, agente, cc).json()["telefonos"][0]["llamable"] is True


def test_errores_de_tomar(client, agente, campana, esc, crear_usuario, reloj):
    ahora = reloj()
    assert client.post(f"{K}/registros/9999/tomar", headers=cab(agente)).status_code == 404
    ajena = esc.campana()
    r = tomar(client, agente, esc.registro(ajena))
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "CAMPANA_NO_ASIGNADA"
    for kw in ({"estado": "gestionado"}, {"estado": "descartado"}, {"intentos": 3},
               {"proximo_intento_en": ahora + timedelta(hours=1)}):  # fmt: skip
        r = tomar(client, agente, esc.registro(campana, **kw))
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_NO_DISPONIBLE", kw
    pausada = esc.campana(estado="pausada")
    esc.asignar(pausada, agente)
    r = tomar(client, agente, esc.registro(pausada))
    assert r.json()["error"]["codigo"] == "REGISTRO_NO_DISPONIBLE"
    otro = crear_usuario("agente")
    esc.asignar(campana, otro)
    cc = esc.registro(campana)
    assert tomar(client, otro, cc).status_code == 200
    r = tomar(client, agente, cc)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_RESERVADO"


def test_estado_del_agente_bloquea_tomar(client, agente, campana, esc, reloj):
    cc = esc.registro(campana)
    esc.estado(agente, "en_llamada", reloj())
    assert tomar(client, agente, cc).json()["error"]["codigo"] == "AGENTE_EN_LLAMADA"
    esc.estado(agente, "tipificando", reloj())
    assert tomar(client, agente, cc).json()["error"]["codigo"] == "TIPIFICACION_PENDIENTE"


def test_una_reserva_por_agente(client, agente, campana, esc, db):
    a, b = esc.registro(campana), esc.registro(campana)
    assert tomar(client, agente, a).status_code == 200
    assert tomar(client, agente, b).status_code == 200
    db.refresh(a)
    db.refresh(b)
    assert (a.estado, a.reservado_por) == ("pendiente", None)
    assert (b.estado, b.reservado_por) == ("en_gestion", agente.id)


def test_renovar_y_reserva_caducada(client, agente, campana, esc, crear_usuario, db, reloj):
    cc = esc.registro(campana)
    tomar(client, agente, cc)
    reloj.avanzar(minutes=10)
    r = tomar(client, agente, cc)
    assert r.status_code == 200 and r.json()["reservado_hasta"] == "2026-10-23T15:40:00Z"
    otro = crear_usuario("agente")
    esc.asignar(campana, otro)
    assert tomar(client, otro, cc).status_code == 409
    reloj.avanzar(minutes=16)  # caduca la reserva del primero
    r = tomar(client, otro, cc)
    assert r.status_code == 200
    db.refresh(cc)
    assert cc.reservado_por == otro.id


def test_carrera_la_actualizacion_condicional_decide(
    esc, campana, agente, crear_usuario, db, reloj
):
    """Dos sesiones llegan a la vez: el UPDATE condicional deja pasar solo a una."""
    otro = crear_usuario("agente")
    esc.asignar(campana, otro)
    cc = esc.registro(campana)
    ahora = reloj()
    assert _reservar_atomico(db, cc.id, agente.id, ahora, ahora + timedelta(minutes=15)) is True
    assert _reservar_atomico(db, cc.id, otro.id, ahora, ahora + timedelta(minutes=15)) is False
    assert _reservar_atomico(db, cc.id, agente.id, ahora, ahora + timedelta(minutes=20)) is True
    assert _reservar_atomico(db, cc.id, otro.id, ahora + timedelta(minutes=30), ahora) is True


def test_soltar(client, agente, campana, esc, db):
    cc = esc.registro(campana)
    r = client.post(f"{K}/registros/{cc.id}/soltar", headers=cab(agente))
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "REGISTRO_NO_RESERVADO"
    tomar(client, agente, cc)
    assert client.post(f"{K}/registros/{cc.id}/soltar", headers=cab(agente)).status_code == 204
    db.refresh(cc)
    assert (cc.estado, cc.reservado_por) == ("pendiente", None)


def test_solo_agentes(client, h_admin, h_supervisor):
    for h in (h_admin, h_supervisor):
        assert client.get(f"{K}/registros", headers=h).status_code == 403
        assert client.get(f"{K}/campanas", headers=h).status_code == 403
        assert client.post(f"{K}/registros/1/tomar", headers=h).status_code == 403
