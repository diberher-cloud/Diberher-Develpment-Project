"""B33: la auditoría, los payloads de trabajos y los logs de 2B no llevan datos personales."""

import logging
import re

from escenario import cab
from sqlalchemy import select
from wa import NUMERO, clave, contexto, crear_conv, entrante

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.conversaciones.dueno import Humano
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.trabajos.modelos import Trabajo

API = "/api/v1"
SECRETOS = (
    "SECRETO-ENTRANTE",
    "RESPUESTA-CONFIDENCIAL",
    "EVIDENCIA-PRIVADA",
    "OBS-SECRETA",
    "Nombre Perfil",
)
NUMEROS = re.compile(r"\+?57\s?3\d{9}|\b3\d{9}\b")


def test_flujo_completo_sin_datos_personales_en_auditoria_payloads_y_logs(
    client, firmar_twilio, db, esc, crear_usuario, reloj, correr_trabajos, h_admin, caplog
):
    ctx = contexto(esc, crear_usuario, reloj, db)
    esc.reservar(ctx.cc, ctx.agente, reloj())
    ag = cab(ctx.agente)
    with caplog.at_level(logging.DEBUG):
        client.post(
            f"{API}/autorizaciones",
            json={
                "telefono": "3001234567",
                "finalidad": "cobranza",
                "evidencia": "EVIDENCIA-PRIVADA f-1",
            },
            headers=h_admin,
        )
        client.post(f"{API}/whatsapp/plantillas/sincronizar", headers=h_admin)
        entrante(client, firmar_twilio, texto="SECRETO-ENTRANTE-1", ProfileName="Nombre Perfil")
        correr_trabajos()
        conv = db.scalar(select(Conversacion))
        client.get(f"{API}/conversaciones/{conv.id}?apertura=true", headers=h_admin)
        client.post(f"{API}/conversaciones/{conv.id}/tomar", headers=ag)
        client.post(
            f"{API}/conversaciones/{conv.id}/mensajes",
            json={"texto": "RESPUESTA-CONFIDENCIAL-2", "idempotencia_clave": clave()},
            headers=ag,
        )
        client.get(f"{API}/conversaciones/{conv.id}/ficha", headers=ag)
        client.post(
            f"{API}/conversaciones/{conv.id}/asignar",
            json={"usuario_id": ctx.agente.id},
            headers=h_admin,
        )
        correr_trabajos()
        client.post(f"{API}/conversaciones/{conv.id}/liberar", headers=ag)
        client.post(f"{API}/conversaciones/{conv.id}/tomar", headers=ag)
        client.post(
            f"{API}/conversaciones/{conv.id}/cerrar",
            json={"tipificacion": {"resultado": "contactado", "observacion": "OBS-SECRETA-3"}},
            headers=ag,
        )
        # Plantilla bloqueada y enviada, opt-out por texto, medios y estado.
        entrante(client, firmar_twilio, texto="STOP")
        correr_trabajos()
        crear_conv(db, reloj(), numero="+573115550001", dueno=Humano(ctx.agente.id))
    # Auditoría.
    for fila in db.scalars(select(Auditoria)):
        volcado = str(fila.detalle) + str(fila.entidad_id)
        assert not NUMEROS.search(volcado), (fila.accion, volcado)
        assert not any(s in volcado for s in SECRETOS), (fila.accion, volcado)
    acciones = {a.accion for a in db.scalars(select(Auditoria))}
    assert {
        "autorizacion.crear",
        "whatsapp.plantillas_sincronizar",
        "conversacion.ver",
        "conversacion.tomar",
        "conversacion.dueno",
        "conversacion.cerrar",
        "tipificacion.crear",
        "consola.ficha_ver",
        "whatsapp.opt_out",
        "exclusion.crear",
    } <= acciones
    # Payloads de trabajos: solo ids.
    for t in db.scalars(select(Trabajo)):
        assert all(isinstance(v, int) for v in t.payload.values()), t.payload
        assert not t.ultimo_error or not NUMEROS.search(t.ultimo_error)
    # Logs: ni textos ni números completos.
    assert not NUMEROS.search(caplog.text), "número completo en los logs"
    assert not any(s in caplog.text for s in SECRETOS)
    assert NUMERO not in caplog.text
    # Los mensajes sí conservan su texto en la tabla de mensajes (única fuente).
    assert any("SECRETO-ENTRANTE-1" in (m.cuerpo or "") for m in db.scalars(select(Mensaje)))
