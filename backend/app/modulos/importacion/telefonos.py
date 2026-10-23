"""Normalización de teléfonos colombianos a E.164 (ADR-0007). Módulo puro."""

import re
from dataclasses import dataclass
from typing import Literal

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType

CodigoErrorTelefono = Literal[
    "TELEFONO_REQUERIDO",
    "TELEFONO_INVALIDO",
    "TELEFONO_NO_COLOMBIANO",
    "TELEFONO_TIPO_NO_PERMITIDO",
]

_MENSAJES: dict[str, str] = {
    "TELEFONO_REQUERIDO": "El teléfono es obligatorio.",
    "TELEFONO_INVALIDO": "El teléfono no es válido.",
    "TELEFONO_NO_COLOMBIANO": "El teléfono no es un número colombiano.",
    "TELEFONO_TIPO_NO_PERMITIDO": "El tipo de línea del teléfono no está permitido.",
}


@dataclass(frozen=True)
class TelefonoNormalizado:
    numero_e164: str
    tipo_linea: Literal["movil", "fijo"]


class ErrorTelefono(Exception):
    def __init__(self, codigo: CodigoErrorTelefono) -> None:
        super().__init__(codigo)
        self.codigo: CodigoErrorTelefono = codigo

    @property
    def mensaje(self) -> str:
        return _MENSAJES[self.codigo]


def enmascarar(valor: str | None) -> str:
    """Enmascara un valor sensible dejando solo los últimos 4 caracteres: `***4567`."""
    limpio = re.sub(r"\s", "", valor or "")
    return "***" + limpio[-4:] if limpio else "***"


def normalizar_telefono(crudo: str | None) -> TelefonoNormalizado:
    if crudo is None or not crudo.strip():
        raise ErrorTelefono("TELEFONO_REQUERIDO")
    texto = crudo.strip()
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]
    con_mas = texto.startswith("+")
    digitos = re.sub(r"\D", "", texto)
    if not digitos:
        raise ErrorTelefono("TELEFONO_INVALIDO")
    if not con_mas and len(digitos) == 12 and digitos.startswith("57"):
        con_mas = True
    candidato = ("+" if con_mas else "") + digitos
    try:
        numero = phonenumbers.parse(candidato, "CO")
    except NumberParseException as exc:
        raise ErrorTelefono("TELEFONO_INVALIDO") from exc
    if not phonenumbers.is_valid_number(numero):
        raise ErrorTelefono("TELEFONO_INVALIDO")
    if phonenumbers.region_code_for_number(numero) != "CO":
        raise ErrorTelefono("TELEFONO_NO_COLOMBIANO")
    tipo = phonenumbers.number_type(numero)
    if tipo == PhoneNumberType.MOBILE:
        linea: Literal["movil", "fijo"] = "movil"
    elif tipo in (PhoneNumberType.FIXED_LINE, PhoneNumberType.FIXED_LINE_OR_MOBILE):
        linea = "fijo"
    else:
        raise ErrorTelefono("TELEFONO_TIPO_NO_PERMITIDO")
    return TelefonoNormalizado(
        numero_e164=phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.E164),
        tipo_linea=linea,
    )
