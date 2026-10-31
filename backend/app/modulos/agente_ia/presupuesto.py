"""Presupuesto, límites por conversación y desactivación automática (fase-2c.md §4.11).

El presupuesto mensual es un límite SUAVE: turnos concurrentes de la misma campaña pueden
sobrepasarlo como mucho en el coste de esos turnos. Las desactivaciones son idempotentes
(una sola alerta aunque varios turnos crucen el límite a la vez).
"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.agente_ia import eventos
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, ErrorIA, UsoIA
from app.modulos.auditoria import servicio as auditoria
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.cumplimiento import servicio as cumplimiento
from app.trabajos.cola import encolar


def inicio_de_mes(db: Session, tipo_campana: str, ahora: datetime) -> tuple[datetime, str]:
    """(inicio del mes local en UTC, `AAAA-MM` local) según la zona de la política del tipo."""
    politica, _ = cumplimiento.cargar_politica(db, tipo_campana)
    local = ahora.astimezone(ZoneInfo(politica.zona_horaria))
    inicio = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return inicio, f"{local.year:04d}-{local.month:02d}"


def gasto_mes(db: Session, campana_id: int, tipo_campana: str, ahora: datetime) -> Decimal:
    inicio, _ = inicio_de_mes(db, tipo_campana, ahora)
    return db.scalar(
        select(func.coalesce(func.sum(UsoIA.costo_usd), 0)).where(
            UsoIA.campana_id == campana_id, UsoIA.creado_en >= inicio
        )
    ) or Decimal(0)


def conversacion_excedida(conv: Conversacion, cfg: ConfiguracionIACampana, al_inicio: bool) -> bool:
    """Coste acumulado >= máximo, o (al inicio del turno) turnos >= máximo."""
    if conv.costo_usd_acumulado >= cfg.max_costo_conversacion_usd:
        return True
    return al_inicio and conv.turnos_ia >= cfg.max_turnos_conversacion


def comprobar_campana(
    db: Session, cfg: ConfiguracionIACampana, tipo_campana: str, ahora: datetime
) -> bool:
    """True si la campaña superó su presupuesto mensual (y lo desactiva). Al cruzar el
    `IA_ALERTA_PRESUPUESTO_PCT` avisa una vez por mes."""
    gasto = gasto_mes(db, cfg.campana_id, tipo_campana, ahora)
    if gasto >= cfg.presupuesto_usd_mensual:
        desactivar_automatica(db, cfg.campana_id, "presupuesto", ahora)
        return True
    umbral = cfg.presupuesto_usd_mensual * Decimal(get_settings().ia_alerta_presupuesto_pct) / 100
    if gasto >= umbral:
        _, mes = inicio_de_mes(db, tipo_campana, ahora)
        r = db.execute(
            update(ConfiguracionIACampana)
            .where(
                ConfiguracionIACampana.campana_id == cfg.campana_id,
                (ConfiguracionIACampana.alerta_presupuesto_mes.is_(None))
                | (ConfiguracionIACampana.alerta_presupuesto_mes != mes),
            )
            .values(alerta_presupuesto_mes=mes)
            .execution_options(synchronize_session=False)
        )
        if r.rowcount == 1:
            eventos.publicar_alerta(db, "presupuesto_campana", "aviso", cfg.campana_id)
    return False


def desactivar_automatica(db: Session, campana_id: int, motivo: str, ahora: datetime) -> bool:
    """Apaga la IA de la campaña (`presupuesto` | `errores`) una sola vez: UPDATE condicional
    `activa = true`. Encola el traspaso de sus conversaciones y avisa. Sin commit."""
    r = db.execute(
        update(ConfiguracionIACampana)
        .where(ConfiguracionIACampana.campana_id == campana_id, ConfiguracionIACampana.activa)
        .values(activa=False, desactivada_motivo=motivo, desactivada_en=ahora)
        .execution_options(synchronize_session=False)
    )
    if r.rowcount != 1:
        return False
    auditoria.registrar(
        db,
        "ia.desactivar",
        None,
        "campana",
        campana_id,
        {"campana_id": campana_id, "motivo": motivo},
    )
    encolar_traspaso(db, campana_id, ahora)
    cfg = db.get(ConfiguracionIACampana, campana_id)
    if cfg is not None:
        db.refresh(cfg)
    eventos.publicar_configuracion(db, campana_id, False, cfg.version if cfg else None, motivo)
    eventos.publicar_alerta(
        db, "presupuesto_campana" if motivo == "presupuesto" else "errores", "critico", campana_id
    )
    return True


def encolar_traspaso(db: Session, campana_id: int | None, ahora: datetime) -> None:
    encolar(
        db,
        "ia.traspasar_campana",
        {"campana_id": campana_id, "motivo": "ia_desactivada"},
        clave_unica=f"ia_traspaso:{campana_id if campana_id is not None else 'global'}",
        ahora=ahora,
        max_intentos=5,
    )


def registrar_error(
    db: Session,
    ref_tipo: str,
    ref_id: int,
    campana_id: int,
    codigo: str,
    transitorio: bool,
    ahora: datetime,
) -> ErrorIA:
    fila = ErrorIA(
        conversacion_id=ref_id if ref_tipo == "conversacion" else None,
        llamada_id=ref_id if ref_tipo == "llamada" else None,
        campana_id=campana_id,
        codigo=codigo[:40],
        transitorio=transitorio,
        creado_en=ahora,
    )
    db.add(fila)
    db.flush()
    return fila


def comprobar_errores(db: Session, campana_id: int, ahora: datetime) -> bool:
    """≥ `IA_ERRORES_UMBRAL` errores no transitorios (o `AGOTADO`) de la campaña en la ventana
    -> desactivación automática (`errores`)."""
    s = get_settings()
    desde = ahora - timedelta(minutes=s.ia_errores_ventana_minutos)
    n = db.scalar(
        select(func.count(ErrorIA.id)).where(
            ErrorIA.campana_id == campana_id,
            ErrorIA.creado_en >= desde,
            (ErrorIA.transitorio.is_(False)) | (ErrorIA.codigo == "AGOTADO"),
        )
    )
    if (n or 0) >= s.ia_errores_umbral:
        return desactivar_automatica(db, campana_id, "errores", ahora)
    return False
