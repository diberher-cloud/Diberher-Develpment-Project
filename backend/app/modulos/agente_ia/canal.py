"""Interfaz de canal del agente (fase-2c.md §4.1). El núcleo (bucle, herramientas, guardas) solo
conoce este protocolo: `CanalChat` lo implementa para WhatsApp; 2D añade `CanalVoz`."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.modulos.agente_ia.contexto import ContextoInteraccion, RefInteraccion
from app.modulos.whatsapp.ventana import Decision


@dataclass(frozen=True)
class EntradaCliente:
    id: int  # mensajes.id (chat) / secuencia de transcripción (voz)
    momento: datetime
    tipo: Literal["texto", "boton", "media", "no_soportado"]
    texto: str | None  # cuerpo o texto del botón; pie de foto en media
    categoria_media: str | None  # imagen | audio | documento | no_soportado
    boton_payload: str | None


@dataclass(frozen=True)
class TextoCliente:
    """Mensaje del cliente contra el que se verifican las citas."""

    id: int
    momento: datetime
    texto: str


@dataclass(frozen=True)
class EstadoInteraccion:
    abierta: bool
    dueno: Literal["ia", "humano", "sin_asignar"]
    cola_id_activa: int | None


class CanalIA(Protocol):
    nombre: Literal["chat", "voz"]

    def bloquear(self, db: Session, ref: RefInteraccion) -> EstadoInteraccion: ...

    def entradas_nuevas(self, db: Session, ref: RefInteraccion) -> list[EntradaCliente]: ...

    def marcar_procesadas(
        self, db: Session, entradas: list[EntradaCliente], ahora: datetime
    ) -> None: ...

    def textos_cliente(
        self, db: Session, ref: RefInteraccion, desde: datetime | None
    ) -> list[TextoCliente]: ...

    def decidir_respuesta(self, db: Session, ref: RefInteraccion, ahora: datetime) -> Decision: ...

    def enviar(
        self,
        db: Session,
        ref: RefInteraccion,
        texto: str,
        ahora: datetime,
        autor: Literal["ia", "sistema"],
    ) -> int: ...

    def hay_humano_disponible(self, db: Session, ctx: ContextoInteraccion) -> bool: ...

    def derivar(
        self, db: Session, ref: RefInteraccion, motivo: str, resumen: str, ahora: datetime
    ) -> int: ...

    def cerrar(self, db: Session, ref: RefInteraccion, ahora: datetime) -> None: ...

    def aplicar_opt_out(
        self, db: Session, ref: RefInteraccion, alcance: str, ahora: datetime
    ) -> None: ...
