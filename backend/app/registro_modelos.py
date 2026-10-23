"""Importa todos los modelos para poblar `Base.metadata` (Alembic, tests, CLI)."""

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.cumplimiento.modelos import Festivo, PoliticaCumplimiento
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.modelos import Importacion, ImportacionError
from app.modulos.usuarios.modelos import Usuario

__all__ = [
    "Auditoria",
    "Campana",
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
