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


# ---- Fase 2B: WhatsApp y bandeja ---------------------------------------------------------------
CATEGORIAS_PLANTILLA = ("marketing", "utility", "authentication", "desconocida")
ESTADOS_APROBACION = (
    "aprobada",
    "pendiente",
    "rechazada",
    "pausada",
    "deshabilitada",
    "eliminada",
    "desconocido",
)
FINALIDADES = ("venta", "cobranza", "todas")
ESTADOS_CONVERSACION = ("abierta", "cerrada")
ATENDIDA_POR = ("sin_asignar", "humano", "ia")
INICIADA_POR = ("empresa", "cliente")
MOTIVOS_CIERRE = ("agente", "supervisor", "inactividad", "opt_out", "sistema")
DIRECCIONES_MENSAJE = ("entrante", "saliente")
AUTORES_MENSAJE = ("cliente", "agente", "ia", "sistema")
TIPOS_MENSAJE = ("texto", "plantilla", "media", "boton", "no_soportado")
ESTADOS_MENSAJE = (
    "recibido",
    "pendiente",
    "retenido",
    "enviando",
    "enviado",
    "entregado",
    "leido",
    "fallido",
    "cancelado",
)
ORIGENES_AUTORIZACION = ("importacion", "cliente", "agente", "agente_ia")
MOTIVOS_REVOCACION = ("opt_out", "manual", "importacion")
ESTADOS_COLA = ("pendiente", "asignada", "cerrada")
MOTIVOS_COLA = (
    "entrante",
    "sin_campana",
    "liberada",
    "agente_desconectado",
    "supervisor",
    "solicitud_cliente",
    "queja",
    "ia_no_resuelve",
    "identidad_bloqueada",
    "ia_rechazo",
    "ia_max_tokens",
    "ia_iteraciones",
    "ia_stop_inesperado",
    "ia_monto_no_respaldado",
    "ia_error",
    "presupuesto_excedido",
    "ia_desactivada",
)
ESTADOS_TRABAJO = ("pendiente", "en_proceso", "completado", "fallido", "cancelado")
CANALES_EXCLUSION = ("todos", "voz", "whatsapp")
ORIGENES_EXCLUSION = ("usuario", "sistema", "agente_ia")
