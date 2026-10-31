"""Entradas de las herramientas (Pydantic, `extra="forbid"`; fase-2c.md §4.8). El esquema JSON
enviado al modelo es `strict`, pero los rangos y formatos se validan aquí."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SinEntrada(_Base):
    pass


class VerificarIdentidad(_Base):
    numero_documento: StrictStr


class SimularAcuerdo(_Base):
    monto_total: StrictStr
    numero_cuotas: StrictInt
    fecha_primer_pago: date
    periodicidad: Literal["unica", "semanal", "quincenal", "mensual"]


class RegistrarAcuerdo(SimularAcuerdo):
    confirmacion_cliente: StrictStr


class CotizarVenta(_Base):
    codigo_oferta: StrictStr
    unidades: StrictInt
    descuento_porcentaje: StrictStr


class RegistrarVenta(CotizarVenta):
    confirmacion_cliente: StrictStr


class ProgramarSeguimiento(_Base):
    fecha_hora_local: StrictStr
    motivo: StrictStr

    @field_validator("motivo")
    @classmethod
    def _recortar(cls, v: str) -> str:
        return v[:200]


class RegistrarAutorizacion(_Base):
    cita_cliente: StrictStr


class RegistrarOptOut(_Base):
    alcance: Literal["whatsapp", "llamadas", "todos_los_canales"]
    cita_cliente: StrictStr


class DerivarAHumano(_Base):
    motivo: Literal["solicitud_cliente", "queja", "ia_no_resuelve"]
    resumen: StrictStr

    @field_validator("resumen")
    @classmethod
    def _recortar(cls, v: str) -> str:
        return v[:500]


class CerrarConversacion(_Base):
    resultado: Literal["contactado", "rechazo", "numero_errado", "ninguno"]
    resumen: StrictStr

    @field_validator("resumen")
    @classmethod
    def _recortar(cls, v: str) -> str:
        return v[:500]


MODELOS: dict[str, type[_Base]] = {
    "verificar_identidad": VerificarIdentidad,
    "consultar_obligacion": SinEntrada,
    "simular_acuerdo_pago": SimularAcuerdo,
    "registrar_acuerdo_pago": RegistrarAcuerdo,
    "consultar_ofertas": SinEntrada,
    "cotizar_venta": CotizarVenta,
    "registrar_venta": RegistrarVenta,
    "consultar_historial_gestiones": SinEntrada,
    "programar_seguimiento": ProgramarSeguimiento,
    "registrar_autorizacion_whatsapp": RegistrarAutorizacion,
    "registrar_opt_out": RegistrarOptOut,
    "derivar_a_humano": DerivarAHumano,
    "cerrar_conversacion": CerrarConversacion,
}
