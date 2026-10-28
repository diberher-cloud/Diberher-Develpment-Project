"""Resolución determinista del contexto de una conversación nueva (fase-2b.md §4.5 paso 2).

Consultas acotadas, sin IA: dado el número del cliente decide a qué registro de campaña pertenece
la conversación (o a ninguno).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.exclusiones.modelos import Exclusion


@dataclass(frozen=True)
class Candidato:
    campana_cliente: CampanaCliente
    campana: Campana
    cliente: Cliente
    telefono: Telefono


@dataclass(frozen=True)
class Resolucion:
    candidato: Candidato | None
    candidatos: int


def candidatos(db: Session, numero_e164: str) -> list[Candidato]:
    """Registros de campañas `activa` con WhatsApp cuyo cliente tiene un teléfono con el número,
    salvo que el número esté marcado como errado."""
    errado = db.scalar(
        select(Exclusion.id)
        .where(Exclusion.numero_e164 == numero_e164, Exclusion.motivo == "numero_errado")
        .limit(1)
    )
    if errado is not None:
        return []
    filas = db.execute(
        select(CampanaCliente, Campana, Cliente, Telefono)
        .join(Telefono, Telefono.cliente_id == CampanaCliente.cliente_id)
        .join(Cliente, Cliente.id == CampanaCliente.cliente_id)
        .join(Campana, Campana.id == CampanaCliente.campana_id)
        .where(
            Telefono.numero_e164 == numero_e164,
            Campana.estado == "activa",
            Campana.whatsapp_habilitado.is_(True),
        )
        .order_by(CampanaCliente.id)
    ).all()
    return [Candidato(cc, camp, cli, tel) for cc, camp, cli, tel in filas]


def resolver(db: Session, numero_e164: str, ahora: datetime, dias_plantilla: int) -> Resolucion:
    lista = candidatos(db, numero_e164)
    if not lista:
        return Resolucion(None, 0)
    por_registro = {c.campana_cliente.id: c for c in lista}
    # 2. Plantilla reciente (no fallida) a ese número desde alguno de los registros candidatos.
    desde = ahora - timedelta(days=dias_plantilla)
    reciente = db.scalar(
        select(Conversacion.campana_cliente_id)
        .join(Mensaje, Mensaje.conversacion_id == Conversacion.id)
        .where(
            Mensaje.tipo == "plantilla",
            Mensaje.direccion == "saliente",
            Mensaje.estado.not_in(("fallido", "cancelado")),
            Mensaje.numero_cliente_e164 == numero_e164,
            Mensaje.creado_en >= desde,
            Conversacion.campana_cliente_id.in_(por_registro),
        )
        .order_by(Mensaje.id.desc())
        .limit(1)
    )
    if reciente is not None:
        return Resolucion(por_registro[reciente], len(lista))
    # 3. Un único candidato.
    if len(lista) == 1:
        return Resolucion(lista[0], 1)
    # 4. Cero o varios: sin registro.
    return Resolucion(None, len(lista))
