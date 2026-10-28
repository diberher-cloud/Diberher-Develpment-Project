"""Opt-in (autorizaciones por canal y finalidad) y opt-out (ADR-0012, fase-2b.md §4.10)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.auditoria import servicio as auditoria
from app.modulos.consola.servicio import enmascarar_telefono
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.esquemas import UsuarioRef
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.telefonos import ErrorTelefono, normalizar_telefono
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp.esquemas import AutorizacionCrear, AutorizacionSalida
from app.modulos.whatsapp.modelos import AutorizacionCanal
from app.modulos.whatsapp.ventana import ventana_abierta
from app.paginacion import ParamsPaginacion, paginar


def clave_vigente(numero: str, finalidad: str) -> str:
    return f"{numero}|whatsapp|{finalidad}"


# ---- Opt-out -----------------------------------------------------------------------------------
def revocar_vigentes(
    db: Session,
    numero: str,
    ahora: datetime,
    motivo: str,
    por: int | None,
    finalidades: tuple[str, ...] | None = None,
) -> int:
    consulta = select(AutorizacionCanal).where(
        AutorizacionCanal.numero_e164 == numero, AutorizacionCanal.clave_vigente.is_not(None)
    )
    if finalidades is not None:
        consulta = consulta.where(AutorizacionCanal.finalidad.in_(finalidades))
    n = 0
    for a in db.scalars(consulta):
        a.revocada_en = ahora
        a.revocada_por = por
        a.motivo_revocacion = motivo
        a.clave_vigente = None
        n += 1
    return n


def _exclusion_equivalente(db: Session, numero: str, alcance: str) -> bool:
    canales = ("todos",) if alcance == "todos" else ("todos", "whatsapp")
    return (
        db.scalar(
            select(Exclusion.id)
            .where(
                Exclusion.numero_e164 == numero,
                Exclusion.aplica_a == "todas",
                Exclusion.canal.in_(canales),
            )
            .limit(1)
        )
        is not None
    )


def aplicar_opt_out(
    db: Session,
    conv: Conversacion,
    alcance: str,
    *,
    origen: str,
    usuario_id: int | None,
    ahora: datetime,
) -> None:
    """Servicio único de opt-out (entrante determinista y endpoint manual). Sin commit.

    `origen`: `determinista` (exclusión `origen=sistema`) o `agente` (`origen=usuario`)."""
    from app.modulos.whatsapp import servicio_envio

    settings = get_settings()
    numero = conv.numero_cliente_e164
    if not _exclusion_equivalente(db, numero, alcance):
        try:
            with db.begin_nested():
                db.add(
                    Exclusion(
                        numero_e164=numero,
                        motivo="solicitud_titular",
                        aplica_a="todas",
                        canal=alcance,
                        origen="sistema" if origen == "determinista" else "usuario",
                        creado_por=None if origen == "determinista" else usuario_id,
                        conversacion_id=conv.id,
                        creado_en=ahora,
                    )
                )
                db.flush()
        except IntegrityError:  # otra transacción creó la misma exclusión
            pass
        else:
            auditoria.registrar(
                db,
                "exclusion.crear",
                usuario_id,
                "exclusion",
                None,
                {"motivo": "solicitud_titular", "aplica_a": "todas", "canal": alcance},
            )
    revocar_vigentes(db, numero, ahora, "opt_out", usuario_id)
    conversaciones.cancelar_pendientes(db, conv.id)
    texto = (
        settings.whatsapp_mensaje_opt_out_todos
        if alcance == "todos"
        else settings.whatsapp_mensaje_opt_out
    )
    if texto and ventana_abierta(conv, ahora, conversaciones.margen_ventana()):
        servicio_envio.crear_automatico(db, conv, texto, ahora)
    conversaciones.cerrar(db, conv, "opt_out", usuario_id, ahora, cancelar=False)
    auditoria.registrar(
        db,
        "whatsapp.opt_out",
        usuario_id,
        "conversacion",
        conv.id,
        {"conversacion_id": conv.id, "alcance": alcance, "origen": origen},
    )


def opt_out_manual(
    db: Session, usuario: Usuario, conversacion_id: int, alcance: str, ahora: datetime
) -> Conversacion:
    conversaciones.cargar(db, conversacion_id)
    conv = conversaciones.bloquear(db, conversacion_id)
    conversaciones.exigir_dueno(conv, usuario)
    conversaciones.exigir_abierta(conv)
    aplicar_opt_out(db, conv, alcance, origen="agente", usuario_id=usuario.id, ahora=ahora)
    db.commit()
    return conv


# ---- Autorizaciones ----------------------------------------------------------------------------
def a_salida(db: Session, a: AutorizacionCanal, usuario: Usuario) -> AutorizacionSalida:
    registrada = None
    if a.registrada_por is not None:
        u = db.get(Usuario, a.registrada_por)
        registrada = UsuarioRef(id=u.id, nombre=u.nombre) if u else None
    return AutorizacionSalida(
        id=a.id,
        numero_mascara=enmascarar_telefono(a.numero_e164),
        numero_e164=a.numero_e164 if usuario.rol in ("administrador", "supervisor") else None,
        canal="whatsapp",
        finalidad=a.finalidad,  # type: ignore[arg-type]
        origen=a.origen,  # type: ignore[arg-type]
        evidencia=a.evidencia,
        otorgada_en=a.otorgada_en,
        vigente=a.clave_vigente is not None,
        revocada_en=a.revocada_en,
        motivo_revocacion=a.motivo_revocacion,  # type: ignore[arg-type]
        registrada_por=registrada,
    )


def listar(
    db: Session,
    usuario: Usuario,
    params: ParamsPaginacion,
    numero: str | None,
    finalidad: str | None,
    vigentes: bool | None,
) -> tuple[list[AutorizacionSalida], int]:
    consulta = select(AutorizacionCanal)
    if numero and numero.strip():
        try:
            consulta = consulta.where(
                AutorizacionCanal.numero_e164 == normalizar_telefono(numero).numero_e164
            )
        except ErrorTelefono:
            return [], 0
    if finalidad:
        consulta = consulta.where(AutorizacionCanal.finalidad == finalidad)
    if vigentes is True:
        consulta = consulta.where(AutorizacionCanal.clave_vigente.is_not(None))
    elif vigentes is False:
        consulta = consulta.where(AutorizacionCanal.clave_vigente.is_(None))
    filas, total = paginar(db, consulta.order_by(AutorizacionCanal.id.desc()), params)
    return [a_salida(db, a, usuario) for a in filas], total


def _duplicada() -> ErrorApp:
    return ErrorApp(
        409, "AUTORIZACION_DUPLICADA", "Ya existe una autorización vigente para esa finalidad."
    )


def _alta(
    db: Session,
    *,
    numero: str,
    finalidad: str,
    origen: str,
    evidencia: str,
    otorgada_en: datetime,
    usuario_id: int | None,
    ahora: datetime,
    conversacion_id: int | None = None,
    importacion_id: int | None = None,
) -> AutorizacionCanal:
    """Inserta la autorización vigente; 409 `AUTORIZACION_DUPLICADA` si ya existe."""
    clave = clave_vigente(numero, finalidad)
    if db.scalar(select(AutorizacionCanal.id).where(AutorizacionCanal.clave_vigente == clave)):
        raise _duplicada()
    a = AutorizacionCanal(
        numero_e164=numero,
        canal="whatsapp",
        finalidad=finalidad,
        origen=origen,
        evidencia=evidencia,
        otorgada_en=otorgada_en,
        registrada_por=usuario_id,
        importacion_id=importacion_id,
        conversacion_id=conversacion_id,
        clave_vigente=clave,
        creado_en=ahora,
    )
    try:
        with db.begin_nested():
            db.add(a)
            db.flush()
    except IntegrityError:
        raise _duplicada() from None
    return a


def crear(
    db: Session, usuario: Usuario, datos: AutorizacionCrear, ahora: datetime
) -> AutorizacionSalida:
    try:
        tel = normalizar_telefono(datos.telefono)
    except ErrorTelefono as exc:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("telefono", f"{exc.codigo}: {exc.mensaje}")],
        ) from exc
    if tel.tipo_linea != "movil":
        raise ErrorApp(
            422,
            "TELEFONO_NO_VALIDO",
            "WhatsApp solo aplica a números móviles.",
            [detalle("telefono", "Debe ser un número móvil.")],
        )
    otorgada = datos.otorgada_en or ahora
    if otorgada > ahora:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("otorgada_en", "No puede ser una fecha futura.")],
        )
    a = _alta(
        db,
        numero=tel.numero_e164,
        finalidad=datos.finalidad,
        origen="agente",
        evidencia=datos.evidencia,
        otorgada_en=otorgada,
        usuario_id=usuario.id,
        ahora=ahora,
    )
    auditoria.registrar(
        db,
        "autorizacion.crear",
        usuario.id,
        "autorizacion",
        a.id,
        {"autorizacion_id": a.id, "finalidad": a.finalidad, "origen": a.origen},
    )
    db.commit()
    return a_salida(db, a, usuario)


def crear_desde_conversacion(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    finalidad: str,
    evidencia: str,
    ahora: datetime,
) -> AutorizacionSalida:
    conversaciones.cargar(db, conversacion_id)
    conv = conversaciones.bloquear(db, conversacion_id)
    conversaciones.exigir_dueno(conv, usuario)
    a = _alta(
        db,
        numero=conv.numero_cliente_e164,
        finalidad=finalidad,
        origen="cliente",
        evidencia=evidencia,
        otorgada_en=ahora,
        usuario_id=usuario.id,
        ahora=ahora,
        conversacion_id=conv.id,
    )
    auditoria.registrar(
        db,
        "autorizacion.crear",
        usuario.id,
        "autorizacion",
        a.id,
        {"autorizacion_id": a.id, "finalidad": a.finalidad, "origen": a.origen},
    )
    db.commit()
    return a_salida(db, a, usuario)


def revocar(db: Session, usuario: Usuario, autorizacion_id: int, ahora: datetime) -> None:
    a = db.get(AutorizacionCanal, autorizacion_id)
    if a is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Autorización no encontrada.")
    if a.revocada_en is not None:
        return
    a.revocada_en = ahora
    a.revocada_por = usuario.id
    a.motivo_revocacion = "manual"
    a.clave_vigente = None
    auditoria.registrar(
        db,
        "autorizacion.revocar",
        usuario.id,
        "autorizacion",
        a.id,
        {"autorizacion_id": a.id, "finalidad": a.finalidad},
    )
    db.commit()


# ---- Importación -------------------------------------------------------------------------------
def alta_importacion(
    db: Session,
    *,
    numero: str,
    finalidad: str,
    otorgada_en: datetime,
    importacion_id: int,
    fila: int,
    ahora: datetime,
) -> bool:
    """Autorización de una fila importada. False si ya había una vigente igual. Sin commit."""
    clave = clave_vigente(numero, finalidad)
    if db.scalar(select(AutorizacionCanal.id).where(AutorizacionCanal.clave_vigente == clave)):
        return False
    db.add(
        AutorizacionCanal(
            numero_e164=numero,
            canal="whatsapp",
            finalidad=finalidad,
            origen="importacion",
            evidencia=f"importacion:{importacion_id} fila {fila}",
            otorgada_en=otorgada_en,
            importacion_id=importacion_id,
            clave_vigente=clave,
            creado_en=ahora,
        )
    )
    return True
