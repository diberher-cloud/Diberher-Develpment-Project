"""T28: el núcleo (bucle, herramientas, guardas) habla solo con el protocolo `CanalIA`: un canal
en memoria, sin WhatsApp ni mensajes, ejecuta un turno completo con herramientas."""

from datetime import timedelta

from ia import escenario_ia, herramienta, usar_llm
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from wa import crear_conv

from app.modulos.agente_ia import bucle
from app.modulos.agente_ia.canal import EntradaCliente, EstadoInteraccion
from app.modulos.agente_ia.canal_chat import CanalChat
from app.modulos.agente_ia.contexto import RefInteraccion
from app.modulos.agente_ia.modelos import AccionIA
from app.modulos.conversaciones.dueno import IA
from app.modulos.whatsapp.ventana import Enviar


class CanalFalso:
    """Canal sin WhatsApp: entradas y salidas en memoria. Reutiliza el bloqueo de la fila de la
    interacción (en 2D será `llamadas`) pero nada más del canal de chat."""

    nombre = "chat"

    def __init__(self, entradas):
        self.entradas, self.enviados, self.derivaciones, self.cierres, self.procesadas = (
            entradas, [], [], [], []
        )  # fmt: skip
        self._chat = CanalChat()

    def bloquear(self, db, ref):
        est = self._chat.bloquear(db, ref)
        return EstadoInteraccion(est.abierta, est.dueno, est.cola_id_activa)

    def entradas_nuevas(self, db, ref):
        return [e for e in self.entradas if e.id not in self.procesadas]

    def marcar_procesadas(self, db, entradas, ahora):
        self.procesadas += [e.id for e in entradas]

    def textos_cliente(self, db, ref, desde):
        return []

    def decidir_respuesta(self, db, ref, ahora):
        return Enviar()

    def enviar(self, db, ref, texto, ahora, autor):
        self.enviados.append((autor, texto))
        return len(self.enviados)

    def hay_humano_disponible(self, db, ctx):
        return True

    def derivar(self, db, ref, motivo, resumen, ahora):
        self.derivaciones.append((motivo, resumen))
        return 1

    def cerrar(self, db, ref, ahora):
        self.cierres.append(ref.clave)

    def aplicar_opt_out(self, db, ref, alcance, ahora):
        self.cierres.append(alcance)


def test_t28_turno_con_canal_falso(session_factory, db, esc, crear_usuario, reloj):
    ctx = escenario_ia(esc, crear_usuario, db)
    conv = crear_conv(db, reloj(), cc=ctx.cc, dueno=IA())
    llm = usar_llm([
        herramienta("verificar_identidad", numero_documento="1020304050"),
        herramienta("derivar_a_humano", motivo="queja", resumen="Quiere reclamar"),
        {"texto": "Un asesor lo atenderá."},
    ])  # fmt: skip
    canal = CanalFalso([EntradaCliente(1, reloj(), "texto", "Mi cédula es 1020304050", None, None)])
    fabrica = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    r = bucle.ejecutar_turno(
        fabrica,
        canal,
        RefInteraccion("conversacion", conv.id),
        llm,
        lambda: reloj() + timedelta(seconds=1),
        "t:1",
    )  # noqa: E501
    assert r.estado == "derivado"
    assert canal.derivaciones == [("queja", "Quiere reclamar")]
    # La despedida solo se envía si la fila de cola sigue pendiente y sin asignar: este canal
    # no cambia el dueño, así que el núcleo no la envía.
    assert [a.herramienta for a in db.scalars(select(AccionIA).order_by(AccionIA.id))] == [
        "verificar_identidad",
        "derivar_a_humano",
    ]
    assert llm.llamadas == 3 and canal.procesadas == [1]
