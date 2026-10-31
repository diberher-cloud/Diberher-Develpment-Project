"""Evaluaciones registradas en `evaluaciones_ia` y trabajo `ia.evaluacion` (fase-2c.md §6.9)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.agente_ia import configuracion, eventos
from app.modulos.agente_ia.esquemas import EvaluacionCrear
from app.modulos.agente_ia.esquemas import EvaluacionIA as EvaluacionSalida
from app.modulos.agente_ia.evaluacion import casos as casos_mod
from app.modulos.agente_ia.evaluacion import harness, informe
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, EvaluacionIA
from app.modulos.agente_ia.prompts import VERSIONES
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.conversaciones.esquemas import UsuarioRef
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import Pagina, ParamsPaginacion, paginar
from app.trabajos.cola import encolar


def salida(db: Session, e: EvaluacionIA) -> EvaluacionSalida:
    u = db.get(Usuario, e.iniciada_por) if e.iniciada_por else None
    return EvaluacionSalida(
        id=e.id,
        modo=e.modo,
        canal=e.canal,
        campana_id=e.campana_id,
        modelo=e.modelo,
        esfuerzo=e.esfuerzo,
        prompt_version=e.prompt_version,
        huella=e.huella,
        patron_casos=e.patron_casos,
        estado=e.estado,
        aprobada=e.aprobada,
        resumen=e.resumen,
        casos=e.casos,
        iniciada_por=UsuarioRef(id=u.id, nombre=u.nombre) if u else None,
        creado_en=e.creado_en,
        completada_en=e.completada_en,
    )


def _validacion(campo: str, mensaje: str) -> ErrorApp:
    return ErrorApp(
        422, "VALIDACION", "Los datos enviados no son válidos.", [detalle(campo, mensaje)]
    )


def crear(
    db: Session, usuario: Usuario, datos: EvaluacionCrear, ahora: datetime
) -> EvaluacionSalida:
    s = get_settings()
    cfg = None
    if datos.modo == "offline" and datos.campana_id is not None:
        raise _validacion("campana_id", "No aplica a una evaluación offline.")
    if datos.modo == "online":
        if datos.campana_id is None:
            raise _validacion("campana_id", "Obligatorio en una evaluación online.")
        if db.get(Campana, datos.campana_id) is None:
            raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
        if s.ia_proveedor != "anthropic" or not s.anthropic_api_key.get_secret_value():
            raise ErrorApp(
                409, "IA_PROVEEDOR_NO_CONFIGURADO", "La evaluación online exige el proveedor real."
            )
        cfg = db.get(ConfiguracionIACampana, datos.campana_id)
        if cfg is None:
            raise ErrorApp(409, "IA_NO_DISPONIBLE", "La campaña no tiene configuración de IA.")
    en_curso = db.scalar(
        select(EvaluacionIA.id).where(
            EvaluacionIA.modo == datos.modo,
            EvaluacionIA.campana_id.is_(None)
            if datos.campana_id is None
            else EvaluacionIA.campana_id == datos.campana_id,
            EvaluacionIA.estado.in_(("pendiente", "en_curso")),
        )
    )
    if en_curso is not None:
        raise ErrorApp(409, "EVALUACION_EN_CURSO", "Ya hay una evaluación en curso.")
    version = cfg.prompt_version if cfg else VERSIONES["chat"][-1]
    e = EvaluacionIA(
        modo=datos.modo,
        canal="chat",
        campana_id=datos.campana_id,
        modelo=cfg.modelo if cfg else None,
        esfuerzo=cfg.esfuerzo if cfg else None,
        prompt_version=version,
        huella=configuracion.huella_evaluacion(version),
        patron_casos=datos.casos,
        estado="pendiente",
        resumen={},
        casos=[],
        iniciada_por=usuario.id,
        creado_en=ahora,
    )
    db.add(e)
    db.flush()
    auditoria.registrar(
        db,
        "ia.evaluacion_lanzar",
        usuario.id,
        "evaluacion",
        e.id,
        {"evaluacion_id": e.id, "modo": e.modo},
    )
    encolar(db, "ia.evaluacion", {"evaluacion_id": e.id}, max_intentos=1, ahora=ahora)
    db.commit()
    return salida(db, e)


def listar(
    db: Session, params: ParamsPaginacion, modo: str | None, campana_id: int | None
) -> Pagina[EvaluacionSalida]:
    consulta = select(EvaluacionIA)
    if modo:
        consulta = consulta.where(EvaluacionIA.modo == modo)
    if campana_id:
        consulta = consulta.where(EvaluacionIA.campana_id == campana_id)
    filas, total = paginar(db, consulta.order_by(EvaluacionIA.id.desc()), params)
    return Pagina(
        items=[salida(db, e) for e in filas],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


def ver(db: Session, evaluacion_id: int) -> EvaluacionSalida:
    e = db.get(EvaluacionIA, evaluacion_id)
    if e is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Evaluación no encontrada.")
    return salida(db, e)


def registrar_resultado(
    db: Session,
    e: EvaluacionIA,
    resultados: list[informe.ResultadoCaso],
    ahora: datetime,
) -> None:
    e.resumen = informe.agregar(resultados, e.modo)
    e.casos = [r.como_dict() for r in resultados]
    e.aprobada = informe.aprobada(resultados, e.modo)
    e.estado = "completada"
    e.completada_en = ahora


def ejecutar_evaluacion(db: Session, evaluacion_id: int, ahora: datetime) -> None:
    """Trabajo `ia.evaluacion`: mismo arnés que la CLI y los tests."""
    e = db.get(EvaluacionIA, evaluacion_id)
    if e is None or e.estado != "pendiente":
        return
    e.estado = "en_curso"
    db.commit()
    resultados: list[informe.ResultadoCaso] = []
    try:
        cliente: Any = None
        if e.modo == "online":
            from app.modulos.agente_ia.llm_anthropic import ClienteAnthropic

            s = get_settings()
            cliente = ClienteAnthropic(
                api_key=s.anthropic_api_key.get_secret_value(),
                timeout_segundos=s.ia_timeout_segundos,
            )
        resultados = harness.ejecutar_casos(
            casos_mod.cargar_casos(e.patron_casos),
            e.modo,
            cliente,
            modelo=e.modelo,
            esfuerzo=e.esfuerzo,
        )
        registrar_resultado(db, e, resultados, ahora)
    except Exception as exc:  # la evaluación no debe tumbar el worker
        db.rollback()
        e = db.get(EvaluacionIA, evaluacion_id)
        assert e is not None
        e.estado = "fallida"
        e.resumen = {"error": type(exc).__name__}
        e.completada_en = ahora
    eventos.publicar_evaluacion(db, e.id, e.estado, e.aprobada)
    if e.estado == "fallida" or e.aprobada is False:
        eventos.publicar_alerta(db, "evaluacion_fallida", "aviso", e.campana_id)
    db.commit()
