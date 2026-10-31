"""QA 2C: casos H sin test dedicado (H13) y constancias."""

from datetime import timedelta

import pytest
from ia import escenario_ia, escribir, mensajes_de, usar_llm
from sqlalchemy import select
from test_qa_2c_modelo_malicioso import VERIFICAR, reg, sim

from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones.modelos import Conversacion


@pytest.fixture()
def c(client, firmar_twilio, correr_trabajos, reloj, db, esc, crear_usuario):
    ctx = escenario_ia(esc, crear_usuario, db)

    class X: ...

    x = X()
    x.ctx, x.db, x.reloj, x.esc = ctx, db, reloj, esc
    x.decir = lambda t: (
        escribir(client, firmar_twilio, correr_trabajos, reloj, t),
        db.expire_all(),
    )
    return x


def test_h13_registro_reservado_por_agente_de_voz_no_toca_la_reserva(c):
    cc = c.ctx.cc
    c.esc.reservar(cc, c.ctx.agente, c.reloj(), minutos=15)
    reservado_hasta = cc.reservado_hasta
    usar_llm([VERIFICAR, sim(), {"texto": "Plan: 3 cuotas de $ 90.000, total $ 270.000."},
              reg("Sí, acepto"), {"texto": "Registrado."}])  # fmt: skip
    c.decir("Quiero pagar 270 mil en 3 cuotas")
    c.decir("Sí, acepto")
    c.db.expire_all()
    assert c.db.scalar(select(PromesaPago)) is not None  # la gestión por chat sí se anota
    tip = c.db.scalar(select(Tipificacion))
    assert tip.resultado == "promesa_pago" and tip.conversacion_id is not None
    cc = c.db.get(CampanaCliente, cc.id)
    assert cc.reservado_por == c.ctx.agente.id and cc.estado == "en_gestion"  # B2: reserva intacta
    assert cc.reservado_hasta == reservado_hasta


def test_constancia_unica_y_despues_de_la_tipificacion(c):
    usar_llm([VERIFICAR, sim(), {"texto": "Plan: 3 cuotas de $ 90.000, total $ 270.000."},
              reg("Sí, acepto"), {"texto": "Registrado."}])  # fmt: skip
    c.decir("Quiero pagar 270 mil en 3 cuotas")
    c.decir("Sí, acepto")
    conv = c.db.scalar(select(Conversacion))
    constancias = [m for m in mensajes_de(c.db, conv.id) if "Constancia" in (m.cuerpo or "")]
    assert len(constancias) == 1 and constancias[0].autor == "sistema"
    tip = c.db.scalar(select(Tipificacion))
    assert constancias[0].creado_en >= tip.creado_en - timedelta(seconds=1)
