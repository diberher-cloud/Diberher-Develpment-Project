"""Mensajes entrantes: webhook (persistir y encolar) y trabajo `whatsapp.procesar_entrante`
(resolución del contexto, opt-out, enrutado y avisos), fase-2b.md §4.4-4.5.

El `ProfileName` se guarda de forma transitoria en `mensajes.variables` (el payload del trabajo
lleva solo ids) y el procesamiento lo mueve a `conversaciones.nombre_perfil`.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integraciones.whatsapp.proveedor import MensajeEntrante, ProveedorWhatsApp
from app.modulos.conversaciones import atencion, resolucion
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import SinAsignar, decidir_dueno_inicial
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.whatsapp import cumplimiento as cumplimiento_wa
from app.modulos.whatsapp import medios, opt_out, servicio_autorizaciones, servicio_envio
from app.modulos.whatsapp.ventana import VENTANA
from app.trabajos.cola import encolar

logger = logging.getLogger("app")


def tipo_de(entrante: MensajeEntrante) -> str:
    if entrante.boton_payload is not None:
        return "boton"
    if entrante.media:
        return "media"
    if entrante.texto:
        return "texto"
    return "no_soportado"


# ---- Webhook -----------------------------------------------------------------------------------
def recibir(
    db: Session, proveedor: ProveedorWhatsApp, params: dict[str, str], ahora: datetime
) -> Mensaje | None:
    """Pasos 2-4 del webhook entrante (los usa también la simulación). Devuelve el mensaje
    nuevo, o None si es inválido, ajeno o duplicado (sin efectos). Confirma."""
    settings = get_settings()
    entrante = proveedor.parsear_entrante(params)
    if entrante is None:
        logger.warning("whatsapp.entrante_invalido")
        return None
    if proveedor.nombre == "twilio" and entrante.cuenta != settings.twilio_account_sid:
        logger.warning("whatsapp.entrante_cuenta_ajena")
        return None
    if entrante.numero_empresa != settings.whatsapp_numero_empresa:
        logger.warning("whatsapp.entrante_numero_ajeno")
        return None
    if db.scalar(select(Mensaje.id).where(Mensaje.proveedor_id == entrante.proveedor_id)):
        return None
    mensaje = Mensaje(
        conversacion_id=None,
        numero_cliente_e164=entrante.numero_cliente,
        direccion="entrante",
        autor="cliente",
        tipo=tipo_de(entrante),
        cuerpo=entrante.texto or (entrante.boton_texto if entrante.boton_payload else None),
        variables={"nombre_perfil": entrante.nombre_perfil} if entrante.nombre_perfil else None,
        media=[
            {
                "indice": m.indice,
                "tipo_contenido": m.tipo_contenido,
                "categoria": medios.categoria(m.tipo_contenido),
                "url_proveedor": m.url,
            }
            for m in entrante.media
        ],
        boton_payload=entrante.boton_payload,
        boton_texto=entrante.boton_texto,
        respuesta_a_proveedor_id=entrante.respuesta_a,
        proveedor_id=entrante.proveedor_id,
        estado="recibido",
        creado_en=ahora,
    )
    try:
        db.add(mensaje)
        db.flush()
        encolar(
            db,
            "whatsapp.procesar_entrante",
            {"mensaje_id": mensaje.id},
            clave_unica=f"entrante:{mensaje.id}",
            ahora=ahora,
        )
        db.commit()
    except IntegrityError:  # MessageSid duplicado (reintento de Twilio o carrera)
        db.rollback()
        return None
    return mensaje


# ---- Trabajo whatsapp.procesar_entrante --------------------------------------------------------
def _frases() -> tuple[frozenset[str], frozenset[str]]:
    s = get_settings()
    return (
        opt_out.cargar_frases(s.whatsapp_frases_opt_out, opt_out.FRASES_WHATSAPP),
        opt_out.cargar_frases(s.whatsapp_frases_opt_out_todos, opt_out.FRASES_TODOS),
    )


def _abrir_conversacion(
    db: Session, m: Mensaje, numero_empresa: str, nombre_perfil: str | None
) -> tuple[Conversacion, bool]:
    """Crea la conversación abierta (resolviendo el contexto) en un SAVEPOINT; si otra
    transacción la creó antes, devuelve la abierta con `FOR UPDATE`."""
    settings = get_settings()
    res = resolucion.resolver(
        db, m.numero_cliente_e164, m.creado_en, settings.whatsapp_dias_resolucion_plantilla
    )
    cand = res.candidato
    try:
        with db.begin_nested():
            intento_id = None
            if cand is not None:
                from app.modulos.cumplimiento import servicio as cumplimiento

                politica, version = cumplimiento.cargar_politica(db, cand.campana.tipo)
                intento = cumplimiento.registrar_intento(
                    db,
                    cliente_id=cand.cliente.id,
                    tipo_campana=cand.campana.tipo,
                    canal="whatsapp_mensaje",
                    iniciado_por="cliente",
                    momento=m.creado_en,
                    campana_id=cand.campana.id,
                    campana_cliente_id=cand.campana_cliente.id,
                    telefono_id=cand.telefono.id,
                    contacto_directo=politica.entrantes.establecen_contacto_directo,
                    politica_version=version,
                )
                intento_id = intento.id
            conv = conversaciones.crear_conversacion(
                db,
                numero_cliente=m.numero_cliente_e164,
                numero_empresa=numero_empresa,
                iniciada_por="cliente",
                ahora=m.creado_en,
                dueno=decidir_dueno_inicial(None, cand.campana if cand else None),
                nombre_perfil=nombre_perfil,
                cliente_id=cand.cliente.id if cand else None,
                campana_id=cand.campana.id if cand else None,
                campana_cliente_id=cand.campana_cliente.id if cand else None,
                telefono_id=cand.telefono.id if cand else None,
                intento_contacto_id=intento_id,
            )
    except IntegrityError:
        existente = db.scalar(
            select(Conversacion)
            .where(
                Conversacion.clave_abierta
                == conversaciones.clave_abierta(m.numero_cliente_e164, numero_empresa)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existente is None:
            raise
        return existente, False
    return conv, True


def procesar_entrante(db: Session, payload: dict[str, Any], ahora: datetime) -> None:
    """Trabajo `whatsapp.procesar_entrante` (idempotente: si ya se procesó, termina)."""
    settings = get_settings()
    previo = db.get(Mensaje, payload["mensaje_id"])
    if previo is None or previo.procesado_en is not None:
        return
    empresa = settings.whatsapp_numero_empresa
    clave = conversaciones.clave_abierta(previo.numero_cliente_e164, empresa)
    conv = db.scalar(
        select(Conversacion)
        .where(Conversacion.clave_abierta == clave)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    m = db.scalar(
        select(Mensaje)
        .where(Mensaje.id == previo.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if m is None or m.procesado_en is not None:
        return
    nombre = (m.variables or {}).get("nombre_perfil") if m.direccion == "entrante" else None
    nueva = False
    if conv is None:
        conv, nueva = _abrir_conversacion(db, m, empresa, nombre)
    # Asociar el mensaje y actualizar la conversación.
    primer_entrante = conv.ultimo_entrante_en is None
    m.conversacion_id = conv.id
    m.procesado_en = ahora
    m.variables = None
    if m.creado_en >= conv.ultimo_mensaje_en:
        conv.ultimo_mensaje_en = m.creado_en
    if conv.ultimo_entrante_en is None or m.creado_en >= conv.ultimo_entrante_en:
        conv.ultimo_entrante_en = m.creado_en
        conv.ventana_expira_en = m.creado_en + VENTANA
    conv.mensajes_sin_leer += 1
    if nombre:
        conv.nombre_perfil = nombre
    if nueva:
        conversaciones.publicar_estado(db, conv)
    # La respuesta del cliente a una conversación iniciada por la empresa es contacto directo.
    if conv.iniciada_por == "empresa" and primer_entrante and conv.intento_contacto_id is not None:
        intento = db.get(IntentoContacto, conv.intento_contacto_id)
        if intento is not None:
            intento.contacto_directo = True
    db.flush()
    conversaciones.publicar_mensaje(db, conv, m, "nuevo")

    # Opt-out determinista: no se encola a nadie.
    frases_wa, frases_todos = _frases()
    alcance = opt_out.clasificar(
        m.cuerpo,
        m.boton_payload,
        frases_wa,
        frases_todos,
        settings.whatsapp_payload_baja,
        usar_patrones=not (
            settings.whatsapp_frases_opt_out or settings.whatsapp_frases_opt_out_todos
        ),
    )
    if alcance == "voz":  # solo deja de recibir llamadas; la conversación sigue su curso
        servicio_autorizaciones.aplicar_opt_out_voz(db, conv, ahora)
    elif alcance is not None:
        servicio_autorizaciones.aplicar_opt_out(
            db, conv, alcance, origen="determinista", usuario_id=None, ahora=ahora
        )
        return

    # Enrutado.
    if conv.atendida_por == "sin_asignar" and atencion.fila_activa(db, conv.id) is None:
        motivo = "sin_campana" if conv.campana_cliente_id is None else "entrante"
        conversaciones.cambiar_dueno(db, conv, SinAsignar(), motivo, None, ahora)
        # Aviso de espera: solo al entrar en cola y si nadie puede atender ahora mismo.
        texto = settings.whatsapp_mensaje_espera
        if (
            texto
            and conv.aviso_espera_enviado_en is None
            and not cumplimiento_wa.hay_agente_disponible(db, conv.campana_id)
        ):
            servicio_envio.crear_automatico(db, conv, texto, ahora)
            conv.aviso_espera_enviado_en = ahora
