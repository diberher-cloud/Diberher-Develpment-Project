"""Construcción de las salidas de la API de conversaciones y mensajes (§4.8)."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import Cliente
from app.modulos.consola.esquemas import MotivoSalida
from app.modulos.consola.modelos import Tipificacion
from app.modulos.consola.servicio import enmascarar_telefono
from app.modulos.conversaciones import servicio
from app.modulos.conversaciones.esquemas import (
    BotonMensaje,
    CampanaRef,
    ConversacionResumen,
    ErrorMensaje,
    MediaMensaje,
    PlantillaRef,
    UsuarioRef,
)
from app.modulos.conversaciones.esquemas import (
    Conversacion as ConversacionSalida,
)
from app.modulos.conversaciones.esquemas import (
    Mensaje as MensajeSalida,
)
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.conversaciones.resolucion import candidatos
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import cumplimiento as cumplimiento_wa
from app.modulos.whatsapp.modelos import PlantillaWhatsApp
from app.modulos.whatsapp.ventana import ventana_abierta

_ERRORES = {
    "63016": "Fuera de la ventana de 24 h.",
    "63003": "El número no está disponible en WhatsApp.",
    "VENTANA_CERRADA": "La ventana de 24 h se cerró antes de enviar.",
    "CLIENTE_OPT_OUT": "El cliente pidió no recibir mensajes.",
    "CONTACTO_NO_PERMITIDO": "El contacto ya no está permitido (exclusión o sin autorización).",
    "FUERA_DE_FRANJA": "La plantilla ya no se podía enviar: fuera de la franja horaria.",
    "PLANTILLA_NO_ENVIABLE": "La plantilla dejó de estar disponible antes de enviarse.",
    "ENVIO_INCIERTO": "No se pudo confirmar el envío; revise antes de reenviar.",
    "RESPUESTA_FUERA_DE_FRANJA": "La respuesta quedó fuera de la franja horaria permitida.",
}


def mensaje_de_error(codigo: str) -> str:
    return _ERRORES.get(codigo, f"Error del proveedor ({codigo}).")


def _usuarios(db: Session, ids: Iterable[int | None]) -> dict[int, UsuarioRef]:
    unicos = {i for i in ids if i is not None}
    if not unicos:
        return {}
    return {
        u.id: UsuarioRef(id=u.id, nombre=u.nombre)
        for u in db.scalars(select(Usuario).where(Usuario.id.in_(unicos)))
    }


# ---- Mensajes ----------------------------------------------------------------------------------
def mensajes_salida(db: Session, mensajes: list[Mensaje]) -> list[MensajeSalida]:
    usuarios = _usuarios(db, (m.usuario_id for m in mensajes))
    plantilla_ids = {m.plantilla_id for m in mensajes if m.plantilla_id is not None}
    plantillas: dict[int, PlantillaRef] = {}
    if plantilla_ids:
        plantillas = {
            p.id: PlantillaRef(id=p.id, nombre=p.nombre)
            for p in db.scalars(
                select(PlantillaWhatsApp).where(PlantillaWhatsApp.id.in_(plantilla_ids))
            )
        }
    return [
        MensajeSalida(
            id=m.id,
            conversacion_id=m.conversacion_id or 0,
            direccion=m.direccion,  # type: ignore[arg-type]
            autor=m.autor,  # type: ignore[arg-type]
            usuario=usuarios.get(m.usuario_id) if m.usuario_id is not None else None,
            tipo=m.tipo,  # type: ignore[arg-type]
            cuerpo=m.cuerpo,
            plantilla=plantillas.get(m.plantilla_id) if m.plantilla_id is not None else None,
            media=[
                MediaMensaje(
                    indice=int(x["indice"]),
                    categoria=x["categoria"],
                    tipo_contenido=x["tipo_contenido"],
                    disponible=x["categoria"] != "no_soportado",
                )
                for x in (m.media or [])
            ],
            boton=(
                BotonMensaje(payload=m.boton_payload, texto=m.boton_texto)
                if m.boton_payload is not None
                else None
            ),
            estado=m.estado,
            error=(
                ErrorMensaje(codigo=m.error_codigo, mensaje=mensaje_de_error(m.error_codigo))
                if m.error_codigo
                else None
            ),
            programado_para=m.programado_para,
            creado_en=m.creado_en,
            enviado_en=m.enviado_en,
            entregado_en=m.entregado_en,
            leido_en=m.leido_en,
        )
        for m in mensajes
    ]


def mensaje_salida(db: Session, mensaje: Mensaje) -> MensajeSalida:
    return mensajes_salida(db, [mensaje])[0]


# ---- Conversaciones ----------------------------------------------------------------------------
def resumenes(
    db: Session, convs: list[Conversacion], usuario: Usuario, ahora: datetime
) -> list[ConversacionResumen]:
    if not convs:
        return []
    ids = [c.id for c in convs]
    usuarios = _usuarios(db, (c.usuario_asignado_id for c in convs))
    campana_ids = {c.campana_id for c in convs if c.campana_id is not None}
    campanas = {
        c.id: CampanaRef(id=c.id, nombre=c.nombre, tipo=c.tipo)  # type: ignore[arg-type]
        for c in (
            db.scalars(select(Campana).where(Campana.id.in_(campana_ids))) if campana_ids else []
        )
    }
    cliente_ids = {c.cliente_id for c in convs if c.cliente_id is not None}
    clientes = (
        dict(
            db.execute(select(Cliente.id, Cliente.nombre).where(Cliente.id.in_(cliente_ids))).all()
        )
        if cliente_ids
        else {}
    )
    motivos_cola: dict[int, str] = {
        cid: motivo
        for cid, motivo in db.execute(
            select(ColaAtencion.conversacion_id, ColaAtencion.motivo).where(
                ColaAtencion.conversacion_id.in_(ids),
                ColaAtencion.estado.in_(("pendiente", "asignada")),
            )
        )
    }
    margen = servicio.margen_ventana()
    ve_numero = usuario.rol in ("administrador", "supervisor")
    return [
        ConversacionResumen(
            id=c.id,
            estado=c.estado,  # type: ignore[arg-type]
            atendida_por=c.atendida_por,  # type: ignore[arg-type]
            usuario_asignado=usuarios.get(c.usuario_asignado_id) if c.usuario_asignado_id else None,
            numero_mascara=enmascarar_telefono(c.numero_cliente_e164),
            numero_e164=c.numero_cliente_e164 if ve_numero else None,
            nombre_perfil=c.nombre_perfil,
            campana=campanas.get(c.campana_id) if c.campana_id else None,
            cliente_nombre=clientes.get(c.cliente_id) if c.cliente_id else None,
            iniciada_por=c.iniciada_por,  # type: ignore[arg-type]
            ventana_abierta=c.estado == "abierta" and ventana_abierta(c, ahora, margen),
            ventana_expira_en=c.ventana_expira_en,
            ultimo_mensaje_en=c.ultimo_mensaje_en,
            mensajes_sin_leer=c.mensajes_sin_leer,
            motivo_cola=motivos_cola.get(c.id),
            abierta_en=c.abierta_en,
            cerrada_en=c.cerrada_en,
            motivo_cierre=c.motivo_cierre,  # type: ignore[arg-type]
        )
        for c in convs
    ]


def motivos_no_responder(
    db: Session, conv: Conversacion, usuario: Usuario, ahora: datetime
) -> list[MotivoSalida]:
    motivos: list[MotivoSalida] = []
    if not servicio.es_dueno(conv, usuario):
        motivos.append(
            MotivoSalida(codigo="NO_ES_DUENO", mensaje="No es el dueño de la conversación.")
        )
    if conv.estado != "abierta":
        motivos.append(
            MotivoSalida(codigo="CONVERSACION_CERRADA", mensaje="La conversación está cerrada.")
        )
        return motivos
    if not ventana_abierta(conv, ahora, servicio.margen_ventana()):
        motivos.append(
            MotivoSalida(
                codigo="VENTANA_CERRADA",
                mensaje="La ventana de 24 h está cerrada: solo se pueden enviar plantillas.",
            )
        )
    elif cumplimiento_wa.opt_out_posterior(db, conv):
        motivos.append(
            MotivoSalida(
                codigo="CLIENTE_OPT_OUT", mensaje="El cliente pidió no recibir más mensajes."
            )
        )
    return motivos


def alertas(db: Session, conv: Conversacion) -> list[MotivoSalida]:
    resultado: list[MotivoSalida] = []
    tipo = None
    if conv.campana_id is not None:
        campana = db.get(Campana, conv.campana_id)
        tipo = campana.tipo if campana else None
    exc = cumplimiento_wa.exclusion_aplicable(db, conv.numero_cliente_e164, tipo)
    if exc is not None:
        resultado.append(
            MotivoSalida(
                codigo="EXCLUIDO_WHATSAPP",
                mensaje=f"El número tiene una exclusión para WhatsApp ({exc.motivo}).",
            )
        )
    if tipo is not None and not cumplimiento_wa.autorizacion_vigente(
        db, conv.numero_cliente_e164, tipo
    ):
        resultado.append(
            MotivoSalida(
                codigo="SIN_AUTORIZACION",
                mensaje="El número no tiene autorización vigente para WhatsApp.",
            )
        )
    if conv.campana_id is None:
        resultado.append(
            MotivoSalida(
                codigo="SIN_CAMPANA", mensaje="La conversación no está vinculada a una campaña."
            )
        )
        if len(candidatos(db, conv.numero_cliente_e164)) > 1:
            resultado.append(
                MotivoSalida(
                    codigo="VARIOS_REGISTROS",
                    mensaje="El número coincide con varios registros; vincule el correcto.",
                )
            )
    return resultado


def _estado_ia(db: Session, conv: Conversacion, usuario: Usuario):
    from app.modulos.agente_ia.estado import estado_ia

    return estado_ia(db, conv, usuario)


def conversacion_salida(
    db: Session, conv: Conversacion, usuario: Usuario, ahora: datetime
) -> ConversacionSalida:
    base = resumenes(db, [conv], usuario, ahora)[0]
    tipificada = (
        db.scalar(select(Tipificacion.id).where(Tipificacion.conversacion_id == conv.id))
        is not None
    )
    motivos = motivos_no_responder(db, conv, usuario, ahora)
    return ConversacionSalida(
        **base.model_dump(),
        campana_cliente_id=conv.campana_cliente_id,
        cliente_id=conv.cliente_id,
        telefono_id=conv.telefono_id,
        tipificada=tipificada,
        puede_responder=not motivos,
        motivos_no_responder=motivos,
        alertas=alertas(db, conv),
        ia=_estado_ia(db, conv, usuario),
    )
