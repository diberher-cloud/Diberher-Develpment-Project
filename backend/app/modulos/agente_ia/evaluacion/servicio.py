"""Evaluaciones registradas en `evaluaciones_ia` y trabajo `ia.evaluacion` (fase-2c.md §6.9)."""

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.agente_ia import configuracion, eventos
from app.modulos.agente_ia.esquemas import EvaluacionCrear
from app.modulos.agente_ia.esquemas import EvaluacionIA as EvaluacionSalida
from app.modulos.agente_ia.evaluacion import informe
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, EvaluacionIA
from app.modulos.agente_ia.prompts import VERSIONES
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.conversaciones.esquemas import UsuarioRef
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import Pagina, ParamsPaginacion, paginar
from app.trabajos.cola import encolar
from app.trabajos.registro import ReprogramarTrabajo

SONDEO_SEGUNDOS = 3


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
        resumen={k: v for k, v in (e.resumen or {}).items() if not k.startswith("_")},
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


def _ruta_informe(evaluacion_id: int) -> Path:
    return Path(tempfile.gettempdir()) / f"evaluacion_ia_{evaluacion_id}.json"


def _lanzar(e: EvaluacionIA) -> int:
    """Lanza `python -m app.evaluacion_ia` en un PROCESO APARTE: la evaluación usa su propia BD
    SQLite en memoria y sustituye globales (bus, proveedor de WhatsApp, cliente de IA) que no
    deben tocar los del worker. Devuelve el pid."""
    salida = _ruta_informe(e.id)
    salida.unlink(missing_ok=True)
    orden = [sys.executable, "-m", "app.evaluacion_ia", "--salida", str(salida)]
    if e.modo == "online":
        orden.append("--real")
    if e.patron_casos:
        orden += ["--casos", e.patron_casos]
    if e.modelo:
        orden += ["--modelo", e.modelo]
    if e.esfuerzo:
        orden += ["--esfuerzo", e.esfuerzo]
    proceso = subprocess.Popen(  # noqa: S603  (argumentos fijos; el patrón viaja como un argumento)
        orden,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(os.environ),
        start_new_session=True,
    )
    return proceso.pid


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        # un proceso terminado y no recogido (zombi) sigue "existiendo": se recoge si es hijo
        try:
            terminado, _ = os.waitpid(pid, os.WNOHANG)
            return terminado == 0
        except ChildProcessError:
            return True
    except OSError:
        return False


def _fallar(e: EvaluacionIA, motivo: str, ahora: datetime) -> None:
    e.estado = "fallida"
    e.resumen = {"error": motivo}
    e.completada_en = ahora


def ejecutar_evaluacion(db: Session, evaluacion_id: int, ahora: datetime) -> None:
    """Trabajo `ia.evaluacion`, sin bloquear la cola: la primera vez lanza el subproceso y
    reprograma el trabajo; cada vuelta comprueba si terminó (o venció el
    `IA_EVALUACION_TIMEOUT_SEGUNDOS`: se mata). No se repite por bloqueo caducado
    (`max_intentos=1`; un gancho `AL_AGOTAR` la marca fallida)."""
    e = db.get(EvaluacionIA, evaluacion_id)
    if e is None or e.estado in ("completada", "fallida"):
        return
    timeout = get_settings().ia_evaluacion_timeout_segundos
    informe_ruta = _ruta_informe(e.id)
    if e.estado == "pendiente":
        e.estado = "en_curso"
        e.resumen = {"_proceso": {"pid": _lanzar(e), "desde": ahora.isoformat()}}
        db.commit()
        raise ReprogramarTrabajo(ahora + timedelta(seconds=SONDEO_SEGUNDOS))
    proceso = (e.resumen or {}).get("_proceso") or {}
    pid = int(proceso.get("pid", 0))
    if informe_ruta.exists() and not _vivo(pid):
        try:
            datos = json.loads(informe_ruta.read_text(encoding="utf-8"))
            e.resumen = datos["resumen"]
            e.casos = datos["casos"]
            e.aprobada = bool(datos["aprobada"])
            e.estado = "completada"
            e.completada_en = ahora
        except (ValueError, KeyError):
            _fallar(e, "INFORME_INVALIDO", ahora)
        informe_ruta.unlink(missing_ok=True)
    elif not _vivo(pid):
        _fallar(e, "PROCESO_TERMINADO_SIN_INFORME", ahora)
    else:
        desde = datetime.fromisoformat(proceso["desde"])
        if (ahora - desde).total_seconds() > timeout:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)
            _fallar(e, "TIMEOUT", ahora)
        else:
            db.commit()
            raise ReprogramarTrabajo(ahora + timedelta(seconds=SONDEO_SEGUNDOS))
    eventos.publicar_evaluacion(db, e.id, e.estado, e.aprobada)
    if e.estado == "fallida" or e.aprobada is False:
        eventos.publicar_alerta(db, "evaluacion_fallida", "aviso", e.campana_id)
    db.commit()


def evaluacion_agotada(db: Session, payload: dict, codigo: str, ahora: datetime) -> None:
    """Gancho: el trabajo se agotó (worker caído, bloqueo caducado): `fallida`, sin reintento."""
    e = db.get(EvaluacionIA, int(payload.get("evaluacion_id", 0)))
    if e is not None and e.estado in ("pendiente", "en_curso"):
        pid = int(((e.resumen or {}).get("_proceso") or {}).get("pid", 0))
        if pid:
            with contextlib.suppress(OSError):
                os.killpg(pid, signal.SIGKILL)
        _fallar(e, codigo, ahora)
        eventos.publicar_evaluacion(db, e.id, e.estado, e.aprobada)
