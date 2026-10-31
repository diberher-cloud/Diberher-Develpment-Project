"""Importa todos los modelos para poblar `Base.metadata` (Alembic, tests, CLI)."""

from app.modulos.agente_ia.modelos import (
    AccionIA,
    BloqueoTurnoIA,
    ConfiguracionGlobal,
    ConfiguracionIACampana,
    ErrorIA,
    EvaluacionIA,
    HistorialIA,
    InstruccionSupervisor,
    OfertaCampana,
    PromesaCuota,
    UsoIA,
)
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola.modelos import (
    EstadoAgente,
    HistorialEstadoAgente,
    PromesaPago,
    Tipificacion,
    Venta,
)
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, EventoMensaje, Mensaje
from app.modulos.cumplimiento.modelos import Festivo, IntentoContacto, PoliticaCumplimiento
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.modelos import Importacion, ImportacionError
from app.modulos.telefonia.modelos import EventoLlamada, Grabacion, Llamada
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp.modelos import AutorizacionCanal, PlantillaWhatsApp
from app.tiempo_real.modelos import TicketWS
from app.trabajos.modelos import LatidoWorker, Trabajo

__all__ = [
    "AccionIA",
    "BloqueoTurnoIA",
    "ConfiguracionGlobal",
    "ConfiguracionIACampana",
    "ErrorIA",
    "EvaluacionIA",
    "HistorialIA",
    "InstruccionSupervisor",
    "OfertaCampana",
    "PromesaCuota",
    "UsoIA",
    "AutorizacionCanal",
    "Auditoria",
    "ColaAtencion",
    "Conversacion",
    "EventoMensaje",
    "LatidoWorker",
    "Mensaje",
    "PlantillaWhatsApp",
    "Trabajo",
    "Campana",
    "CampanaAgente",
    "EstadoAgente",
    "EventoLlamada",
    "Grabacion",
    "HistorialEstadoAgente",
    "IntentoContacto",
    "Llamada",
    "PromesaPago",
    "Tipificacion",
    "TicketWS",
    "Venta",
    "CampanaCliente",
    "Cliente",
    "Telefono",
    "Festivo",
    "PoliticaCumplimiento",
    "Exclusion",
    "Importacion",
    "ImportacionError",
    "Usuario",
]
