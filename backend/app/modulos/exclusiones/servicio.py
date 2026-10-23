from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.auditoria import servicio as auditoria
from app.modulos.exclusiones.esquemas import ExclusionCrear, resolver_aplica_a
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.lector_csv import ErrorLector, leer_csv
from app.modulos.importacion.servicio import a_error_app
from app.modulos.importacion.telefonos import ErrorTelefono, enmascarar, normalizar_telefono
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar

MAX_ERRORES = 100


def _error_telefono(exc: ErrorTelefono) -> ErrorApp:
    return ErrorApp(
        422,
        "VALIDACION",
        "Los datos enviados no son válidos.",
        [detalle("telefono", f"{exc.codigo}: {exc.mensaje}")],
    )


def listar(
    db: Session,
    params: ParamsPaginacion,
    q: str | None,
    motivo: str | None,
    aplica_a: str | None,
) -> tuple[list[Exclusion], int]:
    consulta = select(Exclusion)
    if q and q.strip():
        try:
            consulta = consulta.where(Exclusion.numero_e164 == normalizar_telefono(q).numero_e164)
        except ErrorTelefono:
            return [], 0
    if motivo:
        consulta = consulta.where(Exclusion.motivo == motivo)
    if aplica_a:
        consulta = consulta.where(Exclusion.aplica_a == aplica_a)
    return paginar(db, consulta.order_by(Exclusion.id.desc()), params)


def crear(db: Session, datos: ExclusionCrear, usuario: Usuario) -> Exclusion:
    try:
        numero = normalizar_telefono(datos.telefono).numero_e164
    except ErrorTelefono as exc:
        raise _error_telefono(exc) from exc
    aplica_a = resolver_aplica_a(datos.motivo, datos.aplica_a)
    duplicada = ErrorApp(
        409, "EXCLUSION_DUPLICADA", "El número ya está excluido para esa finalidad."
    )
    if db.scalar(
        select(Exclusion.id).where(Exclusion.numero_e164 == numero, Exclusion.aplica_a == aplica_a)
    ):
        raise duplicada
    exclusion = Exclusion(
        numero_e164=numero,
        motivo=datos.motivo,
        aplica_a=aplica_a,
        observacion=(datos.observacion or None),
        creado_por=usuario.id,
    )
    db.add(exclusion)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise duplicada from exc
    auditoria.registrar(
        db, "exclusion.crear", usuario.id, "exclusion", exclusion.id,
        {"motivo": datos.motivo, "aplica_a": aplica_a},
    )  # fmt: skip
    db.commit()
    return exclusion


def eliminar(db: Session, exclusion_id: int, usuario: Usuario) -> None:
    exclusion = db.get(Exclusion, exclusion_id)
    if exclusion is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Exclusión no encontrada.")
    detalle_aud = {"motivo": exclusion.motivo, "aplica_a": exclusion.aplica_a}
    db.delete(exclusion)
    auditoria.registrar(
        db, "exclusion.eliminar", usuario.id, "exclusion", exclusion_id, detalle_aud
    )
    db.commit()


def importar(
    db: Session, usuario: Usuario, contenido: bytes, motivo: str, aplica_a_in: str | None
) -> dict:
    aplica_a = resolver_aplica_a(motivo, aplica_a_in)
    try:
        archivo = leer_csv(contenido, get_settings().exclusiones_max_filas, ("telefono",))
    except ErrorLector as exc:
        raise a_error_app(exc) from exc

    try:
        existentes = set(
            db.scalars(select(Exclusion.numero_e164).where(Exclusion.aplica_a == aplica_a))
        )
        nuevas: list[Exclusion] = []
        errores: list[dict] = []
        total_errores = 0
        duplicadas = invalidas = 0
        for fila in archivo.filas:
            crudo = fila.valores.get("telefono", "")
            try:
                numero = normalizar_telefono(crudo).numero_e164
            except ErrorTelefono as exc:
                invalidas += 1
                total_errores += 1
                if len(errores) < MAX_ERRORES:
                    rotulo = {
                        "TELEFONO_REQUERIDO": "Teléfono obligatorio",
                        "TELEFONO_INVALIDO": "Teléfono inválido",
                        "TELEFONO_NO_COLOMBIANO": "Teléfono no colombiano",
                        "TELEFONO_TIPO_NO_PERMITIDO": "Tipo de línea no permitido",
                    }[exc.codigo]
                    mensaje = (
                        f"{rotulo} ({enmascarar(crudo)})."
                        if exc.codigo != "TELEFONO_REQUERIDO"
                        else f"{rotulo}."
                    )
                    errores.append(
                        {
                            "fila": fila.numero,
                            "campo": "telefono",
                            "codigo": exc.codigo,
                            "mensaje": mensaje,
                            "severidad": "error",
                        }
                    )
                continue
            if numero in existentes:
                duplicadas += 1
                continue
            existentes.add(numero)
            nuevas.append(
                Exclusion(
                    numero_e164=numero, motivo=motivo, aplica_a=aplica_a, creado_por=usuario.id
                )
            )
        db.add_all(nuevas)
        auditoria.registrar(
            db, "exclusion.importar", usuario.id, "exclusion", None,
            {
                "motivo": motivo,
                "aplica_a": aplica_a,
                "total_filas": len(archivo.filas),
                "creadas": len(nuevas),
                "duplicadas": duplicadas,
                "invalidas": invalidas,
            },
        )  # fmt: skip
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "total_filas": len(archivo.filas),
        "creadas": len(nuevas),
        "duplicadas": duplicadas,
        "invalidas": invalidas,
        "errores": errores,
        "errores_truncados": total_errores > len(errores),
    }
