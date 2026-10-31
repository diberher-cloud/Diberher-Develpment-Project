"""Bloque `ia` del objeto `Conversacion` (fase-2c.md §6.7)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.agente_ia import derivacion
from app.modulos.agente_ia.modelos import ConfiguracionIACampana
from app.modulos.consola.modelos import Tipificacion
from app.modulos.conversaciones.esquemas import (
    EstadoIAConversacion,
    GestionIA,
    Requisito,
    UltimoTraspaso,
)
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion
from app.modulos.usuarios.modelos import Usuario

MOTIVOS_IA = (
    "solicitud_cliente", "queja", "ia_no_resuelve", "identidad_bloqueada", "ia_rechazo",
    "ia_max_tokens", "ia_iteraciones", "ia_stop_inesperado", "ia_monto_no_respaldado", "ia_error",
    "presupuesto_excedido", "ia_desactivada", "supervisor",
)  # fmt: skip


def estado_ia(db: Session, conv: Conversacion, usuario: Usuario) -> EstadoIAConversacion | None:
    """`None` si la conversación nunca tuvo IA y su campaña no tiene IA configurada."""
    cfg = db.get(ConfiguracionIACampana, conv.campana_id) if conv.campana_id else None
    if conv.modelo_ia is None and (cfg is None or not cfg.activa):
        return None
    t = db.scalar(select(Tipificacion).where(Tipificacion.conversacion_id == conv.id))
    fila = db.scalar(
        select(ColaAtencion)
        .where(ColaAtencion.conversacion_id == conv.id, ColaAtencion.motivo.in_(MOTIVOS_IA))
        .order_by(ColaAtencion.id.desc())
        .limit(1)
    )
    motivos = [Requisito(codigo=c, mensaje=m) for c, m in derivacion.motivos_no_devolver(db, conv)]
    ve_coste = usuario.rol in ("administrador", "supervisor")
    return EstadoIAConversacion(
        identidad_verificada=conv.identidad_verificada,
        turnos=conv.turnos_ia,
        costo_usd=conv.costo_usd_acumulado if ve_coste else None,
        modelo=conv.modelo_ia,
        gestion=GestionIA(resultado=t.resultado, tipificacion_id=t.id) if t else None,
        aviso_enviado=conv.aviso_ia_enviado_en is not None,
        ultimo_traspaso=(
            UltimoTraspaso(motivo=fila.motivo, resumen=fila.resumen, creado_en=fila.creado_en)
            if fila
            else None
        ),
        puede_devolver_ia=conv.atendida_por != "ia" and not motivos,
        motivos_no_devolver=motivos,
    )
