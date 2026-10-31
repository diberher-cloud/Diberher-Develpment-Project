"""Resultados de herramientas: errores controlados y enmascarado de entradas guardadas."""

import re
from dataclasses import dataclass
from typing import Any


class ErrorHerramienta(Exception):
    """Rechazo de una herramienta (`is_error: true`). Deshace los efectos parciales."""

    def __init__(
        self,
        codigo: str,
        mensaje: str,
        limites: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.mensaje = mensaje
        self.limites = limites
        self.extra = extra or {}

    def como_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"codigo": self.codigo, "mensaje": self.mensaje}
        if self.limites is not None:
            d["limites"] = self.limites
        d.update(self.extra)
        return d


@dataclass
class Resultado:
    datos: dict[str, Any]
    es_error: bool = False
    efecto: str = "ninguno"
    referencia: tuple[str, int] | None = None
    reglas_version: int | None = None

    @property
    def codigo_error(self) -> str | None:
        return self.datos.get("codigo") if self.es_error else None


def enmascarar_documento(valor: str) -> str:
    digitos = re.sub(r"\D", "", valor)
    return "***" + digitos[-4:]


def enmascarar_entrada(nombre: str, entrada: Any) -> dict[str, Any]:
    """`numero_documento` -> `***4050` en lo que se guarda en `acciones_ia`."""
    if not isinstance(entrada, dict):
        return {}
    copia = dict(entrada)
    if isinstance(copia.get("numero_documento"), str):
        copia["numero_documento"] = enmascarar_documento(copia["numero_documento"])
    return copia
