"""`CanalChat`: implementación de `CanalIA` para conversaciones de WhatsApp (fase-2c.md §4.1)."""

from datetime import datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.agente_ia.canal import (
    EntradaCliente,
    EstadoInteraccion,
    TextoCliente,
)
from app.modulos.agente_ia.contexto import ContextoInteraccion, RefInteraccion
from app.modulos.conversaciones import atencion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import SinAsignar, nombre
from app.modulos.conversaciones.dueno import de_conversacion as dueno_de
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.whatsapp import cumplimiento as cumplimiento_wa
from app.modulos.whatsapp import servicio_autorizaciones, servicio_envio
from app.modulos.whatsapp.ventana import (
    Decision,
    Enviar,
    Rechazar,
    decidir_respuesta,
    ventana_abierta,
)


def _conv(db: Session, ref: RefInteraccion) -> Conversacion:
    return conversaciones.cargar(db, ref.id)


class CanalChat:
    nombre: Literal["chat", "voz"] = "chat"

    def bloquear(self, db: Session, ref: RefInteraccion) -> EstadoInteraccion:
        conv = conversaciones.bloquear(db, ref.id)
        fila = atencion.fila_activa(db, conv.id)
        return EstadoInteraccion(
            abierta=conv.estado == "abierta",
            dueno=nombre(dueno_de(conv)),
            cola_id_activa=fila.id if fila is not None else None,
        )

    def entradas_nuevas(self, db: Session, ref: RefInteraccion) -> list[EntradaCliente]:
        """Entrantes procesados por 2B y aún no incorporados al historial. Máximo
        `IA_MAX_MENSAJES_TURNO`: si hay más, se toman los más recientes y a la primera entrada se
        le anota cuántos anteriores se omiten."""
        maximo = get_settings().ia_max_mensajes_turno
        filas = list(
            db.scalars(
                select(Mensaje)
                .where(
                    Mensaje.conversacion_id == ref.id,
                    Mensaje.direccion == "entrante",
                    Mensaje.procesado_en.is_not(None),
                    Mensaje.procesado_ia_en.is_(None),
                )
                .order_by(Mensaje.id)
            )
        )
        omitidas = max(len(filas) - maximo, 0)
        entradas = [self._entrada(m) for m in filas[omitidas:]]
        if entradas and omitidas:
            self.omitidas[ref.clave] = omitidas
        else:
            self.omitidas.pop(ref.clave, None)
        return entradas

    def __init__(self) -> None:
        self.omitidas: dict[str, int] = {}

    @staticmethod
    def _entrada(m: Mensaje) -> EntradaCliente:
        categoria = None
        if m.tipo == "media":
            categoria = (m.media[0]["categoria"] if m.media else None) or "no_soportado"
        tipo = m.tipo if m.tipo in ("texto", "boton", "media") else "no_soportado"
        return EntradaCliente(
            id=m.id,
            momento=m.creado_en,
            tipo=tipo,  # type: ignore[arg-type]
            texto=m.cuerpo,
            categoria_media=categoria,
            boton_payload=m.boton_payload,
        )

    def marcar_procesadas(
        self, db: Session, entradas: list[EntradaCliente], ahora: datetime
    ) -> None:
        """Marca las entradas y los entrantes anteriores omitidos de la misma conversación."""
        if not entradas:
            return
        primero = db.get(Mensaje, min(e.id for e in entradas))
        assert primero is not None
        db.execute(
            update(Mensaje)
            .where(
                Mensaje.conversacion_id == primero.conversacion_id,
                Mensaje.direccion == "entrante",
                Mensaje.procesado_en.is_not(None),
                Mensaje.procesado_ia_en.is_(None),
                Mensaje.id <= max(e.id for e in entradas),
            )
            .values(procesado_ia_en=ahora)
            .execution_options(synchronize_session=False)
        )

    def textos_cliente(
        self, db: Session, ref: RefInteraccion, desde: datetime | None
    ) -> list[TextoCliente]:
        consulta = select(Mensaje).where(
            Mensaje.conversacion_id == ref.id,
            Mensaje.direccion == "entrante",
            Mensaje.tipo.in_(("texto", "boton")),
            Mensaje.cuerpo.is_not(None),
        )
        if desde is not None:
            consulta = consulta.where(Mensaje.creado_en > desde)
        return [
            TextoCliente(m.id, m.creado_en, m.cuerpo or "")
            for m in db.scalars(consulta.order_by(Mensaje.id))
        ]

    def decidir_respuesta(self, db: Session, ref: RefInteraccion, ahora: datetime) -> Decision:
        conv = _conv(db, ref)
        margen = conversaciones.margen_ventana()
        if not ventana_abierta(conv, ahora, margen) or conv.ventana_expira_en is None:
            return Rechazar("VENTANA_CERRADA", None)
        politicas = cumplimiento_wa.politicas_aplicables(db, conv.campana_id)
        decision = decidir_respuesta(
            ahora,
            politicas,
            servicio_envio._festivos(db, ahora, politicas),
            conv.ventana_expira_en,
            margen,
        )
        return decision if not isinstance(decision, Enviar) else Enviar()

    def enviar(
        self,
        db: Session,
        ref: RefInteraccion,
        texto: str,
        ahora: datetime,
        autor: Literal["ia", "sistema"],
    ) -> int:
        conv = _conv(db, ref)
        return servicio_envio.crear_automatico(db, conv, texto, ahora, autor=autor).id

    def hay_humano_disponible(self, db: Session, ctx: ContextoInteraccion) -> bool:
        return cumplimiento_wa.hay_agente_disponible(db, ctx.campana_id)

    def derivar(
        self, db: Session, ref: RefInteraccion, motivo: str, resumen: str, ahora: datetime
    ) -> int:
        conv = _conv(db, ref)
        conversaciones.cambiar_dueno(db, conv, SinAsignar(), motivo, None, ahora, resumen=resumen)
        fila = atencion.fila_activa(db, conv.id)
        assert fila is not None
        return fila.id

    def cerrar(self, db: Session, ref: RefInteraccion, ahora: datetime) -> None:
        conversaciones.cerrar(db, _conv(db, ref), "sistema", None, ahora, cancelar=False)

    def aplicar_opt_out(
        self, db: Session, ref: RefInteraccion, alcance: str, ahora: datetime
    ) -> None:
        conv = _conv(db, ref)
        if alcance == "llamadas":
            servicio_autorizaciones.aplicar_opt_out_voz(db, conv, ahora, origen="agente_ia")
        else:
            servicio_autorizaciones.aplicar_opt_out(
                db, conv, alcance, origen="ia", usuario_id=None, ahora=ahora
            )
