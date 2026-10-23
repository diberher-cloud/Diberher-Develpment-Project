"""Normalización pura de campos de importación: cabeceras, documento, montos, enteros, fechas."""

import re
import unicodedata
from datetime import date
from decimal import Decimal

from email_validator import EmailNotValidError, validate_email

TIPOS_DOCUMENTO = ("CC", "CE", "NIT", "PA", "TI", "PPT")
_MAX_MONTO = Decimal("999999999999.99")  # NUMERIC(14,2)


class ErrorValor(Exception):
    """Valor inválido; `codigo` es uno de los códigos de fila de §4.6."""

    def __init__(self, codigo: str, mensaje: str) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def normalizar_cabecera(cabecera: str) -> str:
    """minúsculas, sin tildes, espacios/guiones → `_`, recortada. `Teléfono 1` → `telefono_1`."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", cabecera) if not unicodedata.combining(c)
    )
    minuscula = sin_tildes.strip().lower()
    return re.sub(r"_+", "_", re.sub(r"[\s\-]+", "_", minuscula)).strip("_")


def limpiar_texto(valor: str | None) -> str:
    """Recorta y colapsa espacios."""
    return re.sub(r"\s+", " ", valor or "").strip()


def normalizar_tipo_documento(valor: str | None) -> str:
    tipo = limpiar_texto(valor).upper()
    if tipo not in TIPOS_DOCUMENTO:
        raise ErrorValor("TIPO_DOCUMENTO_INVALIDO", "Tipo de documento inválido.")
    return tipo


def normalizar_documento(tipo: str, valor: str | None) -> str:
    crudo = valor or ""
    if tipo in ("CC", "TI", "NIT"):
        limpio = re.sub(r"[\s.\-]", "", crudo)
        if not re.fullmatch(r"\d{4,15}", limpio):
            raise ErrorValor(
                "DOCUMENTO_INVALIDO", f"Número de documento inválido ({_mask(crudo)})."
            )
        return limpio
    limpio = re.sub(r"\s", "", crudo).upper()
    if not re.fullmatch(r"[A-Z0-9]{3,20}", limpio):
        raise ErrorValor("DOCUMENTO_INVALIDO", f"Número de documento inválido ({_mask(crudo)}).")
    return limpio


def _mask(valor: str) -> str:
    limpio = re.sub(r"\s", "", valor)
    return "***" + limpio[-4:] if limpio else "***"


def parsear_monto(valor: str | None) -> Decimal:
    texto = re.sub(r"[$\s]", "", valor or "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", texto):
        numero = texto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+([.,]\d{1,2})?", texto):
        numero = texto.replace(",", ".")
    else:
        raise ErrorValor("MONTO_INVALIDO", "Monto inválido.")
    monto = Decimal(numero).quantize(Decimal("0.01"))
    if monto > _MAX_MONTO:
        raise ErrorValor("MONTO_INVALIDO", "Monto fuera de rango.")
    return monto


def parsear_entero_no_negativo(valor: str | None) -> int:
    texto = (valor or "").strip()
    if not re.fullmatch(r"\d{1,9}", texto):
        raise ErrorValor("ENTERO_INVALIDO", "Debe ser un entero mayor o igual a 0.")
    return int(texto)


def parsear_fecha(valor: str | None) -> date:
    texto = (valor or "").strip()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto):
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        pass
    raise ErrorValor("FECHA_INVALIDA", "Fecha inválida (use YYYY-MM-DD o DD/MM/YYYY).")


def validar_email(valor: str | None) -> str:
    texto = (valor or "").strip()
    try:
        resultado = validate_email(texto, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ErrorValor("EMAIL_INVALIDO", "Email inválido.") from exc
    correo = resultado.normalized.lower()
    if len(correo) > 254:
        raise ErrorValor("EMAIL_INVALIDO", "Email inválido.")
    return correo
