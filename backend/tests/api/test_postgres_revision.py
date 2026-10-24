# ruff: noqa: F811, B023
"""Carreras de la revisión 2 sobre PostgreSQL real (marcador `postgres`; TEST_DATABASE_URL).

Reutiliza la fixture `pg` (esquema con migraciones reales) y los ayudantes de hilos.
"""

import threading
import uuid

import pytest
from conftest import firma_independiente
from escenario import Escenario, telefono_de
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_postgres_concurrencia import AHORA, _en_hilos, _usuario, pg  # noqa: F401

from app.main import app
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola import servicio as consola
from app.modulos.consola.modelos import HistorialEstadoAgente
from app.modulos.cumplimiento.modelos import IntentoContacto, PoliticaCumplimiento
from app.modulos.telefonia import servicio as tel
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario

pytestmark = pytest.mark.postgres
BASE = "https://pruebas.example.com"


def _saliente(pg, agente_id, cc_id, tel_id, sid):
    with pg() as s:
        return tel.procesar_saliente(
            s,
            call_sid=sid,
            desde=f"client:agente_{agente_id}",
            account_sid=None,
            campana_cliente_id=str(cc_id),
            telefono_id=str(tel_id),
            ahora=AHORA,
            verificar_cuenta=False,
        )


def test_b4_dos_pestanas_del_mismo_agente_solo_una_llamada_pasa(pg):
    for ronda in range(6):
        with pg() as db:
            admin = _usuario(db, "administrador", 100 + ronda)
            ag = _usuario(db, "agente", 200 + ronda)
            esc = Escenario(db, admin.id)
            camp = esc.campana()
            esc.asignar(camp, ag)
            cc = esc.registro(camp)
            esc.estado(ag, "disponible", AHORA)
            esc.reservar(cc, ag, AHORA)
            ids = (ag.id, cc.id, telefono_de(db, cc).id)
        barrera = threading.Barrier(4, timeout=10)

        def intento(sid):
            def _f():
                barrera.wait()
                return _saliente(pg, *ids, sid)

            return _f

        r = _en_hilos([intento(f"CA{ronda}-{i}") for i in range(4)])
        assert not any(isinstance(x, BaseException) for x in r), r
        permitidas = [x for x in r if x.permitida]
        assert len(permitidas) == 1, [(x.permitida, x.motivos) for x in r]
        with pg() as s:
            assert s.scalar(select(func.count()).select_from(IntentoContacto)) == ronda + 1


def test_b4_dos_agentes_sobre_el_mismo_cliente_respetan_la_frecuencia(pg):
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        a1, a2 = _usuario(db, "agente", 1), _usuario(db, "agente", 2)
        esc = Escenario(db, admin.id)
        # El límite diario aplica aun sin contacto directo previo.
        for fila in db.scalars(select(PoliticaCumplimiento)):
            cfg = dict(fila.configuracion)
            cfg["frecuencia"] = {**cfg["frecuencia"], "solo_tras_contacto_directo": False}
            fila.configuracion = cfg
        db.commit()
        c1, c2 = esc.campana(), esc.campana()
        esc.asignar(c1, a1)
        esc.asignar(c2, a2)
        cc1 = esc.registro(c1)
        cc2 = CampanaCliente(campana_id=c2.id, cliente_id=cc1.cliente_id)
        db.add(cc2)
        db.commit()
        for ag, cc in ((a1, cc1), (a2, cc2)):
            esc.estado(ag, "disponible", AHORA)
            esc.reservar(cc, ag, AHORA)
        tel_id = telefono_de(db, cc1).id
        datos = [(a1.id, cc1.id), (a2.id, cc2.id)]
    barrera = threading.Barrier(2, timeout=10)

    def intento(ag, cc, sid):
        def _f():
            barrera.wait()
            return _saliente(pg, ag, cc, tel_id, sid)

        return _f

    r = _en_hilos([intento(a, c, f"CAx{i}") for i, (a, c) in enumerate(datos)])
    assert not any(isinstance(x, BaseException) for x in r), r
    assert sorted(x.permitida for x in r) == [False, True]
    bloqueada = next(x for x in r if not x.permitida)
    assert [m["codigo"] for m in bloqueada.motivos] == ["FRECUENCIA_DIA"]


def _firmado(ruta, params, consulta):
    url = BASE + ruta + "?" + consulta
    return {
        "url": ruta + "?" + consulta,
        "data": params,
        "headers": {"X-Twilio-Signature": firma_independiente(url, params)},
    }


def test_b1_ringing_concurrente_con_dial_terminado_no_resucita_la_llamada(pg):
    for ronda in range(6):
        with pg() as db:
            admin = _usuario(db, "administrador", 300 + ronda)
            ag = _usuario(db, "agente", 400 + ronda)
            esc = Escenario(db, admin.id)
            camp = esc.campana()
            esc.asignar(camp, ag)
            cc = esc.registro(camp)
            esc.estado(ag, "disponible", AHORA)
            esc.reservar(cc, ag, AHORA)
            ids = (ag.id, cc.id, telefono_de(db, cc).id)
        sid = f"CAb1-{uuid.uuid4().hex[:10]}"
        res = _saliente(pg, *ids, sid)
        lid = res.llamada_id
        cons = f"llamada_id={lid}"
        reqs = [
            _firmado(
                "/api/v1/telefonia/twiml/dial-terminado",
                {"CallSid": sid, "DialCallStatus": "busy", "DialCallSid": f"CAc{ronda}"},
                cons,
            ),
            _firmado(
                "/api/v1/telefonia/webhooks/estado",
                {"CallSid": f"CAc{ronda}", "CallStatus": "ringing", "SequenceNumber": "1"},
                cons,
            ),
            _firmado(
                "/api/v1/telefonia/webhooks/estado",
                {"CallSid": f"CAc{ronda}", "CallStatus": "in-progress", "SequenceNumber": "2"},
                cons,
            ),
        ]
        barrera = threading.Barrier(len(reqs), timeout=10)

        def disparar(p):
            def _f():
                with TestClient(app) as c:
                    barrera.wait()
                    return c.post(p["url"], data=p["data"], headers=p["headers"]).status_code

            return _f

        codigos = _en_hilos([disparar(p) for p in reqs])
        assert all(c in (200, 204) for c in codigos), codigos
        with pg() as s:
            ll = s.get(Llamada, lid)
            # Según el orden de llegada: o terminó `ocupado` (llegó D antes que in-progress), o
            # pasó por `en_curso` y D la finalizó. Nunca queda en un estado no terminal.
            assert ll.estado in ("ocupado", "completada", "no_contesta"), ll.estado
            n = s.scalar(
                select(func.count())
                .select_from(HistorialEstadoAgente)
                .where(
                    HistorialEstadoAgente.usuario_id == ids[0],
                    HistorialEstadoAgente.estado == "tipificando",
                )
            )
            assert n == 1


def test_b2_tomar_concurrente_con_la_finalizacion_no_roba_el_registro(pg, monkeypatch):
    """Tras finalizar sin tipificar, otro agente no puede tomar el registro aunque la reserva
    haya vencido, ni siquiera si lo intenta justo en la finalización."""
    with pg() as db:
        admin = _usuario(db, "administrador", 0)
        a1, a2 = _usuario(db, "agente", 1), _usuario(db, "agente", 2)
        esc = Escenario(db, admin.id)
        camp = esc.campana()
        esc.asignar(camp, a1)
        esc.asignar(camp, a2)
        cc = esc.registro(camp)
        esc.estado(a1, "disponible", AHORA)
        esc.reservar(cc, a1, AHORA)
        ids = (a1.id, cc.id, telefono_de(db, cc).id)
        a2_id, cc_id = a2.id, cc.id
    res = _saliente(pg, *ids, "CAb2")
    with pg() as s:
        ll = s.get(Llamada, res.llamada_id)
        tel.finalizar(s, ll, "completed", 5, AHORA, contestada=True)
        s.commit()
    from datetime import timedelta

    tarde = AHORA + timedelta(minutes=45)  # la reserva renovada también venció
    with pg() as s:
        with pytest.raises(Exception) as e:
            consola.tomar(s, s.get(Usuario, a2_id), cc_id, tarde)
        assert getattr(e.value, "codigo", None) == "REGISTRO_RESERVADO"
