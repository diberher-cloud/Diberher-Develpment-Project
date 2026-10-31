"""Traspaso de la IA a la cola humana y vuelta a la IA (fase-2c.md §5)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.agente_ia import configuracion, historial, mensajes
from app.modulos.agente_ia.canal import CanalIA
from app.modulos.agente_ia.canal_chat import CanalChat
from app.modulos.agente_ia.contexto import (
    RefInteraccion,
    SinContextoIA,
    cargar_contexto,
)
from app.modulos.auditoria import servicio as auditoria
from app.modulos.consola.modelos import Tipificacion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import IA, SinAsignar
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import cumplimiento as cumplimiento_wa

RESUMENES: dict[str, str] = {
    "solicitud_cliente": "El cliente pidió hablar con un asesor.",
    "entrante": (
        "No se puede responder ahora: la próxima franja empieza después de cerrar la ventana "
        "de 24 h. Use una plantilla."
    ),
    "identidad_bloqueada": "Verificación de identidad fallida {n} veces.",
    "ia_monto_no_respaldado": (
        "El asistente intentó enviar una respuesta que no superó los controles; no se envió."
    ),
    "presupuesto_excedido": "Se alcanzó el límite de coste o de turnos de la conversación.",
    "ia_desactivada": "El agente IA se desactivó para esta campaña.",
}
_GENERICO_IA = "El asistente no pudo completar la respuesta ({motivo}). Revise la conversación."
ORIGEN_AUDITORIA = {
    "solicitud_cliente": "guarda",
    "entrante": "guarda",
    "identidad_bloqueada": "guarda",
    "presupuesto_excedido": "presupuesto",
    "ia_desactivada": "kill_switch",
}


def gestion_registrada(db: Session, conv: Conversacion) -> str | None:
    return db.scalar(select(Tipificacion.resultado).where(Tipificacion.conversacion_id == conv.id))


def resumen_fijo(db: Session, conv: Conversacion, motivo: str) -> str:
    base = RESUMENES.get(motivo) or _GENERICO_IA.format(motivo=motivo)
    base = base.format(n=conv.identidad_intentos) if "{n}" in base else base
    return (
        f"{base} Identidad verificada: {'sí' if conv.identidad_verificada else 'no'}. "
        f"Gestión registrada: {gestion_registrada(db, conv) or 'ninguna'}."
    )[:500]


def derivar_determinista(
    db: Session,
    canal: CanalIA,
    ref: RefInteraccion,
    motivo: str,
    ahora: datetime,
    *,
    enviar: bool = True,
    origen: str | None = None,
) -> int:
    """Traspaso a la cola humana con resumen fijo + mensaje fijo (`autor=sistema`):
    `IA_MENSAJE_TRASPASO` si hay un asesor disponible, si no `WHATSAPP_MENSAJE_ESPERA`.
    Devuelve el id de la fila de cola. Sin commit."""
    s = get_settings()
    conv = conversaciones.cargar(db, ref.id)
    cola_id = canal.derivar(db, ref, motivo, resumen_fijo(db, conv, motivo), ahora)
    auditoria.registrar(
        db,
        "ia.derivacion",
        None,
        "conversacion",
        conv.id,
        {
            "conversacion_id": conv.id,
            "motivo": motivo,
            "origen": origen or ORIGEN_AUDITORIA.get(motivo, "error"),
        },
    )
    if enviar:
        try:
            hay = canal.hay_humano_disponible(db, cargar_contexto(db, ref))
        except SinContextoIA:
            hay = cumplimiento_wa.hay_agente_disponible(db, conv.campana_id)
        texto = s.ia_mensaje_traspaso if hay else s.whatsapp_mensaje_espera
        if texto:
            canal.enviar(db, ref, texto, ahora, "sistema")
            if not hay:
                conv.aviso_espera_enviado_en = ahora
    return cola_id


# ---- Vuelta a la IA ----------------------------------------------------------------------------
def _etiqueta_media(m: Mensaje) -> str:
    if m.cuerpo:
        return m.cuerpo
    return "[mensaje sin texto]"


def _mensajes_para_intervencion(
    db: Session, conv: Conversacion
) -> list[tuple[str, int, datetime, str]]:
    visto = db.scalar(
        select(Mensaje.id)
        .where(
            Mensaje.conversacion_id == conv.id,
            (Mensaje.procesado_ia_en.is_not(None)) | (Mensaje.autor == "ia"),
        )
        .order_by(Mensaje.id.desc())
        .limit(1)
    )
    filas = db.scalars(
        select(Mensaje)
        .where(
            Mensaje.conversacion_id == conv.id,
            Mensaje.id > (visto or 0),
            Mensaje.estado.not_in(("cancelado", "fallido")),
        )
        .order_by(Mensaje.id)
    )
    salida = []
    for m in filas:
        clase = (
            "cliente"
            if m.direccion == "entrante"
            else ("asesor" if m.autor == "agente" else "sistema")
        )
        salida.append((clase, m.id, m.creado_en, _etiqueta_media(m)))
    return salida


def devolver_a_ia(
    db: Session, usuario: Usuario, conversacion_id: int, ahora: datetime
) -> Conversacion:
    previa = conversaciones.cargar(db, conversacion_id)
    if usuario.rol == "agente":
        conversaciones.exigir_dueno(previa, usuario)
    conv = conversaciones.bloquear(db, conversacion_id)
    if usuario.rol == "agente":
        conversaciones.exigir_dueno(conv, usuario)
    conversaciones.exigir_abierta(conv)
    motivos = motivos_no_devolver(db, conv)
    if motivos:
        raise ErrorApp(409, motivos[0][0], motivos[0][1])
    ref = RefInteraccion("conversacion", conv.id)
    ctx = cargar_contexto(db, ref)
    pendientes = _mensajes_para_intervencion(db, conv)
    historial.agregar(
        db,
        ref,
        "user",
        "intervencion",
        mensajes.bloque_intervencion(pendientes, ctx.zona_horaria),
        ahora,
    )
    historial.agregar(db, ref, "system", "vuelta_ia", {"texto": mensajes.MENSAJE_VUELTA_IA}, ahora)
    ids_cliente = [i for clase, i, _, _ in pendientes if clase == "cliente"]
    if ids_cliente:
        for m in db.scalars(select(Mensaje).where(Mensaje.id.in_(ids_cliente))):
            m.procesado_ia_en = ahora
    try:
        conversaciones.cambiar_dueno(db, conv, IA(), None, usuario.id, ahora)
    except conversaciones.ConflictoDueno:
        db.rollback()
        raise ErrorApp(409, "CONVERSACION_ASIGNADA", "El dueño cambió; reintente.") from None
    auditoria.registrar(
        db, "ia.devolver", usuario.id, "conversacion", conv.id, {"conversacion_id": conv.id}
    )
    db.commit()
    return conv


def motivos_no_devolver(db: Session, conv: Conversacion) -> list[tuple[str, str]]:
    """Códigos de §5.4 que impiden devolver la conversación a la IA."""
    motivos: list[tuple[str, str]] = []
    if conv.estado != "abierta":
        motivos.append(("CONVERSACION_CERRADA", "La conversación está cerrada."))
        return motivos
    if conv.campana_cliente_id is None or not configuracion.ia_disponible(db, conv.campana_id):
        motivos.append(("IA_NO_DISPONIBLE", "La IA no está disponible para esta conversación."))
    elif cumplimiento_wa.opt_out_posterior(db, conv):
        motivos.append(("CLIENTE_OPT_OUT", "El cliente pidió no recibir más mensajes."))
    return motivos


def traspasar(
    db: Session, usuario: Usuario, conversacion_id: int, resumen: str | None, ahora: datetime
) -> Conversacion:
    conversaciones.cargar(db, conversacion_id)
    conv = conversaciones.bloquear(db, conversacion_id)
    conversaciones.exigir_abierta(conv)
    if conv.atendida_por != "ia":
        raise ErrorApp(409, "CONVERSACION_NO_IA", "La conversación no la atiende la IA.")
    texto = (resumen or "").strip()[:500] or "Traspasada por un supervisor."
    try:
        conversaciones.cambiar_dueno(
            db, conv, SinAsignar(), "supervisor", usuario.id, ahora, resumen=texto
        )
    except conversaciones.ConflictoDueno:
        db.rollback()
        raise ErrorApp(409, "CONVERSACION_NO_IA", "La conversación no la atiende la IA.") from None
    auditoria.registrar(
        db, "ia.traspasar", usuario.id, "conversacion", conv.id, {"conversacion_id": conv.id}
    )
    db.commit()
    return conv


# ---- Kill switch: traspaso masivo --------------------------------------------------------------
LOTE_TRASPASO = 100


def traspasar_campana(db: Session, payload: dict[str, Any], ahora: datetime) -> bool:
    """Un lote de conversaciones `ia` abiertas (de la campaña o de todas) sin IA disponible pasan
    a la cola con motivo `ia_desactivada`. Cada una `FOR UPDATE SKIP LOCKED` (las bloqueadas se
    reintentan). Con entrantes sin responder, además el mensaje fijo. Devuelve si quedan."""
    from app.modulos.conversaciones.modelos import Conversacion as C

    campana_id = payload.get("campana_id")
    consulta = select(C.id).where(C.estado == "abierta", C.atendida_por == "ia")
    if campana_id is not None:
        consulta = consulta.where(C.campana_id == campana_id)
    ids = list(db.scalars(consulta.order_by(C.id).limit(LOTE_TRASPASO * 5)))
    canal = CanalChat()
    hechas = 0
    quedan = False
    for conv_id in ids:
        if hechas >= LOTE_TRASPASO:
            quedan = True
            break
        conv = db.scalar(
            select(C)
            .where(C.id == conv_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if conv is None:
            quedan = True
            continue
        if conv.estado != "abierta" or conv.atendida_por != "ia":
            continue
        if configuracion.ia_disponible(db, conv.campana_id):
            continue
        sin_responder = (
            db.scalar(
                select(Mensaje.id)
                .where(
                    Mensaje.conversacion_id == conv.id,
                    Mensaje.direccion == "entrante",
                    Mensaje.procesado_ia_en.is_(None),
                )
                .limit(1)
            )
            is not None
        )
        from app.modulos.whatsapp.ventana import ventana_abierta

        enviar = sin_responder and ventana_abierta(conv, ahora, conversaciones.margen_ventana())
        derivar_determinista(
            db,
            canal,
            RefInteraccion("conversacion", conv.id),
            "ia_desactivada",
            ahora,
            enviar=enviar,
        )
        hechas += 1
    return quedan or len(ids) >= LOTE_TRASPASO * 5
