from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errores import ErrorApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.usuarios.esquemas import UsuarioActualizar, UsuarioCrear
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar
from app.seguridad import hash_password


def listar(
    db: Session, params: ParamsPaginacion, rol: str | None, activo: bool | None
) -> tuple[list[Usuario], int]:
    consulta = select(Usuario)
    if rol:
        consulta = consulta.where(Usuario.rol == rol)
    if activo is not None:
        consulta = consulta.where(Usuario.activo == activo)
    return paginar(db, consulta.order_by(Usuario.nombre, Usuario.id), params)


def obtener(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Usuario no encontrado.")
    return usuario


def obtener_por_email(db: Session, email: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.email == email.lower()))


def crear(
    db: Session, datos: UsuarioCrear, actor_id: int | None, origen: str | None = None
) -> Usuario:
    if obtener_por_email(db, datos.email) is not None:
        raise ErrorApp(409, "EMAIL_DUPLICADO", "Ya existe un usuario con ese email.")
    usuario = Usuario(
        email=datos.email.lower(),
        nombre=datos.nombre,
        rol=datos.rol,
        password_hash=hash_password(datos.password),
        activo=True,
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorApp(409, "EMAIL_DUPLICADO", "Ya existe un usuario con ese email.") from exc
    detalle = {"rol": usuario.rol}
    if origen:
        detalle["origen"] = origen
    auditoria.registrar(db, "usuario.crear", actor_id, "usuario", usuario.id, detalle)
    db.commit()
    return usuario


def actualizar(db: Session, usuario_id: int, datos: UsuarioActualizar, actor: Usuario) -> Usuario:
    usuario = obtener(db, usuario_id)
    cambios = datos.model_dump(exclude_unset=True)
    if usuario.id == actor.id:
        if cambios.get("activo") is False:
            raise ErrorApp(409, "NO_PUEDE_DESACTIVARSE", "No puede desactivarse a sí mismo.")
        if "rol" in cambios and cambios["rol"] != "administrador":
            raise ErrorApp(
                409, "NO_PUEDE_DESACTIVARSE", "No puede quitarse el rol de administrador."
            )
    campos = []
    for campo, valor in cambios.items():
        if valor is None:
            continue
        if campo == "password":
            usuario.password_hash = hash_password(valor)
        else:
            setattr(usuario, campo, valor)
        campos.append(campo)
    auditoria.registrar(
        db, "usuario.actualizar", actor.id, "usuario", usuario.id, {"campos": sorted(campos)}
    )
    db.commit()
    return usuario
