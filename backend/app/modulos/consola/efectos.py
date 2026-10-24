"""Efectos PUROS de una tipificación sobre el registro de campaña (§4.6)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

CONTACTO_DIRECTO_FIJO = {
    "no_contesta": False,
    "numero_errado": False,
    "contactado": True,
    "promesa_pago": True,
    "venta": True,
    "rechazo": True,
}


@dataclass(frozen=True)
class EntradaEfectos:
    resultado: str
    ahora: datetime
    intentos: int
    max_intentos: int
    intervalo_reintento_minutos: int
    contacto_directo_pedido: bool | None = None
    volver_a_llamar_en: datetime | None = None
    quedan_telefonos_llamables: bool = True  # tras excluir el de la llamada (numero_errado)
    # Próxima ventana permitida por el horario a partir de un instante (o None).
    proxima_ventana: Callable[[datetime], datetime | None] = lambda t: t


@dataclass(frozen=True)
class EfectoRegistro:
    estado: str
    intentos: int
    proximo_intento_en: datetime | None
    contacto_directo: bool
    excluir_telefono: bool = False
    crear_promesa: bool = False
    crear_venta: bool = False

    @property
    def cierra_registro(self) -> bool:
        return self.estado in ("gestionado", "descartado")


def calcular_efectos(e: EntradaEfectos) -> EfectoRegistro:
    intentos = e.intentos + 1
    r = e.resultado
    if r == "no_contesta":
        if intentos >= e.max_intentos:
            return EfectoRegistro("gestionado", intentos, None, False)
        objetivo = e.ahora + timedelta(minutes=e.intervalo_reintento_minutos)
        return EfectoRegistro("pendiente", intentos, e.proxima_ventana(objetivo) or objetivo, False)
    if r == "numero_errado":
        if (
            intentos >= e.max_intentos
        ):  # mismo estado terminal que no_contesta con intentos agotados
            estado = "gestionado"
        else:
            estado = "pendiente" if e.quedan_telefonos_llamables else "descartado"
        return EfectoRegistro(estado, intentos, None, False, excluir_telefono=True)
    if r == "volver_a_llamar":
        return EfectoRegistro(
            "pendiente", intentos, e.volver_a_llamar_en, bool(e.contacto_directo_pedido)
        )
    if r in ("contactado", "promesa_pago", "venta", "rechazo"):
        return EfectoRegistro(
            "gestionado",
            intentos,
            None,
            True,
            crear_promesa=r == "promesa_pago",
            crear_venta=r == "venta",
        )
    raise ValueError(f"Resultado desconocido: {r}")
