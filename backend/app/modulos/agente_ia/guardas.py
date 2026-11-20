"""Guardas deterministas del agente (fase-2c.md §4.6). Módulo PURO.

Entrada: petición de humano y recorte. Salida: documento, URL, longitud, cifras antes de verificar
y cifras no respaldadas por herramientas. Citas: el cliente debe haber escrito lo que se cita.
"""

import re
import unicodedata
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


def _pide_humano(e: EntradaCliente, frases_humano: frozenset[str], payload_asesor: str) -> bool:
    if e.boton_payload is not None and e.boton_payload == payload_asesor:
        return True
    if e.tipo in ("texto", "boton") and e.texto:
        return opt_out.normalizar(e.texto) in frases_humano
    return False


def entrada(
    entradas: list[EntradaCliente],
    frases_humano: frozenset[str],
    payload_asesor: str,
    max_caracteres: int,
) -> GuardaEntrada:
    """GE2 (petición de humano en CUALQUIER entrante del lote del *debounce*) y GE3 (recorte)."""
    pide = any(_pide_humano(e, frases_humano, payload_asesor) for e in entradas)
    saneadas = [
        replace(e, texto=recortar(e.texto, max_caracteres)) if e.texto is not None else e
        for e in entradas
    ]
    return GuardaEntrada(pide, saneadas)


# ---- Montos y porcentajes ----------------------------------------------------------------------
# El texto se normaliza (NFKC: cifras de ancho completo y espacios duros; sin tildes; espacios
# colapsados) y las cifras se buscan escritas con dígitos (`$ 250.000`, `250k`, `1.5M`, `250 mil`,
# `250000`, `35 porciento`) y en letras (`doscientos cincuenta mil`, `treinta por ciento`, `medio
# millón`). Lo que no se puede interpretar con certeza junto a `por ciento` se trata como cifra
# NO respaldada (bloquear es el lado seguro).
_MIL = r"(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{1,3}(?: \d{3})+|\d+(?:[.,]\d{1,2})?)"
_MULT_M = re.compile(r"(\d+(?:[.,]\d+)?)(?: ?(?:millones|millon)\b|m\b)")
_MULT_K = re.compile(r"(\d+(?:[.,]\d+)?)(?: ?mil\b|k\b| k\b)")
_PCT_NUM = re.compile(r"(\d+(?:[.,]\d+)?) ?(?:%|por ciento)")
_SIMBOLO = re.compile(rf"(?:\$|\bcop\b) ?({_MIL})")
_PESOS = re.compile(rf"({_MIL}) ?(?:pesos|cop)\b")
_PUNTOS = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?)(?![\d.,])")
_SIN_FORMATO = re.compile(r"(?<![\d/.,\-:])(\d{4,})(?![\d/.,\-:])")
_PCT_PALABRAS = re.compile(r"\bpor-?ciento\b|\bpor[ -]ciento\b")

UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}  # fmt: skip
DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90,
}  # fmt: skip
CENTENAS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
    "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500,
    "quinientas": 500, "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
    "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900,
    "novecientas": 900,
}  # fmt: skip
GRANDES = {"mil": 1000, "millon": 1_000_000, "millones": 1_000_000}
PALABRAS_NUMERO = (
    set(UNIDADES) | set(DECENAS) | set(CENTENAS) | set(GRANDES) | {"medio", "media", "y"}
)


def normalizar_texto(texto: str) -> str:
    """NFKC + minúsculas + sin tildes + espacios colapsados (incluye espacios duros)."""
    t = unicodedata.normalize("NFKC", texto).lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    t = _PCT_PALABRAS.sub("por ciento", t)
    return re.sub(r"\s+", " ", t)


def _numero(token: str) -> Decimal:
    """`250.000`, `250,000`, `250 000`, `1.5`, `1,5`, `1.234.567,50`, `250000`."""
    t = token.strip()
    if re.fullmatch(r"\d{1,3}(?:[., ]\d{3})+", t):
        return Decimal(re.sub(r"[., ]", "", t))
    m = re.fullmatch(r"(\d{1,3}(?:[.,]\d{3})+)[.,](\d{1,2})", t)
    if m:
        return Decimal(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2))
    return Decimal(t.replace(",", ".").replace(" ", ""))


def _valor_de_palabras(palabras: list[str]) -> Decimal | None:
    """Valor de una secuencia de numerales en español; None si no es interpretable con certeza."""
    total, actual = 0, 0
    previa = ""
    for i, w in enumerate(palabras):
        if w == "y":
            ant = palabras[i - 1] if i else ""
            sig = palabras[i + 1] if i + 1 < len(palabras) else ""
            if not (ant in DECENAS and sig in UNIDADES and 1 <= UNIDADES[sig] <= 9):
                return None
        elif w in UNIDADES:
            if previa in UNIDADES:
                return None
            actual += UNIDADES[w]
        elif w in DECENAS:
            actual += DECENAS[w]
        elif w in CENTENAS:
            if actual % 1000 >= 100:
                return None
            actual += CENTENAS[w]
        elif w in ("medio", "media"):
            if i + 1 >= len(palabras) or palabras[i + 1] not in ("millon", "millones"):
                return None
            actual = 0
            total += 500_000
            palabras[i + 1] = "_"  # el "millón" ya está contado
        elif w == "_":
            pass
        elif w == "mil":
            total += (actual or 1) * 1000
            actual = 0
        elif w in ("millon", "millones"):
            total += (actual or 1) * 1_000_000
            actual = 0
        else:
            return None
        previa = w
    return Decimal(total + actual)


@dataclass
class Cifras:
    montos: list[Decimal]
    porcentajes: list[Decimal]
    inciertas: bool  # una expresión numérica en letras no se pudo interpretar con certeza


def _tapar(texto: str, patron: re.Pattern[str]) -> tuple[list[re.Match[str]], str]:
    encontradas = list(patron.finditer(texto))
    for m in reversed(encontradas):
        texto = texto[: m.start()] + " " * (m.end() - m.start()) + texto[m.end() :]
    return encontradas, texto


def _palabras_numericas(texto: str, cifras: Cifras) -> None:
    """Interpreta numerales en letras junto a mil/millón/pesos/por ciento."""
    toks = [(m.group(0), m.start()) for m in re.finditer(r"[a-z_]+|\S", texto)]
    i = 0
    while i < len(toks):
        if toks[i][0] not in PALABRAS_NUMERO or toks[i][0] == "y":
            i += 1
            continue
        j = i
        while j < len(toks) and toks[j][0] in PALABRAS_NUMERO:
            j += 1
        corrida = [t for t, _ in toks[i:j]]
        while corrida and corrida[-1] == "y":  # "y" final no pertenece al numeral
            corrida.pop()
            j -= 1
        siguiente = toks[j][0] if j < len(toks) else ""
        siguiente2 = toks[j + 1][0] if j + 1 < len(toks) else ""
        i_previo = toks[i - 1][0] if i else ""
        es_pct = siguiente == "por" and siguiente2 == "ciento"
        grande = any(w in GRANDES for w in corrida)
        otras = [w for w in corrida if w not in GRANDES and w != "y"]
        pesos = siguiente in ("pesos", "cop") or (siguiente == "de" and siguiente2 == "pesos")
        simbolo = i_previo == "$"
        relevante = es_pct or pesos or simbolo or (grande and (otras or corrida != ["mil"]))
        if relevante:
            valor = _valor_de_palabras(list(corrida))
            if valor is None:
                cifras.inciertas = True
            elif es_pct:
                cifras.porcentajes.append(valor)
            else:
                cifras.montos.append(valor)
        i = max(j, i + 1)
    # `por ciento` sin un número (dígitos o letras) delante: no interpretable -> incierto
    for m in re.finditer(r"por ciento", texto):
        antes = texto[: m.start()].split()
        if not antes or not (antes[-1] in PALABRAS_NUMERO or re.search(r"\d", antes[-1])):
            cifras.inciertas = True


def analizar_cifras(texto: str) -> Cifras:
    t = normalizar_texto(texto)
    cifras = Cifras([], [], False)
    ms, t = _tapar(t, _PCT_NUM)
    cifras.porcentajes += [_numero(m.group(1)) for m in ms]
    for patron, factor in ((_MULT_M, 1_000_000), (_MULT_K, 1000)):
        ms, t = _tapar(t, patron)
        for m in ms:
            cifras.montos.append(_numero(m.group(1)) * factor)
            # Las abreviaturas `k` y `M` (`250k`, `1.5M`) nunca se aceptan: el modelo debe
            # escribir el monto como lo devolvió la herramienta (`$ 250.000`, `1,5 millones`).
            if re.search(r"\d(?:k|m)\b| k\b", m.group(0)):
                cifras.inciertas = True
    for patron in (_SIMBOLO, _PESOS, _PUNTOS):
        ms, t = _tapar(t, patron)
        cifras.montos += [_numero(m.group(1)) for m in ms]
    for m in _SIN_FORMATO.finditer(t):
        valor = int(m.group(1))
        if not (len(m.group(1)) == 4 and 1900 <= valor <= 2100):  # los años no son montos
            cifras.montos.append(Decimal(valor))
    _palabras_numericas(t, cifras)
    return cifras


def extraer_montos(texto: str) -> list[Decimal]:
    """Montos en pesos mencionados (dígitos o letras)."""
    return analizar_cifras(texto).montos


def extraer_porcentajes(texto: str) -> list[Decimal]:
    return analizar_cifras(texto).porcentajes


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
    cifras = analizar_cifras(texto)
    montos, porcentajes = cifras.montos, cifras.porcentajes
    if not ctx.identidad_verificada and (montos or porcentajes or cifras.inciertas):
        return FalloGuarda(
            "MONTO_ANTES_DE_VERIFICAR", "menciona cifras antes de verificar la identidad"
        )
    if cifras.inciertas:
        return FalloGuarda(
            "MONTO_NO_RESPALDADO",
            "menciona una cifra que no se pudo comprobar: escribe las cifras con números, "
            "exactamente como las devolvió una herramienta",
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
CodigoCita = Literal[
    "CITA_INVALIDA",
    "CITA_ANTERIOR_A_PROPUESTA",
    "CITA_NO_ENCONTRADA",
    "CITA_NEGADA",
    "CITA_NO_VALIDA",
]
MAX_CITA = 300
FRACCION_MINIMA_CITA = 0.6
NEGACIONES = frozenset(
    {"no", "nunca", "tampoco", "ni", "jamas", "nada", "nadie", "ninguno", "ninguna"}
)
# Palabras sin contenido propio: no cuentan para la fracción del mensaje que cubre la cita.
NO_SIGNIFICATIVAS = frozenset(
    {
        "de", "la", "el", "los", "las", "un", "una", "y", "a", "en", "que", "lo", "me", "mi", "se",
        "es", "al", "del", "por", "para", "con", "gracias", "favor", "porfa", "hola", "buenas",
        "buenos", "dias", "tardes", "noches", "senor", "senora", "doctor", "doctora",
    }
)  # fmt: skip


def _palabras(texto: str) -> list[str]:
    return opt_out.normalizar_sin_cortesia(texto).split()


def _contiene(mensaje: list[str], cita: list[str]) -> bool:
    n = len(cita)
    return n > 0 and any(mensaje[i : i + n] == cita for i in range(len(mensaje) - n + 1))


def tiene_negacion(texto: str) -> bool:
    """¿El mensaje contiene una negación? Ante la duda se rechaza (`no acepto`, `nunca`, `para
    nada`, `ni`...): el modelo debe pedir una confirmación explícita."""
    palabras = _palabras(texto)
    return any(p in NEGACIONES for p in palabras) or _contiene(palabras, ["para", "nada"])


def _cubre(cita: list[str], mensaje: list[str], fraccion: float) -> bool:
    if cita == mensaje:
        return True
    signif = [p for p in mensaje if p not in NO_SIGNIFICATIVAS]
    if not signif:
        return False
    cubiertas = [p for p in signif if p in cita]
    return len(cubiertas) / len(signif) >= fraccion


def localizar_cita(
    cita: str,
    textos_cliente: list[TextoCliente],
    desde: datetime | None,
    *,
    afirmacion: bool = True,
    completo: bool = False,
    fraccion_minima: float = FRACCION_MINIMA_CITA,
) -> TextoCliente | CodigoCita:
    """Mensaje del cliente que respalda la cita, o el código del rechazo.

    - La cita (normalizada, 2..300 caracteres) debe estar en UN mensaje posterior a `desde`.
    - Debe ser el mensaje completo (`completo`) o cubrir al menos `fraccion_minima` de sus
      palabras significativas: una palabra suelta de un mensaje largo no vale.
    - Si es una confirmación (`afirmacion`), el mensaje no puede contener una negación
      (`no acepto`, `nunca`...). Para opt-out la negación es el contenido y no se comprueba."""
    c = _palabras(cita)
    texto_c = " ".join(c)
    if not 2 <= len(texto_c) <= MAX_CITA:
        return "CITA_INVALIDA"
    en_anterior = False
    negada = False
    parcial = False
    for t in textos_cliente:
        m = _palabras(t.texto)
        if not _contiene(m, c):
            continue
        if desde is not None and t.momento <= desde:
            en_anterior = True
            continue
        if afirmacion and tiene_negacion(t.texto):
            negada = True
            continue
        if completo:
            if c == m:
                return t
            parcial = True
            continue
        if _cubre(c, m, fraccion_minima):
            return t
        parcial = True
    if negada:
        return "CITA_NEGADA"
    if parcial:
        return "CITA_NO_VALIDA"
    return "CITA_ANTERIOR_A_PROPUESTA" if en_anterior else "CITA_NO_ENCONTRADA"


def verificar_cita(
    cita: str,
    textos_cliente: list[TextoCliente],
    desde: datetime | None,
    *,
    afirmacion: bool = True,
    completo: bool = False,
) -> CodigoCita | None:
    r = localizar_cita(cita, textos_cliente, desde, afirmacion=afirmacion, completo=completo)
    return r if isinstance(r, str) else None
