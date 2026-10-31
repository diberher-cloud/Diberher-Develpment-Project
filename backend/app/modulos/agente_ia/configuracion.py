"""Configuración IA por campaña, ofertas, interruptor global y requisitos de activación
(fase-2c.md §6.2-6.4). Un `PUT`/activar/desactivar bloquea SOLO la fila de configuración."""

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalogos import ESFUERZOS_IA
from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.agente_ia import eventos
from app.modulos.agente_ia.esquemas import (
    ConfiguracionGlobalIA,
    ConfiguracionIA,
    ConfiguracionIAActualizar,
    OfertaActualizar,
    OfertaCrear,
    Requisito,
    RequisitosActivacion,
    VerificacionIA,
)
from app.modulos.agente_ia.herramientas.definiciones import huella as huella_canal
from app.modulos.agente_ia.limites import (
    ErroresReglas,
    ReglasCobranza,
    ReglasVenta,
    validar_reglas_cobranza,
    validar_reglas_venta,
)
from app.modulos.agente_ia.modelos import (
    ConfiguracionGlobal,
    ConfiguracionIACampana,
    EvaluacionIA,
    OfertaCampana,
)
from app.modulos.agente_ia.prompts import VERSIONES
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.conversaciones.esquemas import UsuarioRef
from app.modulos.usuarios.modelos import Usuario
from app.trabajos.cola import encolar

VERIFICACION_DEFECTO = {"factores": ["numero_documento"], "max_intentos": 3}


# ---- Disponibilidad ----------------------------------------------------------------------------
def ia_global_activa(db: Session) -> bool:
    fila = db.get(ConfiguracionGlobal, "ia_activa")
    return True if fila is None else bool(fila.valor)


def ia_disponible(db: Session, campana_id: int | None) -> bool:
    """IA_HABILITADA ∧ interruptor global ∧ campaña activa con WhatsApp ∧ configuración activa."""
    if campana_id is None or not get_settings().ia_habilitada or not ia_global_activa(db):
        return False
    campana = db.get(Campana, campana_id)
    if campana is None or campana.estado != "activa" or not campana.whatsapp_habilitado:
        return False
    cfg = db.get(ConfiguracionIACampana, campana_id)
    return cfg is not None and cfg.activa


def huella_evaluacion(prompt_version: int) -> str:
    """Huella de lo que cubre una evaluación del canal chat: herramientas + prompt de los dos
    tipos de campaña (la evaluación incluye casos de cobranza y de venta)."""
    union = huella_canal("chat", "cobranza", prompt_version) + huella_canal(
        "chat", "venta", prompt_version
    )
    return hashlib.sha256(union.encode()).hexdigest()


# ---- Requisitos de activación ------------------------------------------------------------------
def evaluacion_vigente(
    db: Session,
    modo: str,
    prompt_version: int,
    *,
    campana_id: int | None = None,
    modelo: str | None = None,
    esfuerzo: str | None = None,
    desde: datetime | None = None,
) -> EvaluacionIA | None:
    consulta = select(EvaluacionIA).where(
        EvaluacionIA.modo == modo,
        EvaluacionIA.canal == "chat",
        EvaluacionIA.prompt_version == prompt_version,
        EvaluacionIA.huella == huella_evaluacion(prompt_version),
        EvaluacionIA.estado == "completada",
        EvaluacionIA.aprobada.is_(True),
        EvaluacionIA.patron_casos.is_(None),
    )
    if campana_id is not None:
        consulta = consulta.where(EvaluacionIA.campana_id == campana_id)
    if modelo is not None:
        consulta = consulta.where(EvaluacionIA.modelo == modelo, EvaluacionIA.esfuerzo == esfuerzo)
    if desde is not None:
        consulta = consulta.where(EvaluacionIA.creado_en >= desde)
    return db.scalar(consulta.order_by(EvaluacionIA.id.desc()).limit(1))


def reglas_validas(tipo: str, reglas: Any) -> bool:
    try:
        if tipo == "cobranza":
            validar_reglas_cobranza(reglas)
        else:
            validar_reglas_venta(reglas)
    except ErroresReglas:
        return False
    return True


def faltantes_activacion(
    db: Session,
    campana: Campana,
    cfg: ConfiguracionIACampana | None,
    ahora: datetime,
    nuevos: dict[str, Any] | None = None,
) -> list[Requisito]:
    """Requisitos no cumplidos. `nuevos` sobreescribe valores de `cfg` (validar un PUT)."""
    s = get_settings()
    faltan: list[Requisito] = []

    def falta(codigo: str, mensaje: str) -> None:
        faltan.append(Requisito(codigo=codigo, mensaje=mensaje))

    if not campana.whatsapp_habilitado:
        falta("WHATSAPP_NO_HABILITADO", "La campaña no tiene WhatsApp habilitado.")
    if cfg is None and nuevos is None:
        falta("SIN_CONFIGURACION", "La campaña no tiene configuración de IA.")
        return faltan + _globales(db, s)
    valores = {
        "modelo": cfg.modelo if cfg else None,
        "esfuerzo": cfg.esfuerzo if cfg else None,
        "prompt_version": cfg.prompt_version if cfg else 1,
        "reglas": cfg.reglas if cfg else None,
        "presupuesto_usd_mensual": cfg.presupuesto_usd_mensual if cfg else Decimal(0),
        **(nuevos or {}),
    }
    if not reglas_validas(campana.tipo, valores["reglas"]):
        falta("REGLAS_INVALIDAS", "Las reglas de la campaña no son válidas.")
    if campana.tipo == "venta":
        n = db.scalar(
            select(func.count(OfertaCampana.id)).where(
                OfertaCampana.campana_id == campana.id, OfertaCampana.activa.is_(True)
            )
        )
        if not n:
            falta("SIN_OFERTAS_ACTIVAS", "La campaña de venta no tiene ofertas activas.")
    if valores["presupuesto_usd_mensual"] <= 0:
        falta("PRESUPUESTO_CERO", "El presupuesto mensual debe ser mayor que cero.")
    if not db.scalar(
        select(func.count(CampanaAgente.id)).where(CampanaAgente.campana_id == campana.id)
    ):
        falta("SIN_AGENTES_ASIGNADOS", "Asigne al menos un agente humano de respaldo.")
    v = valores["prompt_version"]
    if evaluacion_vigente(db, "offline", v) is None:
        falta(
            "EVALUACION_OFFLINE_PENDIENTE",
            f"No hay una evaluación offline aprobada para la versión {v} del prompt de chat.",
        )
    if s.ia_exigir_evaluacion_online and (
        evaluacion_vigente(
            db,
            "online",
            v,
            campana_id=campana.id,
            modelo=valores["modelo"],
            esfuerzo=valores["esfuerzo"],
            desde=ahora - timedelta(days=30),
        )
        is None
    ):
        falta(
            "EVALUACION_ONLINE_PENDIENTE",
            "No hay una evaluación online aprobada reciente con este modelo y esfuerzo.",
        )
    if valores["modelo"] is not None and valores["modelo"] not in s.precios_ia:
        falta("MODELO_SIN_PRECIO", "El modelo no tiene precio configurado.")
    return faltan + _globales(db, s)


def _globales(db: Session, s) -> list[Requisito]:
    faltan = []
    if not ia_global_activa(db):
        faltan.append(
            Requisito(codigo="IA_GLOBAL_DESACTIVADA", mensaje="La IA está desactivada globalmente.")
        )
    if s.entorno == "produccion" and s.ia_proveedor == "falso":
        faltan.append(
            Requisito(
                codigo="PROVEEDOR_FALSO_EN_PRODUCCION",
                mensaje="En producción se necesita el proveedor real de IA.",
            )
        )
    return faltan


# ---- Salidas -----------------------------------------------------------------------------------
def _ref(db: Session, usuario_id: int | None) -> UsuarioRef | None:
    u = db.get(Usuario, usuario_id) if usuario_id else None
    return UsuarioRef(id=u.id, nombre=u.nombre) if u else None


def salida(db: Session, campana: Campana, ahora: datetime) -> ConfiguracionIA:
    from app.modulos.agente_ia.presupuesto import gasto_mes

    s = get_settings()
    cfg = db.get(ConfiguracionIACampana, campana.id)
    faltantes = faltantes_activacion(db, campana, cfg, ahora)
    gasto = gasto_mes(db, campana.id, campana.tipo, ahora)
    comunes = {
        "campana_id": campana.id,
        "campana_tipo": campana.tipo,
        "gasto_mes_usd": gasto,
        "requisitos": RequisitosActivacion(cumple=not faltantes, faltantes=faltantes),
    }
    if cfg is None:
        return ConfiguracionIA(
            configurada=False,
            activa=False,
            version=0,
            modelo=s.ia_modelo_por_defecto,
            esfuerzo=s.ia_esfuerzo_por_defecto,
            prompt_version=VERSIONES["chat"][-1],
            tratamiento="usted",
            instrucciones=None,
            verificacion=VerificacionIA(**VERIFICACION_DEFECTO),
            reglas=None,
            presupuesto_usd_mensual=Decimal(0),
            max_costo_conversacion_usd=Decimal("0.5"),
            max_turnos_conversacion=30,
            desactivada_motivo=None,
            activada_en=None,
            desactivada_en=None,
            actualizado_por=None,
            actualizado_en=None,
            **comunes,
        )
    return ConfiguracionIA(
        configurada=True,
        activa=cfg.activa,
        version=cfg.version,
        modelo=cfg.modelo,
        esfuerzo=cfg.esfuerzo,  # type: ignore[arg-type]
        prompt_version=cfg.prompt_version,
        tratamiento=cfg.tratamiento,  # type: ignore[arg-type]
        instrucciones=cfg.instrucciones,
        verificacion=VerificacionIA(**cfg.verificacion),
        reglas=cfg.reglas,
        presupuesto_usd_mensual=cfg.presupuesto_usd_mensual,
        max_costo_conversacion_usd=cfg.max_costo_conversacion_usd,
        max_turnos_conversacion=cfg.max_turnos_conversacion,
        desactivada_motivo=cfg.desactivada_motivo,  # type: ignore[arg-type]
        activada_en=cfg.activada_en,
        desactivada_en=cfg.desactivada_en,
        actualizado_por=_ref(db, cfg.actualizado_por),
        actualizado_en=cfg.actualizado_en,
        **comunes,
    )


def _campana(db: Session, campana_id: int) -> Campana:
    c = db.get(Campana, campana_id)
    if c is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    return c


def _cfg_bloqueada(db: Session, campana_id: int) -> ConfiguracionIACampana | None:
    return db.scalar(
        select(ConfiguracionIACampana)
        .where(ConfiguracionIACampana.campana_id == campana_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _validacion(errores: list[tuple[str, str]]) -> ErrorApp:
    return ErrorApp(
        422,
        "VALIDACION",
        "Los datos enviados no son válidos.",
        [detalle(c, m) for c, m in errores],
    )


def _requisitos_error(faltantes: list[Requisito]) -> ErrorApp:
    return ErrorApp(
        409,
        "IA_REQUISITOS_ACTIVACION",
        "No se cumplen los requisitos de activación de la IA.",
        [detalle("requisitos", f"{f.codigo}: {f.mensaje}") for f in faltantes],
    )


# ---- Operaciones -------------------------------------------------------------------------------
def obtener(db: Session, campana_id: int, ahora: datetime) -> ConfiguracionIA:
    return salida(db, _campana(db, campana_id), ahora)


def actualizar(
    db: Session,
    usuario: Usuario,
    campana_id: int,
    datos: ConfiguracionIAActualizar,
    ahora: datetime,
) -> ConfiguracionIA:
    campana = _campana(db, campana_id)
    if campana.estado == "finalizada":
        raise ErrorApp(409, "CAMPANA_FINALIZADA", "La campaña está finalizada.")
    s = get_settings()
    cfg = _cfg_bloqueada(db, campana_id)
    actual = cfg.version if cfg else 0
    if datos.version_esperada != actual:
        raise ErrorApp(
            409, "IA_VERSION_CONFLICTO", "La configuración cambió; recargue e intente de nuevo."
        )
    errores: list[tuple[str, str]] = []
    if datos.modelo not in s.modelos_ia_permitidos:
        errores.append(("modelo", "Modelo no permitido."))
    if datos.prompt_version not in VERSIONES["chat"]:
        errores.append(("prompt_version", "Versión de prompt desconocida."))
    if datos.esfuerzo not in ESFUERZOS_IA:
        errores.append(("esfuerzo", "Esfuerzo desconocido."))
    if datos.verificacion.factores != ["numero_documento"]:
        errores.append(("verificacion.factores", "Solo se admite ['numero_documento']."))
    reglas_json: dict[str, Any] = {}
    try:
        if campana.tipo == "cobranza":
            reglas_json = validar_reglas_cobranza(datos.reglas).model_dump(mode="json")
        else:
            reglas_json = validar_reglas_venta(datos.reglas).model_dump(mode="json")
    except ErroresReglas as e:
        errores += [(f"reglas.{c}" if c else "reglas", m) for c, m in e.detalles]
    if errores:
        raise _validacion(errores)
    instrucciones = (datos.instrucciones or "").strip()[:2000] or None
    if cfg is not None and cfg.activa:
        faltantes = faltantes_activacion(
            db,
            campana,
            cfg,
            ahora,
            nuevos={
                "modelo": datos.modelo,
                "esfuerzo": datos.esfuerzo,
                "prompt_version": datos.prompt_version,
                "reglas": reglas_json,
                "presupuesto_usd_mensual": datos.presupuesto_usd_mensual,
            },
        )
        if faltantes:
            raise _requisitos_error(faltantes)
    nuevos = {
        "modelo": datos.modelo,
        "esfuerzo": datos.esfuerzo,
        "prompt_version": datos.prompt_version,
        "tratamiento": datos.tratamiento,
        "instrucciones": instrucciones,
        "verificacion": datos.verificacion.model_dump(),
        "reglas": reglas_json,
        "presupuesto_usd_mensual": datos.presupuesto_usd_mensual,
        "max_costo_conversacion_usd": datos.max_costo_conversacion_usd,
        "max_turnos_conversacion": datos.max_turnos_conversacion,
    }
    if cfg is None:
        cfg = ConfiguracionIACampana(
            campana_id=campana_id, version=1, activa=False, creado_en=ahora, **nuevos
        )
        cfg.actualizado_por, cfg.actualizado_en = usuario.id, ahora
        campos = list(nuevos)
        try:
            with db.begin_nested():
                db.add(cfg)
                db.flush()
        except IntegrityError:
            db.rollback()
            raise ErrorApp(
                409, "IA_VERSION_CONFLICTO", "La configuración cambió; recargue e intente."
            ) from None
    else:
        campos = [k for k, v in nuevos.items() if getattr(cfg, k) != v]
        for k, v in nuevos.items():
            setattr(cfg, k, v)
        cfg.version += 1
        cfg.actualizado_por, cfg.actualizado_en = usuario.id, ahora
    auditoria.registrar(
        db,
        "ia.configuracion_actualizar",
        usuario.id,
        "campana",
        campana_id,
        {"campana_id": campana_id, "version": cfg.version, "campos": campos},
    )
    eventos.publicar_configuracion(db, campana_id, cfg.activa, cfg.version, cfg.desactivada_motivo)
    db.commit()
    return salida(db, campana, ahora)


def activar(db: Session, usuario: Usuario, campana_id: int, ahora: datetime) -> ConfiguracionIA:
    campana = _campana(db, campana_id)
    cfg = _cfg_bloqueada(db, campana_id)
    if cfg is not None and cfg.activa:
        return salida(db, campana, ahora)
    faltantes = faltantes_activacion(db, campana, cfg, ahora)
    if faltantes:
        db.rollback()
        raise _requisitos_error(faltantes)
    assert cfg is not None
    cfg.activa, cfg.activada_en, cfg.desactivada_motivo = True, ahora, None
    auditoria.registrar(
        db, "ia.activar", usuario.id, "campana", campana_id, {"campana_id": campana_id}
    )
    eventos.publicar_configuracion(db, campana_id, True, cfg.version, None)
    db.commit()
    return salida(db, campana, ahora)


def desactivar(db: Session, usuario: Usuario, campana_id: int, ahora: datetime) -> ConfiguracionIA:
    campana = _campana(db, campana_id)
    cfg = _cfg_bloqueada(db, campana_id)
    if cfg is not None and cfg.activa:
        cfg.activa, cfg.desactivada_motivo, cfg.desactivada_en = False, "manual", ahora
        auditoria.registrar(
            db,
            "ia.desactivar",
            usuario.id,
            "campana",
            campana_id,
            {"campana_id": campana_id, "motivo": "manual"},
        )
        from app.modulos.agente_ia.presupuesto import encolar_traspaso

        encolar_traspaso(db, campana_id, ahora)
        eventos.publicar_configuracion(db, campana_id, False, cfg.version, "manual")
        eventos.publicar_alerta(db, "kill_switch", "critico", campana_id)
    db.commit()
    return salida(db, campana, ahora)


# ---- Global ------------------------------------------------------------------------------------
def global_salida(db: Session) -> ConfiguracionGlobalIA:
    s = get_settings()
    fila = db.get(ConfiguracionGlobal, "ia_activa")
    return ConfiguracionGlobalIA(
        ia_activa=ia_global_activa(db),
        ia_habilitada_entorno=s.ia_habilitada,
        proveedor=s.ia_proveedor,
        modelos_permitidos=s.modelos_ia_permitidos,
        esfuerzos=list(ESFUERZOS_IA),
        prompts={k: list(v) for k, v in VERSIONES.items()},
        exigir_evaluacion_online=s.ia_exigir_evaluacion_online,
        actualizado_por=_ref(db, fila.actualizado_por) if fila else None,
        actualizado_en=fila.actualizado_en if fila else None,
    )


def fijar_global(
    db: Session, usuario: Usuario, activa: bool, ahora: datetime
) -> ConfiguracionGlobalIA:
    fila = db.scalar(
        select(ConfiguracionGlobal)
        .where(ConfiguracionGlobal.clave == "ia_activa")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if fila is None:
        fila = ConfiguracionGlobal(clave="ia_activa", valor=activa, actualizado_en=ahora)
        db.add(fila)
    anterior = bool(fila.valor)
    fila.valor, fila.actualizado_por, fila.actualizado_en = activa, usuario.id, ahora
    auditoria.registrar(db, "ia.global", usuario.id, None, None, {"ia_activa": activa})
    eventos.publicar_configuracion(db, None, activa, None, None)
    if not activa:
        from app.modulos.agente_ia.presupuesto import encolar_traspaso

        encolar_traspaso(db, None, ahora)
        eventos.publicar_alerta(db, "kill_switch", "critico", None)
    del anterior
    db.commit()
    return global_salida(db)


# ---- Ofertas -----------------------------------------------------------------------------------
def _validar_oferta(datos: dict[str, Any]) -> list[tuple[str, str]]:
    import re

    e: list[tuple[str, str]] = []
    if "codigo" in datos and not re.fullmatch(r"[A-Z0-9_-]{2,30}", datos["codigo"]):
        e.append(("codigo", "Debe tener 2 a 30 caracteres: letras, números, guion o guion bajo."))
    if "nombre" in datos and not 2 <= len(datos["nombre"].strip()) <= 120:
        e.append(("nombre", "Debe tener entre 2 y 120 caracteres."))
    if datos.get("descripcion") and len(datos["descripcion"]) > 500:
        e.append(("descripcion", "Máximo 500 caracteres."))
    if "precio" in datos and not (
        Decimal(0) < datos["precio"] <= Decimal("999999999999.99")
        and datos["precio"] == datos["precio"].quantize(Decimal("0.01"))
    ):
        e.append(("precio", "Debe ser mayor que cero con hasta 2 decimales."))
    if "descuento_max_pct" in datos and not (
        0 <= datos["descuento_max_pct"] <= 100
        and datos["descuento_max_pct"] == datos["descuento_max_pct"].quantize(Decimal("0.01"))
    ):
        e.append(("descuento_max_pct", "Debe estar entre 0 y 100 con hasta 2 decimales."))
    if "max_unidades" in datos and not 1 <= datos["max_unidades"] <= 100:
        e.append(("max_unidades", "Debe estar entre 1 y 100."))
    if datos.get("condiciones") and len(datos["condiciones"]) > 1000:
        e.append(("condiciones", "Máximo 1000 caracteres."))
    return e


def listar_ofertas(db: Session, campana_id: int, activas: bool | None) -> list[OfertaCampana]:
    _campana(db, campana_id)
    consulta = select(OfertaCampana).where(OfertaCampana.campana_id == campana_id)
    if activas is not None:
        consulta = consulta.where(OfertaCampana.activa.is_(activas))
    return list(db.scalars(consulta.order_by(OfertaCampana.codigo)))


def crear_oferta(
    db: Session, usuario: Usuario, campana_id: int, datos: OfertaCrear, ahora: datetime
) -> OfertaCampana:
    campana = _campana(db, campana_id)
    if campana.estado == "finalizada":
        raise ErrorApp(409, "CAMPANA_FINALIZADA", "La campaña está finalizada.")
    if campana.tipo != "venta":
        raise _validacion([("campana_id", "Las ofertas solo aplican a campañas de venta.")])
    valores = datos.model_dump()
    valores["codigo"] = valores["codigo"].strip().upper()
    errores = _validar_oferta(valores)
    if errores:
        raise _validacion(errores)
    oferta = OfertaCampana(
        campana_id=campana_id,
        actualizado_por=usuario.id,
        creado_en=ahora,
        actualizado_en=ahora,
        **valores,
    )
    try:
        with db.begin_nested():
            db.add(oferta)
            db.flush()
    except IntegrityError:
        db.rollback()
        raise ErrorApp(409, "OFERTA_DUPLICADA", "Ya existe una oferta con ese código.") from None
    auditoria.registrar(
        db,
        "ia.oferta_crear",
        usuario.id,
        "oferta",
        oferta.id,
        {"oferta_id": oferta.id, "campana_id": campana_id},
    )
    db.commit()
    return oferta


def actualizar_oferta(
    db: Session,
    usuario: Usuario,
    campana_id: int,
    oferta_id: int,
    datos: OfertaActualizar,
    ahora: datetime,
) -> OfertaCampana:
    campana = _campana(db, campana_id)
    cfg = _cfg_bloqueada(db, campana_id)  # un solo lock (la configuración) antes de tocar ofertas
    oferta = db.get(OfertaCampana, oferta_id)
    if oferta is None or oferta.campana_id != campana_id:
        raise ErrorApp(404, "NO_ENCONTRADO", "Oferta no encontrada.")
    cambios = datos.model_dump(exclude_unset=True)
    errores = _validar_oferta({k: v for k, v in cambios.items() if v is not None})
    if errores:
        raise _validacion(errores)
    for k, v in cambios.items():
        if v is None and k in ("nombre", "precio", "descuento_max_pct", "max_unidades", "activa"):
            continue
        setattr(oferta, k, v)
    oferta.actualizado_por, oferta.actualizado_en = usuario.id, ahora
    db.flush()
    if cfg is not None and cfg.activa and campana.tipo == "venta":
        activas = db.scalar(
            select(func.count(OfertaCampana.id)).where(
                OfertaCampana.campana_id == campana_id, OfertaCampana.activa.is_(True)
            )
        )
        if not activas:
            db.rollback()
            raise _requisitos_error(
                [
                    Requisito(
                        codigo="SIN_OFERTAS_ACTIVAS",
                        mensaje="La campaña de venta no tiene ofertas activas.",
                    )
                ]
            )
    auditoria.registrar(
        db,
        "ia.oferta_actualizar",
        usuario.id,
        "oferta",
        oferta.id,
        {"oferta_id": oferta.id, "campos": sorted(cambios)},
    )
    db.commit()
    return oferta


__all__ = [
    "ReglasCobranza",
    "ReglasVenta",
    "encolar",
]
