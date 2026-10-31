"""Catálogo de herramientas del agente (fase-2c.md §4.7). Módulo PURO.

Todas son `strict` (`additionalProperties: false`, `required` completo, solo `type`, `enum`,
`format: date` y `description`): los rangos y formatos (`minimum`, `pattern`...) no se admiten con
`strict` y los valida el servidor. Los montos y porcentajes son `string` decimales con punto.
Ninguna propiedad identifica al cliente, la campaña ni la conversación: lo fija el servidor."""

import hashlib
import json
from typing import Any

from app.modulos.agente_ia.prompts import cargar_sistema

SIN_ENTRADA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


def _esquema(propiedades: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": propiedades,
        "required": list(propiedades),
        "additionalProperties": False,
    }


def _texto(descripcion: str) -> dict[str, Any]:
    return {"type": "string", "description": descripcion}


_PERIODICIDAD = {"type": "string", "enum": ["unica", "semanal", "quincenal", "mensual"]}

_DEFINICIONES: list[dict[str, Any]] = [
    {
        "name": "cerrar_conversacion",
        "description": (
            "Termina la conversación cuando el cliente se despide o ya no hay nada más que "
            "hacer. Escribe después una despedida breve. resultado: 'contactado' (habló el "
            "titular verificado sin acuerdo ni negativa), 'rechazo' (el titular verificado no "
            "acepta), 'numero_errado' (quien escribe no es el titular y el número no le "
            "pertenece), 'ninguno' (ya se registró una gestión o no hay nada que registrar)."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "resultado": {
                    "type": "string",
                    "enum": ["contactado", "rechazo", "numero_errado", "ninguno"],
                },
                "resumen": _texto(
                    "Resumen de la conversación para el historial (máximo 500 caracteres), "
                    "sin documento ni teléfono."
                ),
            }
        ),
    },
    {
        "name": "consultar_historial_gestiones",
        "description": (
            "Devuelve las últimas gestiones de este cliente en esta campaña (fecha, canal, "
            "resultado y acuerdo vigente). Requiere identidad verificada."
        ),
        "strict": True,
        "input_schema": SIN_ENTRADA,
    },
    {
        "name": "consultar_obligacion",
        "description": (
            "Devuelve la obligación del titular (saldos, mora, vencimiento, número "
            "enmascarado), si tiene un acuerdo vigente y las condiciones de negociación "
            "permitidas (descuentos, cuotas, plazos y montos mínimos). Requiere identidad "
            "verificada."
        ),
        "strict": True,
        "input_schema": SIN_ENTRADA,
    },
    {
        "name": "consultar_ofertas",
        "description": (
            "Devuelve las ofertas activas de la campaña con precio, descuento máximo, "
            "unidades máximas y condiciones. Requiere identidad verificada."
        ),
        "strict": True,
        "input_schema": SIN_ENTRADA,
    },
    {
        "name": "cotizar_venta",
        "description": (
            "Calcula el valor exacto de una venta sin registrarla. Úsala antes de ofrecer un "
            "precio con descuento o varias unidades. Si las condiciones no se permiten, "
            "devuelve el motivo y los límites."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "codigo_oferta": _texto("Código de la oferta devuelto por consultar_ofertas."),
                "unidades": {"type": "integer", "description": "Número de unidades (1 o más)."},
                "descuento_porcentaje": _texto(
                    'Descuento sobre el precio, decimal con punto, p. ej. "0" o "10.00".'
                ),
            }
        ),
    },
    {
        "name": "derivar_a_humano",
        "description": (
            "Pasa la conversación a un asesor humano. Úsala siempre que el cliente pida una "
            "persona o un asesor (con cualquier palabra), ante una queja formal o cuando no "
            "puedas resolver. Después escribe un mensaje breve diciendo que un asesor "
            "continuará la conversación."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "motivo": {
                    "type": "string",
                    "enum": ["solicitud_cliente", "queja", "ia_no_resuelve"],
                },
                "resumen": _texto(
                    "Resumen para el asesor (máximo 500 caracteres): qué quiere el cliente y "
                    "qué se ofreció. Sin documento ni teléfono."
                ),
            }
        ),
    },
    {
        "name": "programar_seguimiento",
        "description": (
            "Registra que el cliente pide ser contactado en otro momento. El servidor rechaza "
            "fechas fuera del horario permitido y devuelve la próxima franja válida."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "fecha_hora_local": _texto(
                    "Fecha y hora local de Colombia en formato AAAA-MM-DDTHH:MM, "
                    'p. ej. "2026-10-26T09:00".'
                ),
                "motivo": _texto("Motivo breve (máximo 200 caracteres)."),
            }
        ),
    },
    {
        "name": "registrar_acuerdo_pago",
        "description": (
            "Registra un acuerdo de pago ya aceptado explícitamente por el cliente. Solo "
            "después de simular_acuerdo_pago con exactamente los mismos valores y de recibir "
            "un mensaje POSTERIOR del cliente que lo acepte. El servidor rechaza acuerdos "
            "fuera de las condiciones y citas que no aparezcan en un mensaje del cliente "
            "posterior a la simulación."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "monto_total": _texto(
                    'Monto total del acuerdo en pesos, decimal con punto, p. ej. "270000.00".'
                ),
                "numero_cuotas": {
                    "type": "integer",
                    "description": "Número de cuotas (1 = pago único).",
                },
                "fecha_primer_pago": {
                    "type": "string",
                    "format": "date",
                    "description": "Fecha del primer pago, AAAA-MM-DD.",
                },
                "periodicidad": _PERIODICIDAD,
                "confirmacion_cliente": _texto(
                    "Cita literal del mensaje del cliente en el que acepta el acuerdo."
                ),
            }
        ),
    },
    {
        "name": "registrar_autorizacion_whatsapp",
        "description": (
            "Registra que el cliente autoriza expresamente recibir mensajes de la empresa por "
            "WhatsApp para esta finalidad. Solo si el cliente lo dijo de forma explícita en "
            "la conversación."
        ),
        "strict": True,
        "input_schema": _esquema(
            {"cita_cliente": _texto("Cita literal del mensaje del cliente en el que autoriza.")}
        ),
    },
    {
        "name": "registrar_opt_out",
        "description": (
            "Registra que el cliente no quiere ser contactado. alcance: 'whatsapp' (no más "
            "mensajes por WhatsApp), 'llamadas' (no más llamadas; la conversación sigue), "
            "'todos_los_canales'. Con 'whatsapp' o 'todos_los_canales' la conversación "
            "termina y el sistema envía la confirmación: no escribas nada más."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "alcance": {
                    "type": "string",
                    "enum": ["whatsapp", "llamadas", "todos_los_canales"],
                },
                "cita_cliente": _texto("Cita literal del mensaje del cliente en el que lo pide."),
            }
        ),
    },
    {
        "name": "registrar_venta",
        "description": (
            "Registra una venta ya aceptada explícitamente por el cliente. Solo después de "
            "cotizar_venta con exactamente los mismos valores y de recibir un mensaje "
            "POSTERIOR del cliente que la acepte. El precio lo fija el servidor."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "codigo_oferta": _texto("Código de la oferta."),
                "unidades": {"type": "integer", "description": "Número de unidades."},
                "descuento_porcentaje": _texto("El mismo descuento cotizado, decimal con punto."),
                "confirmacion_cliente": _texto(
                    "Cita literal del mensaje del cliente en el que acepta la compra."
                ),
            }
        ),
    },
    {
        "name": "simular_acuerdo_pago",
        "description": (
            "Calcula un plan de pago sin registrarlo y lo valida contra las condiciones de la "
            "campaña. Úsala antes de proponer cualquier acuerdo. Si no se permite, devuelve "
            "el motivo y los valores mínimos o máximos permitidos."
        ),
        "strict": True,
        "input_schema": _esquema(
            {
                "monto_total": _texto(
                    'Monto total en pesos, decimal con punto, p. ej. "270000.00".'
                ),
                "numero_cuotas": {
                    "type": "integer",
                    "description": "Número de cuotas (1 = pago único).",
                },
                "fecha_primer_pago": {
                    "type": "string",
                    "format": "date",
                    "description": "Fecha del primer pago, AAAA-MM-DD.",
                },
                "periodicidad": _PERIODICIDAD,
            }
        ),
    },
    {
        "name": "verificar_identidad",
        "description": (
            "Comprueba que quien escribe es el titular comparando el número de documento que "
            "el cliente escribió con el registrado. Úsala antes de dar cualquier información "
            "de la cuenta. Nunca digas cuántos dígitos coinciden. Tras varios intentos "
            "fallidos la conversación pasa a un asesor."
        ),
        "strict": True,
        "input_schema": _esquema(
            {"numero_documento": _texto("Número de documento tal como lo escribió el cliente.")}
        ),
    },
]

DEFINICIONES: dict[str, dict[str, Any]] = {d["name"]: d for d in _DEFINICIONES}

# Herramientas por (canal, tipo de campaña) y requisitos.
_COMUNES = (
    "verificar_identidad",
    "consultar_historial_gestiones",
    "programar_seguimiento",
    "registrar_autorizacion_whatsapp",
    "registrar_opt_out",
    "derivar_a_humano",
    "cerrar_conversacion",
)
_POR_TIPO = {
    "cobranza": ("consultar_obligacion", "simular_acuerdo_pago", "registrar_acuerdo_pago"),
    "venta": ("consultar_ofertas", "cotizar_venta", "registrar_venta"),
}
REQUIEREN_IDENTIDAD = frozenset(
    {
        "consultar_obligacion",
        "simular_acuerdo_pago",
        "registrar_acuerdo_pago",
        "consultar_ofertas",
        "cotizar_venta",
        "registrar_venta",
        "consultar_historial_gestiones",
    }
)
TERMINALES = frozenset({"derivar_a_humano", "registrar_opt_out", "cerrar_conversacion"})


def nombres(canal: str, tipo: str) -> tuple[str, ...]:
    if canal != "chat" or tipo not in _POR_TIPO:
        raise ValueError(f"Sin catálogo de herramientas para {canal}/{tipo}.")
    return tuple(sorted((*_COMUNES, *_POR_TIPO[tipo])))


def catalogo(canal: str, tipo: str) -> list[dict[str, Any]]:
    """Herramientas enviadas al modelo, ordenadas por nombre (orden estable para la caché)."""
    return [DEFINICIONES[n] for n in nombres(canal, tipo)]


def serializar(herramientas: list[dict[str, Any]]) -> str:
    return json.dumps(herramientas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def huella(canal: str, tipo: str, prompt_version: int) -> str:
    """SHA-256 de las herramientas serializadas y el texto del sistema del canal."""
    contenido = serializar(catalogo(canal, tipo)) + "\n" + cargar_sistema(canal, prompt_version)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()
