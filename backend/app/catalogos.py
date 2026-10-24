"""Catálogos compartidos entre módulos (enumeraciones como VARCHAR + CHECK, ADR-0006)."""

RESULTADOS = (
    "contactado",
    "no_contesta",
    "numero_errado",
    "promesa_pago",
    "venta",
    "rechazo",
    "volver_a_llamar",
)
CANALES = ("voz", "whatsapp_mensaje", "whatsapp_llamada")
ORIGENES_GESTION = ("agente", "agente_ia", "sistema")
ESTADOS_AGENTE = ("desconectado", "disponible", "pausa", "en_llamada", "tipificando")
MOTIVOS_PAUSA = ("descanso", "almuerzo", "capacitacion", "reunion", "otro")
ESTADOS_LLAMADA = (
    "iniciando",
    "sonando",
    "en_curso",
    "completada",
    "ocupado",
    "no_contesta",
    "fallida",
    "cancelada",
    "bloqueada",
)
ESTADOS_LLAMADA_TERMINALES = (
    "completada",
    "ocupado",
    "no_contesta",
    "fallida",
    "cancelada",
    "bloqueada",
)
# Estados no terminales: la llamada sigue en curso.
ESTADOS_LLAMADA_ACTIVAS = ("iniciando", "sonando", "en_curso")
# Estados terminales de una llamada que SÍ se realizó (exigen tipificación).
ESTADOS_LLAMADA_TIPIFICABLES = ("completada", "ocupado", "no_contesta", "fallida", "cancelada")
# Terminales en los que la llamada nunca fue contestada.
ESTADOS_NO_CONTESTADA = ("ocupado", "no_contesta", "fallida", "cancelada")


def en_lista(columna: str, valores: tuple[str, ...]) -> str:
    """Expresión SQL `columna IN ('a','b')` para CheckConstraint."""
    return f"{columna} IN (" + ",".join(f"'{v}'" for v in valores) + ")"
