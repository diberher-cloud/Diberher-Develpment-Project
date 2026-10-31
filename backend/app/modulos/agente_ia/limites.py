"""Límites de negocio del agente (fase-2c.md §4.9). Módulo PURO (sin BD ni reloj).

`simular_acuerdo` y `cotizar_venta` los usan las herramientas de la IA y la validación de las
promesas registradas por humanos en campañas de cobranza con reglas.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CENTAVOS = Decimal("0.01")
PESO = Decimal("1")
_MONTO_PESOS = re.compile(r"\d{1,12}(\.00?)?", re.ASCII)
_PORCENTAJE = re.compile(r"\d{1,3}(\.\d{1,2})?", re.ASCII)
DIAS_PERIODO = {"semanal": 7, "quincenal": 15}


def dos_decimales(valor: Decimal) -> str:
    return f"{valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP):.2f}"


# ---- Reglas ------------------------------------------------------------------------------------
class TramoCuotas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cuotas: int = Field(ge=1, le=36)
    descuento_max_pct: Decimal = Field(ge=0, le=100, decimal_places=2)


class ReglasCobranza(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_descuento: Literal["saldo_mora", "saldo_total"]
    descuento_max_pct: Decimal = Field(ge=0, le=100, decimal_places=2)
    descuento_max_pct_por_cuotas: list[TramoCuotas] = Field(default_factory=list)
    monto_minimo_promesa: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    monto_minimo_cuota: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    max_cuotas: int = Field(ge=1, le=36)
    plazo_max_dias_primer_pago: int = Field(ge=0, le=90)
    plazo_max_dias_total: int = Field(ge=0, le=365)
    periodicidades: list[Literal["semanal", "quincenal", "mensual"]] = Field(default_factory=list)


class ReglasVenta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_unidades_por_venta: int = Field(default=1, ge=1, le=100)
    requiere_aceptacion_terminos: bool = True


@dataclass
class ErroresReglas(Exception):
    """Errores de validación de reglas con la ruta del campo (`reglas.<campo>`)."""

    detalles: list[tuple[str, str]] = field(default_factory=list)


def _ruta_pydantic(loc: tuple[Any, ...]) -> str:
    return ".".join(str(p) for p in loc)


def validar_reglas_cobranza(datos: Any) -> ReglasCobranza:
    """Valida estructura y coherencia. Lanza `ErroresReglas` con rutas de campo."""
    try:
        r = ReglasCobranza.model_validate(datos)
    except ValidationError as exc:
        raise ErroresReglas(
            [
                (_ruta_pydantic(e["loc"]), str(e["msg"]).removeprefix("Value error, "))
                for e in exc.errors()
            ]
        ) from exc
    errores: list[tuple[str, str]] = []
    if r.plazo_max_dias_total < r.plazo_max_dias_primer_pago:
        errores.append(
            (
                "plazo_max_dias_total",
                "Debe ser mayor o igual que el plazo máximo del primer pago.",
            )
        )
    if r.max_cuotas > 1 and not r.periodicidades:
        errores.append(("periodicidades", "Obligatoria si se permite más de una cuota."))
    anterior = 0
    for i, t in enumerate(r.descuento_max_pct_por_cuotas):
        base = f"descuento_max_pct_por_cuotas.{i}"
        if t.max_cuotas <= anterior:
            errores.append((f"{base}.max_cuotas", "Los tramos deben tener cuotas crecientes."))
        if t.max_cuotas > r.max_cuotas:
            errores.append((f"{base}.max_cuotas", "No puede superar el máximo de cuotas."))
        if t.descuento_max_pct > r.descuento_max_pct:
            errores.append((f"{base}.descuento_max_pct", "No puede superar el descuento general."))
        anterior = max(anterior, t.max_cuotas)
    if errores:
        raise ErroresReglas(errores)
    return r


def validar_reglas_venta(datos: Any) -> ReglasVenta:
    try:
        return ReglasVenta.model_validate(datos)
    except ValidationError as exc:
        raise ErroresReglas(
            [(_ruta_pydantic(e["loc"]), str(e["msg"])) for e in exc.errors()]
        ) from exc


# ---- Datos de entrada --------------------------------------------------------------------------
@dataclass(frozen=True)
class Obligacion:
    saldo_total: Decimal | None
    saldo_mora: Decimal | None

    def base(self, reglas: ReglasCobranza) -> Decimal | None:
        """Base del descuento; si falta la elegida se usa la otra (ADR-0015 §1)."""
        preferida, otra = (
            (self.saldo_mora, self.saldo_total)
            if reglas.base_descuento == "saldo_mora"
            else (self.saldo_total, self.saldo_mora)
        )
        return preferida if preferida is not None else otra


@dataclass(frozen=True)
class Cuota:
    numero: int
    fecha: date
    monto: Decimal


@dataclass(frozen=True)
class Plan:
    monto_total: Decimal
    descuento_porcentaje: Decimal
    numero_cuotas: int
    periodicidad: str
    cuotas: list[Cuota]

    def como_dict(self) -> dict[str, Any]:
        return {
            "valido": True,
            "monto_total": dos_decimales(self.monto_total),
            "descuento_porcentaje": dos_decimales(self.descuento_porcentaje),
            "numero_cuotas": self.numero_cuotas,
            "periodicidad": self.periodicidad,
            "cuotas": [
                {"numero": c.numero, "fecha": c.fecha.isoformat(), "monto": dos_decimales(c.monto)}
                for c in self.cuotas
            ],
        }


@dataclass(frozen=True)
class Rechazo:
    codigo: str
    mensaje: str
    limites: dict[str, Any] | None = None

    def como_dict(self) -> dict[str, Any]:
        r: dict[str, Any] = {"codigo": self.codigo, "mensaje": self.mensaje}
        if self.limites is not None:
            r["limites"] = self.limites
        return r


# ---- Cobranza ----------------------------------------------------------------------------------
def pesos(texto: str) -> Decimal | None:
    """Monto en pesos enteros (`270000`, `270000.0`, `270000.00`); None si no es válido."""
    limpio = texto.strip()
    if not _MONTO_PESOS.fullmatch(limpio):
        return None
    valor = Decimal(limpio)
    return valor if valor > 0 else None


def sumar_meses(base: date, meses: int) -> date:
    indice = base.month - 1 + meses
    anio, mes = base.year + indice // 12, indice % 12 + 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def fechas_de_cuotas(primera: date, n: int, periodicidad: str) -> list[date]:
    if periodicidad == "mensual":
        return [sumar_meses(primera, k) for k in range(n)]
    paso = DIAS_PERIODO.get(periodicidad, 0)
    return [primera + timedelta(days=paso * k) for k in range(n)]


def max_pct_para(reglas: ReglasCobranza, n: int) -> Decimal:
    """Descuento máximo para `n` cuotas: primer tramo con `max_cuotas >= n`; sin tramos, el
    general; si `n` supera el último tramo, el del último tramo."""
    tramos = reglas.descuento_max_pct_por_cuotas
    if not tramos:
        return reglas.descuento_max_pct
    for t in tramos:
        if t.max_cuotas >= n:
            return t.descuento_max_pct
    return tramos[-1].descuento_max_pct


def monto_minimo_para(base: Decimal, pct: Decimal) -> Decimal:
    return (base * (Decimal(100) - pct) / Decimal(100)).quantize(PESO, rounding=ROUND_CEILING)


def monto_minimo_acuerdo(base: Decimal, reglas: ReglasCobranza) -> Decimal:
    return max(reglas.monto_minimo_promesa, monto_minimo_para(base, reglas.descuento_max_pct))


def simular_acuerdo(
    obligacion: Obligacion,
    reglas: ReglasCobranza,
    monto_total: str,
    n: int,
    fecha_primer_pago: date,
    periodicidad: str,
    hoy: date,
) -> Plan | Rechazo:
    """Comprobaciones en el orden de fase-2c.md §4.9 (la primera que falla decide)."""
    monto = pesos(monto_total)
    if monto is None:
        return Rechazo(
            "MONTO_INVALIDO", "El monto debe ser un número entero de pesos mayor que cero."
        )
    if not 1 <= n <= reglas.max_cuotas:
        return Rechazo(
            "CUOTAS_EXCEDEN_LIMITE",
            f"El número de cuotas debe estar entre 1 y {reglas.max_cuotas}.",
            {"max_cuotas": reglas.max_cuotas},
        )
    if (n == 1) != (periodicidad == "unica") or (
        n > 1 and periodicidad not in reglas.periodicidades
    ):
        return Rechazo(
            "PERIODICIDAD_NO_PERMITIDA",
            "La periodicidad no es válida para ese número de cuotas.",
            {"periodicidades": ["unica"] if n == 1 else list(reglas.periodicidades)},
        )
    if fecha_primer_pago < hoy:
        return Rechazo("FECHA_INVALIDA", "La fecha del primer pago no puede ser anterior a hoy.")
    primer_max = hoy + timedelta(days=reglas.plazo_max_dias_primer_pago)
    ultimo_max = hoy + timedelta(days=reglas.plazo_max_dias_total)
    fechas = fechas_de_cuotas(fecha_primer_pago, n, periodicidad)
    if fecha_primer_pago > primer_max or fechas[-1] > ultimo_max:
        return Rechazo(
            "PLAZO_EXCEDE_LIMITE",
            "Las fechas superan el plazo permitido.",
            {
                "fecha_primer_pago_max": primer_max.isoformat(),
                "fecha_ultima_cuota_max": ultimo_max.isoformat(),
            },
        )
    if obligacion.saldo_total is not None and monto > obligacion.saldo_total:
        return Rechazo(
            "MONTO_SUPERA_SALDO",
            "El monto supera el saldo total de la obligación.",
            {"saldo_total": dos_decimales(obligacion.saldo_total)},
        )
    base = obligacion.base(reglas)
    if base is None or base <= 0:
        return Rechazo("OBLIGACION_SIN_SALDO", "La obligación no tiene saldo para negociar.")
    descuento = max(Decimal(0), (base - monto) / base * 100).quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )
    max_pct = max_pct_para(reglas, n)
    if descuento > max_pct or monto < monto_minimo_para(base, max_pct):
        return Rechazo(
            "DESCUENTO_EXCEDE_LIMITE",
            f"Con {n} cuota{'s' if n != 1 else ''} el descuento máximo es "
            f"{dos_decimales(max_pct)} %.",
            {
                "descuento_max_pct": dos_decimales(max_pct),
                "monto_minimo_para_cuotas": dos_decimales(monto_minimo_para(base, max_pct)),
            },
        )
    if monto < reglas.monto_minimo_promesa:
        return Rechazo(
            "MONTO_INFERIOR_MINIMO",
            "El monto es inferior al mínimo permitido para un acuerdo.",
            {"monto_minimo_acuerdo": dos_decimales(reglas.monto_minimo_promesa)},
        )
    cuota = (monto / n).quantize(PESO, rounding=ROUND_FLOOR)
    montos = [cuota] * (n - 1) + [monto - cuota * (n - 1)]
    if any(m < reglas.monto_minimo_cuota for m in montos):
        return Rechazo(
            "CUOTA_INFERIOR_MINIMO",
            "Alguna cuota es inferior al mínimo permitido.",
            {"monto_minimo_cuota": dos_decimales(reglas.monto_minimo_cuota)},
        )
    return Plan(
        monto,
        descuento,
        n,
        periodicidad,
        [Cuota(i + 1, f, m) for i, (f, m) in enumerate(zip(fechas, montos, strict=True))],
    )


def condiciones_negociacion(
    obligacion: Obligacion, reglas: ReglasCobranza, hoy: date
) -> dict[str, Any] | None:
    """Bloque `condiciones` de `consultar_obligacion` (None si no hay base)."""
    base = obligacion.base(reglas)
    if base is None:
        return None
    return {
        "base_descuento": reglas.base_descuento,
        "base": dos_decimales(base),
        "descuento_max_pct": dos_decimales(reglas.descuento_max_pct),
        "descuento_max_pct_por_cuotas": [
            {"max_cuotas": t.max_cuotas, "descuento_max_pct": dos_decimales(t.descuento_max_pct)}
            for t in reglas.descuento_max_pct_por_cuotas
        ],
        "monto_minimo_acuerdo": dos_decimales(monto_minimo_acuerdo(base, reglas)),
        "monto_minimo_cuota": dos_decimales(reglas.monto_minimo_cuota),
        "max_cuotas": reglas.max_cuotas,
        "periodicidades": list(reglas.periodicidades),
        "fecha_primer_pago_max": (
            hoy + timedelta(days=reglas.plazo_max_dias_primer_pago)
        ).isoformat(),
        "fecha_ultima_cuota_max": (hoy + timedelta(days=reglas.plazo_max_dias_total)).isoformat(),
    }


def validar_promesa_humana(
    obligacion: Obligacion, reglas: ReglasCobranza, monto: Decimal
) -> str | None:
    """Pasos 4-6 con una cuota y `unica` (ADR-0015 §1): mensaje de error o None."""
    if obligacion.saldo_total is not None and monto > obligacion.saldo_total:
        return "No puede superar el saldo total."
    base = obligacion.base(reglas)
    if base is None or base <= 0:
        return None
    descuento = max(Decimal(0), (base - monto) / base * 100).quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )
    max_pct = max_pct_para(reglas, 1)
    if descuento > max_pct or monto < monto_minimo_para(base, max_pct):
        return (
            f"Con 1 cuota el monto mínimo es {formatear_pesos(monto_minimo_para(base, max_pct))}."
        )
    if monto < reglas.monto_minimo_promesa:
        return f"El monto mínimo es {formatear_pesos(reglas.monto_minimo_promesa)}."
    return None


def formatear_pesos(valor: Decimal) -> str:
    """`$ 240.000` (sin decimales cuando son 00)."""
    from app.modulos.consola.guion import formatear_monto

    return formatear_monto(valor.quantize(CENTAVOS))


# ---- Venta -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class OfertaDatos:
    codigo: str
    nombre: str
    descripcion: str | None
    precio: Decimal
    descuento_max_pct: Decimal
    max_unidades: int
    condiciones: str | None
    activa: bool = True


@dataclass(frozen=True)
class Cotizacion:
    oferta: OfertaDatos
    unidades: int
    descuento_porcentaje: Decimal
    valor_total: Decimal

    def como_dict(self) -> dict[str, Any]:
        return {
            "valido": True,
            "codigo_oferta": self.oferta.codigo,
            "nombre": self.oferta.nombre,
            "unidades": self.unidades,
            "precio_unitario": dos_decimales(self.oferta.precio),
            "descuento_porcentaje": dos_decimales(self.descuento_porcentaje),
            "valor_total": dos_decimales(self.valor_total),
            "condiciones": self.oferta.condiciones,
        }


def parsear_porcentaje(texto: str) -> Decimal | None:
    limpio = texto.strip()
    if not _PORCENTAJE.fullmatch(limpio):
        return None
    valor = Decimal(limpio)
    return valor if 0 <= valor <= 100 else None


def cotizar_venta(
    oferta: OfertaDatos | None, reglas: ReglasVenta, unidades: int, descuento: str
) -> Cotizacion | Rechazo:
    if oferta is None or not oferta.activa:
        return Rechazo("OFERTA_NO_DISPONIBLE", "La oferta no existe o no está disponible.")
    maximo = min(oferta.max_unidades, reglas.max_unidades_por_venta)
    if not 1 <= unidades <= maximo:
        return Rechazo(
            "UNIDADES_EXCEDEN_LIMITE",
            f"Se permiten entre 1 y {maximo} unidades por venta.",
            {"max_unidades": maximo},
        )
    pct = parsear_porcentaje(descuento)
    if pct is None or pct > oferta.descuento_max_pct:
        return Rechazo(
            "DESCUENTO_EXCEDE_LIMITE",
            f"El descuento máximo de esta oferta es {dos_decimales(oferta.descuento_max_pct)} %.",
            {"descuento_max_pct": dos_decimales(oferta.descuento_max_pct)},
        )
    valor = (oferta.precio * unidades * (Decimal(100) - pct) / Decimal(100)).quantize(
        PESO, rounding=ROUND_HALF_UP
    )
    return Cotizacion(oferta, unidades, pct.quantize(CENTAVOS), valor)
