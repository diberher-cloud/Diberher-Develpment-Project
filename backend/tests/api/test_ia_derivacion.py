"""Tomar, asignar, traspasar, devolver a la IA, instrucciones y kill switch (casos D)."""

import pytest
from ia import escenario_ia, escribir, herramienta, mensajes_de, usar_llm
from sqlalchemy import select
from wa import NUMERO, entrante

from app.config import get_settings
from app.modulos.agente_ia.modelos import (
    ConfiguracionGlobal,
    ConfiguracionIACampana,
    HistorialIA,
    InstruccionSupervisor,
)
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.trabajos.modelos import Trabajo

API = "/api/v1"


@pytest.fixture()
def e(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario, cabeceras, admin):
    from types import SimpleNamespace

    ctx = escenario_ia(esc, crear_usuario, db)
    llm = usar_llm([{"texto": "Hola, ¿su documento?"}] * 6)
    escribir(client, firmar_twilio, correr_trabajos, reloj, "hola")
    db.expire_all()
    conv = db.scalar(select(Conversacion))

    def decir(t):
        escribir(client, firmar_twilio, correr_trabajos, reloj, t)
        db.expire_all()

    return SimpleNamespace(
        ctx=ctx, conv_id=conv.id, llm=llm, client=client, db=db, h_admin=cabeceras(admin),
        h_agente=cabeceras(ctx.agente), decir=decir, reloj=reloj, correr=correr_trabajos,
        firmar=firmar_twilio, esc=esc, crear_usuario=crear_usuario, cabeceras=cabeceras,
    )  # fmt: skip


def conv_de(e):
    e.db.expire_all()
    return e.db.get(Conversacion, e.conv_id)


def test_d1_admin_toma_conversacion_ia_sin_cola(e):
    r = e.client.post(f"{API}/conversaciones/{e.conv_id}/tomar", headers=e.h_admin)
    assert r.status_code == 200 and r.json()["atendida_por"] == "humano"
    assert e.db.scalar(select(ColaAtencion).where(ColaAtencion.estado != "cerrada")) is None
    antes = e.llm.llamadas
    e.decir("sigo aquí")
    assert (
        e.llm.llamadas == antes
        and e.db.scalar(
            select(Trabajo).where(Trabajo.tipo == "ia.turno", Trabajo.estado == "pendiente")
        )
        is None
    )


def test_d2_agente_no_puede_tomar_conversacion_ia(e):
    e.esc.estado(e.ctx.agente, "disponible", e.reloj())
    r = e.client.post(f"{API}/conversaciones/{e.conv_id}/tomar", headers=e.h_agente)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_ASIGNADA"


def test_d3_asignar_desde_ia(e):
    r = e.client.post(
        f"{API}/conversaciones/{e.conv_id}/asignar",
        json={"usuario_id": e.ctx.agente.id},
        headers=e.h_admin,
    )
    assert r.status_code == 200 and r.json()["atendida_por"] == "humano"


def test_d4_traspasar_a_cola_supervisor(e):
    r = e.client.post(
        f"{API}/conversaciones/{e.conv_id}/traspasar",
        json={"resumen": "Revisar intereses"},
        headers=e.h_admin,
    )
    assert r.status_code == 200 and r.json()["atendida_por"] == "sin_asignar"
    fila = e.db.scalar(select(ColaAtencion).where(ColaAtencion.estado == "pendiente"))
    assert (fila.motivo, fila.resumen) == ("supervisor", "Revisar intereses")
    again = e.client.post(f"{API}/conversaciones/{e.conv_id}/traspasar", json={}, headers=e.h_admin)
    assert again.status_code == 409 and again.json()["error"]["codigo"] == "CONVERSACION_NO_IA"


def test_d5_devolver_a_la_ia_con_intervencion(e):
    e.client.post(f"{API}/conversaciones/{e.conv_id}/tomar", headers=e.h_admin)
    # el cliente escribe durante el periodo humano y el asesor responde
    entrante(e.client, e.firmar, NUMERO, "¿Me dan más plazo?")
    e.correr(e.reloj())

    e.client.post(
        f"{API}/conversaciones/{e.conv_id}/mensajes",
        json={
            "texto": "Puede pagar hasta el 6 de noviembre",
            "idempotencia_clave": "7b0f6f4e-6d2b-4a53-9f6e-0d5c1d1d7b11",
        },
        headers=e.h_admin,
    )
    r = e.client.post(f"{API}/conversaciones/{e.conv_id}/devolver-ia", json={}, headers=e.h_admin)
    assert r.status_code == 200 and r.json()["atendida_por"] == "ia"
    filas = list(e.db.scalars(select(HistorialIA).order_by(HistorialIA.secuencia)))
    assert filas[-2].tipo == "intervencion" and filas[-1].tipo == "vuelta_ia"
    bloque = filas[-2].contenido[0]["text"]
    assert "<mensaje_cliente" in bloque and "¿Me dan más plazo?" in bloque
    assert "<mensaje_asesor" in bloque and "6 de noviembre" in bloque
    assert not any(f.rol == "assistant" and "6 de noviembre" in str(f.contenido) for f in filas)
    assert all(
        m.procesado_ia_en
        for m in e.db.scalars(
            select(Mensaje).where(
                Mensaje.direccion == "entrante", Mensaje.procesado_en.is_not(None)
            )
        )
    )
    # el siguiente turno la lleva en el `user` y el `system` de vuelta, sin `assistant` fabricado
    e.decir("gracias")
    ultima = e.llm.peticiones[-1]["mensajes"]
    texto = str(ultima)
    assert "<intervencion_humana>" in texto and "vuelve a ti" in texto


def test_d6_devolver_sin_requisitos(e):
    e.client.post(f"{API}/conversaciones/{e.conv_id}/tomar", headers=e.h_admin)
    cfg = e.db.get(ConfiguracionIACampana, e.ctx.campana.id)
    cfg.activa = False
    e.db.commit()
    r = e.client.post(f"{API}/conversaciones/{e.conv_id}/devolver-ia", json={}, headers=e.h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "IA_NO_DISPONIBLE"
    cfg.activa = True
    e.db.commit()
    from datetime import timedelta

    from app.modulos.exclusiones.modelos import Exclusion

    e.db.add(Exclusion(numero_e164=NUMERO, motivo="solicitud_titular", aplica_a="todas", canal="whatsapp",
                       origen="sistema", creado_en=e.reloj() + timedelta(hours=1)))  # fmt: skip
    e.db.commit()
    r = e.client.post(f"{API}/conversaciones/{e.conv_id}/devolver-ia", json={}, headers=e.h_admin)
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CLIENTE_OPT_OUT"
    e.client.post(
        f"{API}/conversaciones/{e.conv_id}/cerrar",
        json={"tipificacion": {"resultado": "no_contesta"}},
        headers=e.h_admin,
    )


def test_d7_instrucciones(e):
    r = e.client.post(
        f"{API}/conversaciones/{e.conv_id}/instrucciones",
        json={"texto": "Ofrézcale 6 cuotas si lo pide."},
        headers=e.h_admin,
    )
    assert r.status_code == 201 and r.json()["aplicada_en"] is None
    assert (
        e.client.post(
            f"{API}/conversaciones/{e.conv_id}/instrucciones",
            json={"texto": "x"},
            headers=e.h_agente,
        ).status_code
        == 403
    )
    e.decir("otra consulta")
    ult = e.llm.peticiones[-1]["mensajes"]
    assert any(
        m["role"] == "system"
        and m["content"] == "Instrucción del supervisor: Ofrézcale 6 cuotas si lo pide."
        for m in ult
    )
    assert e.db.scalar(select(InstruccionSupervisor)).aplicada_en is not None
    assert "Instrucción del supervisor" not in " ".join(
        m.cuerpo or "" for m in mensajes_de(e.db, e.conv_id)
    )
    e.client.post(f"{API}/conversaciones/{e.conv_id}/tomar", headers=e.h_admin)
    r = e.client.post(
        f"{API}/conversaciones/{e.conv_id}/instrucciones", json={"texto": "hola"}, headers=e.h_admin
    )
    assert r.status_code == 409 and r.json()["error"]["codigo"] == "CONVERSACION_NO_IA"


def test_d8_cerrar_conversacion_ya_tipificada(
    client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario, h_admin
):
    ctx = escenario_ia(esc, crear_usuario, db)
    usar_llm([herramienta("verificar_identidad", numero_documento="1020304050"),
              herramienta("programar_seguimiento", fecha_hora_local="2026-10-26T09:00", motivo="Llamar"),
              {"texto": "Listo"}])  # fmt: skip
    escribir(client, firmar_twilio, correr_trabajos, reloj, "hola")
    cid = db.scalar(select(Conversacion.id))
    client.post(f"{API}/conversaciones/{cid}/tomar", headers=h_admin)
    r = client.post(
        f"{API}/conversaciones/{cid}/cerrar",
        json={"tipificacion": {"resultado": "contactado"}},
        headers=h_admin,
    )
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["campo"] == "tipificacion"
    r = client.post(f"{API}/conversaciones/{cid}/cerrar", json={}, headers=h_admin)
    assert r.status_code == 200 and r.json()["conversacion"]["estado"] == "cerrada"
    assert ctx.numero


def test_d9_desactivar_campana_traspasa_todo(e):
    from app.modulos.clientes.modelos import Telefono

    for i, n in enumerate(("+573005550001", "+573005550002")):
        e.db.add(
            Telefono(
                cliente_id=e.ctx.pedro.cliente_id,
                numero_e164=n,
                tipo_linea="movil",
                prioridad=i + 2,
            )
        )
    e.db.commit()
    # una de las tres con un entrante sin responder
    for n in ("+573005550001", "+573005550002"):
        entrante(e.client, e.firmar, n, "hola")
    e.correr(e.reloj())  # procesa los entrantes (los turnos quedan en debounce)
    r = e.client.post(
        f"{API}/campanas/{e.ctx.campana.id}/ia/desactivar", json={}, headers=e.h_admin
    )
    assert r.status_code == 200 and r.json()["desactivada_motivo"] == "manual"
    e.reloj.avanzar(seconds=10)
    e.correr(e.reloj())
    e.db.expire_all()
    convs = list(e.db.scalars(select(Conversacion)))
    assert len(convs) == 3 and all(c.atendida_por == "sin_asignar" for c in convs)
    motivos = {f.motivo for f in e.db.scalars(select(ColaAtencion))}
    assert "ia_desactivada" in motivos
    entrante(e.client, e.firmar, "+573005550001", "otra")
    e.correr(e.reloj())
    assert (
        e.db.scalar(
            select(Trabajo).where(Trabajo.tipo == "ia.turno", Trabajo.estado == "pendiente")
        )
        is None
    )


def test_d10_global_y_entorno(e, monkeypatch):
    r = e.client.put(f"{API}/configuracion/ia", json={"ia_activa": False}, headers=e.h_admin)
    assert r.status_code == 200 and r.json()["ia_activa"] is False
    e.reloj.avanzar(seconds=10)
    e.correr(e.reloj())
    assert conv_de(e).atendida_por == "sin_asignar"
    assert e.db.get(ConfiguracionGlobal, "ia_activa").valor is False
    e.client.put(f"{API}/configuracion/ia", json={"ia_activa": True}, headers=e.h_admin)
    monkeypatch.setattr(get_settings(), "ia_habilitada", False)
    assert (
        e.client.get(f"{API}/configuracion/ia", headers=e.h_admin).json()["ia_habilitada_entorno"]
        is False
    )
