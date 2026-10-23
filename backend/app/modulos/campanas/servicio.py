from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalle
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.esquemas import CampanaActualizar, CampanaCrear, CampanaSalida
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar

TRANSICIONES = {
    ("borrador", "activa"),
    ("activa", "pausada"),
    ("pausada", "activa"),
    ("activa", "finalizada"),
    ("pausada", "finalizada"),
}


def _total_clientes_expr():
    return (
        select(func.count(CampanaCliente.id))
        .where(CampanaCliente.campana_id == Campana.id)
        .correlate(Campana)
        .scalar_subquery()
    )


def contar_clientes(db: Session, campana_id: int) -> int:
    return (
        db.scalar(
            select(func.count(CampanaCliente.id)).where(CampanaCliente.campana_id == campana_id)
        )
        or 0
    )


def a_salida(db: Session, campana: Campana, total: int | None = None) -> CampanaSalida:
    salida = CampanaSalida.model_validate(campana)
    salida.total_clientes = contar_clientes(db, campana.id) if total is None else total
    return salida


def listar(
    db: Session,
    params: ParamsPaginacion,
    usuario: Usuario,
    estado: str | None,
    tipo: str | None,
    q: str | None,
) -> tuple[list[CampanaSalida], int]:
    consulta = select(Campana, _total_clientes_expr())
    if usuario.rol == "agente":
        estado = "activa"
    if estado:
        consulta = consulta.where(Campana.estado == estado)
    if tipo:
        consulta = consulta.where(Campana.tipo == tipo)
    if q and q.strip():
        patron = (
            "%"
            + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        consulta = consulta.where(func.lower(Campana.nombre).like(patron, escape="\\"))
    consulta = consulta.order_by(Campana.creado_en.desc(), Campana.id.desc())
    filas, total = paginar(db, consulta, params, escalares=False)
    return [a_salida(db, c, t) for c, t in filas], total


def obtener(db: Session, campana_id: int, usuario: Usuario | None = None) -> Campana:
    campana = db.get(Campana, campana_id)
    if campana is None or (
        usuario is not None and usuario.rol == "agente" and campana.estado != "activa"
    ):
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    return campana


def _nombre_existe(db: Session, nombre: str, excepto_id: int | None = None) -> bool:
    consulta = select(Campana.id).where(func.lower(Campana.nombre) == nombre.lower())
    if excepto_id is not None:
        consulta = consulta.where(Campana.id != excepto_id)
    return db.scalar(consulta) is not None


def _duplicado() -> ErrorApp:
    return ErrorApp(409, "NOMBRE_DUPLICADO", "Ya existe una campaña con ese nombre.")


def crear(db: Session, datos: CampanaCrear, usuario: Usuario) -> CampanaSalida:
    if _nombre_existe(db, datos.nombre):
        raise _duplicado()
    campana = Campana(**datos.model_dump(), estado="borrador", creado_por=usuario.id)
    db.add(campana)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicado() from exc
    auditoria.registrar(
        db, "campana.crear", usuario.id, "campana", campana.id, {"tipo": campana.tipo}
    )
    db.commit()
    return a_salida(db, campana, 0)


def actualizar(
    db: Session, campana_id: int, datos: CampanaActualizar, usuario: Usuario
) -> CampanaSalida:
    campana = obtener(db, campana_id)
    cambios = datos.model_dump(exclude_unset=True)
    if campana.estado == "finalizada":
        raise ErrorApp(409, "CAMPANA_FINALIZADA", "La campaña está finalizada y no admite cambios.")

    # Campos no nulables: un null explícito se ignora.
    for campo in ("nombre", "max_intentos", "intervalo_reintento_minutos", "estado"):
        if campo in cambios and cambios[campo] is None:
            del cambios[campo]

    if "nombre" in cambios and _nombre_existe(db, cambios["nombre"], campana.id):
        raise _duplicado()

    inicio = cambios.get("fecha_inicio", campana.fecha_inicio)
    fin = cambios.get("fecha_fin", campana.fecha_fin)
    if inicio and fin and fin < inicio:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("fecha_fin", "fecha_fin no puede ser anterior a fecha_inicio.")],
        )

    estado_anterior = campana.estado
    nuevo_estado = cambios.pop("estado", None)
    cambio_estado = nuevo_estado is not None and nuevo_estado != estado_anterior
    if cambio_estado:
        if (estado_anterior, nuevo_estado) not in TRANSICIONES:
            raise ErrorApp(
                409,
                "TRANSICION_INVALIDA",
                f"No se puede pasar de '{estado_anterior}' a '{nuevo_estado}'.",
            )
        if nuevo_estado == "activa" and contar_clientes(db, campana.id) == 0:
            raise ErrorApp(
                409, "CAMPANA_SIN_CLIENTES", "No se puede activar una campaña sin clientes."
            )

    for campo, valor in cambios.items():
        setattr(campana, campo, valor)
    if cambio_estado:
        campana.estado = nuevo_estado
    if cambios:
        auditoria.registrar(
            db, "campana.actualizar", usuario.id, "campana", campana.id, {"campos": sorted(cambios)}
        )
    if cambio_estado:
        auditoria.registrar(
            db,
            "campana.estado",
            usuario.id,
            "campana",
            campana.id,
            {"de": estado_anterior, "a": nuevo_estado},
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicado() from exc
    db.refresh(campana)
    return a_salida(db, campana)


def eliminar(db: Session, campana_id: int, usuario: Usuario) -> None:
    campana = obtener(db, campana_id)
    if campana.estado != "borrador":
        raise ErrorApp(
            409, "CAMPANA_NO_ELIMINABLE", "Solo se pueden eliminar campañas en estado borrador."
        )
    # Cascada en BD (ON DELETE CASCADE) para importaciones y campana_clientes.
    db.delete(campana)
    auditoria.registrar(db, "campana.eliminar", usuario.id, "campana", campana_id)
    db.commit()
