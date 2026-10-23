from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalles_desde_pydantic
from app.modulos.auditoria import servicio as auditoria
from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento.esquemas import (
    EvaluarRespuesta,
    FestivoActualizar,
    FestivoCrear,
    GenerarFestivosRespuesta,
    MotivoSalida,
)
from app.modulos.cumplimiento.festivos import festivos_colombia
from app.modulos.cumplimiento.modelos import Festivo, PoliticaCumplimiento
from app.modulos.cumplimiento.politica import PoliticaCumplimiento as PoliticaModelo
from app.modulos.usuarios.modelos import Usuario

HORIZONTE_DIAS = 14


# ---- Políticas ---------------------------------------------------------------------------------
def politicas_activas(db: Session) -> list[PoliticaCumplimiento]:
    return list(
        db.scalars(
            select(PoliticaCumplimiento)
            .where(PoliticaCumplimiento.activa.is_(True))
            .order_by(PoliticaCumplimiento.tipo_campana)
        )
    )


def versiones(db: Session, tipo: str) -> list[PoliticaCumplimiento]:
    return list(
        db.scalars(
            select(PoliticaCumplimiento)
            .where(PoliticaCumplimiento.tipo_campana == tipo)
            .order_by(PoliticaCumplimiento.version.desc())
        )
    )


def politica_activa(db: Session, tipo: str) -> PoliticaCumplimiento:
    fila = db.scalar(
        select(PoliticaCumplimiento).where(
            PoliticaCumplimiento.tipo_campana == tipo, PoliticaCumplimiento.activa.is_(True)
        )
    )
    if fila is None:
        raise ErrorApp(409, "POLITICA_NO_CONFIGURADA", f"No hay política activa para '{tipo}'.")
    return fila


def actualizar_politica(
    db: Session, tipo: str, configuracion: Any, usuario: Usuario
) -> PoliticaCumplimiento:
    try:
        validada = PoliticaModelo.model_validate(configuracion)
    except ValidationError as exc:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            detalles_desde_pydantic(exc.errors(), prefijo="configuracion"),
        ) from exc
    ultima = db.scalar(
        select(func.max(PoliticaCumplimiento.version)).where(
            PoliticaCumplimiento.tipo_campana == tipo
        )
    )
    for anterior in db.scalars(
        select(PoliticaCumplimiento).where(
            PoliticaCumplimiento.tipo_campana == tipo, PoliticaCumplimiento.activa.is_(True)
        )
    ):
        anterior.activa = False
    nueva = PoliticaCumplimiento(
        tipo_campana=tipo,
        version=(ultima or 0) + 1,
        configuracion=validada.model_dump(mode="json"),
        activa=True,
        creado_por=usuario.id,
    )
    db.add(nueva)
    db.flush()
    auditoria.registrar(
        db, "politica.actualizar", usuario.id, "politica", nueva.id,
        {"tipo_campana": tipo, "version": nueva.version},
    )  # fmt: skip
    db.commit()
    return nueva


# ---- Festivos ----------------------------------------------------------------------------------
def listar_festivos(db: Session, anio: int) -> list[Festivo]:
    return list(
        db.scalars(
            select(Festivo)
            .where(Festivo.fecha >= date(anio, 1, 1), Festivo.fecha <= date(anio, 12, 31))
            .order_by(Festivo.fecha)
        )
    )


def generar_festivos(
    db: Session, anio: int, usuario_id: int | None = None, confirmar: bool = True
) -> GenerarFestivosRespuesta:
    """Idempotente: no modifica fechas ya existentes (manuales, calculadas o desactivadas)."""
    calculados = festivos_colombia(anio)
    existentes_fechas = set(
        db.scalars(
            select(Festivo.fecha).where(
                Festivo.fecha >= date(anio, 1, 1), Festivo.fecha <= date(anio, 12, 31)
            )
        )
    )
    creados = 0
    for fecha, nombre in calculados.items():
        if fecha in existentes_fechas:
            continue
        db.add(Festivo(fecha=fecha, nombre=nombre, origen="calculado", activo=True))
        creados += 1
    auditoria.registrar(
        db, "festivos.generar", usuario_id, "festivo", None,
        {"anio": anio, "creados": creados, "existentes": len(calculados) - creados},
    )  # fmt: skip
    if confirmar:
        db.commit()
    return GenerarFestivosRespuesta(
        anio=anio, creados=creados, existentes=len(calculados) - creados
    )


def crear_festivo(db: Session, datos: FestivoCrear, usuario: Usuario) -> Festivo:
    duplicado = ErrorApp(409, "FESTIVO_DUPLICADO", "Ya existe un festivo en esa fecha.")
    if db.scalar(select(Festivo.id).where(Festivo.fecha == datos.fecha)):
        raise duplicado
    festivo = Festivo(fecha=datos.fecha, nombre=datos.nombre, origen="manual", activo=True)
    db.add(festivo)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise duplicado from exc
    auditoria.registrar(
        db, "festivo.crear", usuario.id, "festivo", festivo.id, {"fecha": datos.fecha.isoformat()}
    )
    db.commit()
    return festivo


def actualizar_festivo(
    db: Session, festivo_id: int, datos: FestivoActualizar, usuario: Usuario
) -> Festivo:
    festivo = db.get(Festivo, festivo_id)
    if festivo is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Festivo no encontrado.")
    cambios = {k: v for k, v in datos.model_dump(exclude_unset=True).items() if v is not None}
    for campo, valor in cambios.items():
        setattr(festivo, campo, valor)
    auditoria.registrar(
        db, "festivo.actualizar", usuario.id, "festivo", festivo.id, {"campos": sorted(cambios)}
    )
    db.commit()
    return festivo


# ---- Evaluación --------------------------------------------------------------------------------
def evaluar(db: Session, tipo: str, momento: datetime | None) -> EvaluarRespuesta:
    fila = politica_activa(db, tipo)
    politica = PoliticaModelo.model_validate(fila.configuracion)
    momento = momento or datetime.now(UTC)
    desde = momento.astimezone(UTC).date() - timedelta(days=1)
    hasta = desde + timedelta(days=HORIZONTE_DIAS + 3)
    festivos = {
        f: n
        for f, n in db.execute(
            select(Festivo.fecha, Festivo.nombre).where(
                Festivo.activo.is_(True), Festivo.fecha >= desde, Festivo.fecha <= hasta
            )
        )
    }
    resultado = motor.evaluar_horario(momento, politica, festivos)
    return EvaluarRespuesta(
        permitido=resultado.permitido,
        motivos=[MotivoSalida(codigo=m.codigo, mensaje=m.mensaje) for m in resultado.motivos],
        momento_local=resultado.momento_local.isoformat(),
        proxima_ventana_inicio=(
            resultado.proxima_ventana_inicio.isoformat()
            if resultado.proxima_ventana_inicio
            else None
        ),
        politica_version=fila.version,
    )
