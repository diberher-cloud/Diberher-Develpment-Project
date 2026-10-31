"""Guardas deterministas del agente (fase-2c.md §4.6). Módulo PURO.

Entrada: petición de humano y recorte. Salida: documento, URL, longitud, cifras antes de verificar
y cifras no respaldadas por herramientas. Citas: el cliente debe haber escrito lo que se cita.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.modulos.agente_ia.canal import EntradaCliente, TextoCliente
from app.modulos.whatsapp import opt_out

SUFIJO_TRUNCADO = " [truncado]"

# ---- Entrada -----------------------------------------------------------------------------------
FRASES_HUMANO_DEFECTO = (
    "asesor",
    "un asesor",
    "hablar con un asesor",
    "quiero hablar con un asesor",
    "necesito un asesor",
    "humano",
    "una persona",
    "hablar con una persona",
    "quiero hablar con una persona",
    "agente",
    "hablar con un agente",
    "operador",
)


def cargar_frases_humano(crudo: str) -> frozenset[str]:
    """Frases separadas por `|` (normalizadas); vacío = lista por defecto."""
    return opt_out.cargar_frases(crudo, FRASES_HUMANO_DEFECTO)


@dataclass(frozen=True)
class GuardaEntrada:
    pide_humano: bool
    entradas: list[EntradaCliente]
    omitidas: int = 0


def recortar(texto: str, maximo: int) -> str:
    return texto if len(texto) <= maximo else texto[:maximo] + SUFIJO_TRUNCADO


def entrada(
    entradas: list[EntradaCliente],
    frases_humano: frozenset[str],
    payload_asesor: str,
    max_caracteres: int,
) -> GuardaEntrada:
    """GE2 (petición de humano en el último entrante) y GE3 (recorte)."""
    pide = False
    if entradas:
        ultima = entradas[-1]
        if ultima.boton_payload is not None and ultima.boton_payload == payload_asesor:
            pide = True
        elif ultima.tipo in ("texto", "boton") and ultima.texto:
            pide = opt_out.normalizar(ultima.texto) in frases_humano
    saneadas = [
        replace(e, texto=recortar(e.texto, max_caracteres)) if e.texto is not None else e
        for e in entradas
    ]
    return GuardaEntrada(pide, saneadas)


# ---- Montos y porcentajes ----------------------------------------------------------------------
_NUM = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?"
_M1 = re.compile(rf"(?:\$|cop)\s?{_NUM}")
_M2 = re.compile(rf"{_NUM}\s?(?:pesos|cop)\b")
_M3 = re.compile(r"(\d+(?:[.,]\d+)?)\s?(?:millones|millón|millon)\b")
_M4 = re.compile(r"(\d+)\s?mil\b")
_M5 = re.compile(r"\b(\d{1,3}(?:\.\d{3})+)(?:,(\d{1,2}))?\b")
_P1 = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s?(?:%|por ciento)")


def _entero(texto: str, decimales: str | None) -> Decimal:
    valor = Decimal(texto.replace(".", ""))
    if decimales:
        valor += Decimal(decimales) / Decimal(10 ** len(decimales))
    return valor


def _consumir(texto: str, patron: re.Pattern[str]) -> tuple[list[re.Match[str]], str]:
    """Coincidencias de `patron` y el texto con sus tramos tapados (no se cuentan dos veces)."""
    encontradas = list(patron.finditer(texto))
    for m in reversed(encontradas):
        texto = texto[: m.start()] + " " * (m.end() - m.start()) + texto[m.end() :]
    return encontradas, texto


def extraer_montos(texto: str) -> list[Decimal]:
    """Montos en pesos mencionados (`$ 1.500.000`, `300 mil pesos`, `1,5 millones`...). No
    detecta cifras en palabras ni números sin símbolo ni separador de miles."""
    t = texto.lower()
    montos: list[Decimal] = []
    # Primero las formas con multiplicador, para que `$ 300 mil` no se lea como `$ 300`.
    ms, t = _consumir(t, _M3)
    montos += [Decimal(m.group(1).replace(",", ".")) * 1_000_000 for m in ms]
    ms, t = _consumir(t, _M4)
    montos += [Decimal(m.group(1)) * 1000 for m in ms]
    for patron in (_M1, _M2, _M5):
        ms, t = _consumir(t, patron)
        montos += [_entero(m.group(1), m.group(2)) for m in ms]
    return montos


def extraer_porcentajes(texto: str) -> list[Decimal]:
    return [Decimal(m.group(1).replace(",", ".")) for m in _P1.finditer(texto.lower())]


# ---- Valores respaldados -----------------------------------------------------------------------
CLAVES_MONETARIAS = frozenset(
    {
        "saldo_total",
        "saldo_mora",
        "base",
        "monto",
        "monto_total",
        "monto_minimo_acuerdo",
        "monto_minimo_cuota",
        "monto_minimo_para_cuotas",
        "valor_total",
        "precio",
        "precio_unitario",
    }
)
CLAVES_PORCENTAJE = frozenset({"descuento_max_pct", "descuento_porcentaje"})


def _decimal(valor: Any) -> Decimal | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int | float | str):
        try:
            return Decimal(str(valor))
        except InvalidOperation:
            return None
    return None


def _recoger(
    valor: Any, montos: set[Decimal], porcentajes: set[Decimal], todo_numerico: bool
) -> None:
    if isinstance(valor, dict):
        for clave, v in valor.items():
            if isinstance(v, dict | list):
                _recoger(v, montos, porcentajes, todo_numerico)
                continue
            d = _decimal(v)
            if d is None:
                continue
            if clave in CLAVES_PORCENTAJE or (todo_numerico and "pct" in clave):
                porcentajes.add(d)
            elif clave in CLAVES_MONETARIAS or todo_numerico:
                montos.add(d)
    elif isinstance(valor, list):
        for v in valor:
            _recoger(v, montos, porcentajes, todo_numerico)


def valores_respaldados(
    resultados: Iterable[tuple[Any, bool]],
) -> tuple[set[Decimal], set[Decimal]]:
    """(montos, porcentajes) que el modelo puede mencionar: los de los `tool_result` correctos
    (claves monetarias, recursivo) y los `limites` de los erróneos."""
    montos: set[Decimal] = set()
    porcentajes: set[Decimal] = {Decimal(100)}
    for resultado, es_error in resultados:
        if not isinstance(resultado, dict):
            continue
        if es_error:
            _recoger(resultado.get("limites"), montos, porcentajes, True)
        else:
            _recoger(resultado, montos, porcentajes, False)
    return montos, porcentajes


# ---- Salida ------------------------------------------------------------------------------------
CodigoFallo = Literal[
    "DOCUMENTO_EN_SALIDA",
    "URL_NO_PERMITIDA",
    "LONGITUD_EXCEDIDA",
    "MONTO_ANTES_DE_VERIFICAR",
    "MONTO_NO_RESPALDADO",
]


@dataclass(frozen=True)
class FalloGuarda:
    codigo: CodigoFallo
    motivo: str  # para el mensaje de corrección al modelo


@dataclass(frozen=True)
class ContextoGuardas:
    numero_documento: str | None
    identidad_verificada: bool
    montos_respaldados: frozenset[Decimal]
    porcentajes_respaldados: frozenset[Decimal]
    dominios_permitidos: frozenset[str]
    max_caracteres: int


_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DOMINIO = re.compile(
    r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|co|net|org|io|link|ly|app)\b", re.IGNORECASE
)
_HOST = re.compile(r"^(?:https?://)?([^/?#:\s]+)", re.IGNORECASE)


def _host_permitido(coincidencia: str, permitidos: frozenset[str]) -> bool:
    m = _HOST.match(coincidencia.strip(".,;:!?)\"'"))
    host = m.group(1).lower().rstrip(".") if m else ""
    return any(host == d or host.endswith("." + d) for d in permitidos)


def hay_url_no_permitida(texto: str, permitidos: frozenset[str]) -> bool:
    return any(
        not _host_permitido(m.group(0), permitidos)
        for patron in (_URL, _DOMINIO)
        for m in patron.finditer(texto)
    )


def salida(texto: str, ctx: ContextoGuardas) -> FalloGuarda | None:
    """GS1-GS5 en orden; la primera que falla decide."""
    doc = re.sub(r"\D", "", ctx.numero_documento or "")
    if len(doc) >= 5 and doc in re.sub(r"\D", "", texto):
        return FalloGuarda("DOCUMENTO_EN_SALIDA", "incluye el número de documento del cliente")
    if hay_url_no_permitida(texto, ctx.dominios_permitidos):
        return FalloGuarda("URL_NO_PERMITIDA", "incluye un enlace no permitido")
    if len(texto) > ctx.max_caracteres:
        return FalloGuarda("LONGITUD_EXCEDIDA", f"supera {ctx.max_caracteres} caracteres")
    montos = extraer_montos(texto)
    porcentajes = extraer_porcentajes(texto)
    if not ctx.identidad_verificada and (montos or porcentajes):
        return FalloGuarda(
            "MONTO_ANTES_DE_VERIFICAR", "menciona cifras antes de verificar la identidad"
        )
    for m in montos:
        if not any(abs(m - r) < 1 for r in ctx.montos_respaldados):
            return FalloGuarda(
                "MONTO_NO_RESPALDADO",
                f"menciona {formatear_cifra(m)}, que no proviene de ninguna herramienta",
            )
    for p in porcentajes:
        if not any(abs(p - r) < Decimal("0.01") for r in ctx.porcentajes_respaldados):
            return FalloGuarda(
                "MONTO_NO_RESPALDADO",
                f"menciona {p} %, que no proviene de ninguna herramienta",
            )
    return None


def formatear_cifra(monto: Decimal) -> str:
    entero = f"{int(monto):,}".replace(",", ".")
    return f"$ {entero}"


# ---- Citas -------------------------------------------------------------------------------------
CodigoCita = Literal["CITA_INVALIDA", "CITA_ANTERIOR_A_PROPUESTA", "CITA_NO_ENCONTRADA"]
MAX_CITA = 300


def verificar_cita(
    cita: str, textos_cliente: list[TextoCliente], desde: datetime | None
) -> CodigoCita | None:
    """Válida si la cita normalizada (2..300 caracteres) está en el texto normalizado de UN
    mensaje del cliente posterior a `desde` (coincidencia por palabras completas)."""
    c = opt_out.normalizar_sin_cortesia(cita)
    if not 2 <= len(c) <= MAX_CITA:
        return "CITA_INVALIDA"
    aguja = f" {c} "
    en_anterior = False
    for t in textos_cliente:
        if aguja in f" {opt_out.normalizar_sin_cortesia(t.texto)} ":
            if desde is None or t.momento > desde:
                return None
            en_anterior = True
    return "CITA_ANTERIOR_A_PROPUESTA" if en_anterior else "CITA_NO_ENCONTRADA"
