from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalles_desde_pydantic
from app.modulos.auditoria import servicio as auditoria
from app.modulos.clientes.modelos import Cliente
from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento.esquemas import (
    EvaluarRespuesta,
    FestivoActualizar,
    FestivoCrear,
    GenerarFestivosRespuesta,
    MotivoSalida,
)
from app.modulos.cumplimiento.festivos import festivos_colombia
from app.modulos.cumplimiento.frecuencia import Canal, IntentoPrevio
from app.modulos.cumplimiento.modelos import Festivo, IntentoContacto, PoliticaCumplimiento
from app.modulos.cumplimiento.motor import ResultadoEvaluacion
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
    try:
        db.flush()
        auditoria.registrar(
            db, "politica.actualizar", usuario.id, "politica", nueva.id,
            {"tipo_campana": tipo, "version": nueva.version},
        )  # fmt: skip
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorApp(
            409, "POLITICA_CONCURRENTE", "Otra actualización de la política ocurrió a la vez."
        ) from exc
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
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise ErrorApp(
                409, "FESTIVOS_CONCURRENTE", "Otra operación generó los festivos; reintente."
            ) from exc
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
def cargar_festivos(db: Session, momento: datetime, politica: PoliticaModelo) -> dict[date, str]:
    local = momento.astimezone(ZoneInfo(politica.zona_horaria))
    desde = local.date() - timedelta(days=1)
    hasta = desde + timedelta(days=HORIZONTE_DIAS + 3)
    festivos = {
        f: n
        for f, n in db.execute(
            select(Festivo.fecha, Festivo.nombre).where(
                Festivo.activo.is_(True), Festivo.fecha >= desde, Festivo.fecha <= hasta
            )
        )
    }
    # Respaldo: si la tabla no tiene NINGÚN festivo calculado (activo o no) para un año de la
    # ventana, se usan los calculados de ese año. Los manuales y los calculados desactivados
    # se respetan tal cual.
    for anio in sorted({desde.year, hasta.year}):
        hay_filas = db.scalar(
            select(Festivo.id)
            .where(
                Festivo.fecha >= date(anio, 1, 1),
                Festivo.fecha <= date(anio, 12, 31),
                Festivo.origen == "calculado",
            )
            .limit(1)
        )
        if hay_filas is None:
            try:
                calculados = festivos_colombia(anio)
            except ValueError:
                continue
            for f, n in calculados.items():
                if desde <= f <= hasta:
                    festivos.setdefault(f, n)
    return festivos


def cargar_politica(db: Session, tipo: str) -> tuple[PoliticaModelo, int]:
    fila = politica_activa(db, tipo)
    return PoliticaModelo.model_validate(fila.configuracion), fila.version


def historial_cliente(
    db: Session, cliente_id: int, tipo_campana: str, desde: datetime, hasta: datetime
) -> list[IntentoPrevio]:
    """Intentos del cliente en campañas del MISMO tipo con `momento` en [desde, hasta]."""
    filas = db.scalars(
        select(IntentoContacto)
        .where(
            IntentoContacto.cliente_id == cliente_id,
            IntentoContacto.tipo_campana == tipo_campana,
            IntentoContacto.momento >= desde,
            IntentoContacto.momento <= hasta,
        )
        .order_by(IntentoContacto.momento)
    )
    return [
        IntentoPrevio(
            momento=f.momento,
            canal=f.canal,  # type: ignore[arg-type]
            iniciado_por=f.iniciado_por,  # type: ignore[arg-type]
            contacto_directo=f.contacto_directo,
        )
        for f in filas
    ]


def evaluar_para_cliente(
    db: Session,
    cliente_id: int,
    tipo_campana: str,
    canal: Canal,
    momento: datetime,
    entrante: bool = False,
) -> tuple[ResultadoEvaluacion, int]:
    """Horario + frecuencia con el historial real del cliente. Devuelve (resultado, versión)."""
    politica, version = cargar_politica(db, tipo_campana)
    zona = ZoneInfo(politica.zona_horaria)
    local = motor._a_local(momento, politica)
    lunes = datetime.combine(
        local.date() - timedelta(days=local.weekday()), datetime.min.time(), tzinfo=zona
    )
    historial = historial_cliente(db, cliente_id, tipo_campana, lunes - timedelta(days=8), momento)
    festivos = cargar_festivos(db, momento, politica)
    resultado = motor.evaluar_contacto(
        momento, canal, politica, festivos, historial, entrante=entrante
    )
    return resultado, version


def registrar_intento(
    db: Session,
    *,
    cliente_id: int,
    tipo_campana: str,
    canal: Canal,
    iniciado_por: str,
    momento: datetime,
    campana_id: int | None = None,
    campana_cliente_id: int | None = None,
    telefono_id: int | None = None,
    contacto_directo: bool = False,
    resultado: str | None = None,
    politica_version: int | None = None,
) -> IntentoContacto:
    """Único punto de escritura de `intentos_contacto`. No hace commit."""
    intento = IntentoContacto(
        cliente_id=cliente_id,
        campana_id=campana_id,
        campana_cliente_id=campana_cliente_id,
        tipo_campana=tipo_campana,
        canal=canal,
        iniciado_por=iniciado_por,
        telefono_id=telefono_id,
        momento=momento,
        contacto_directo=contacto_directo,
        resultado=resultado,
        politica_version=politica_version,
    )
    db.add(intento)
    db.flush()
    return intento


def evaluar(
    db: Session,
    tipo: str,
    momento: datetime | None,
    canal: Canal = "voz",
    cliente_id: int | None = None,
) -> EvaluarRespuesta:
    momento = momento or datetime.now(UTC)
    if cliente_id is not None:
        if db.get(Cliente, cliente_id) is None:
            raise ErrorApp(404, "NO_ENCONTRADO", "Cliente no encontrado.")
        resultado, version = evaluar_para_cliente(db, cliente_id, tipo, canal, momento)
    else:
        politica, version = cargar_politica(db, tipo)
        festivos = cargar_festivos(db, momento, politica)
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
        politica_version=version,
    )
