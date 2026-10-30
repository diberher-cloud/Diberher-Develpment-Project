"""Envío de mensajes: texto (dentro de la ventana), plantilla (consola y conversación),
automáticos y el trabajo `whatsapp.enviar_mensaje` (fase-2b.md §4.6).

Envío "como mucho una vez": el trabajo marca `enviando` y confirma ANTES de llamar al proveedor;
si un reintento encuentra `enviando`, marca `ENVIO_INCIERTO` en vez de reenviar.
"""

import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.integraciones.whatsapp.fabrica import obtener_proveedor_whatsapp
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import estado as estado_agente
from app.modulos.consola import servicio as consola
from app.modulos.consola.esquemas import MotivoSalida
from app.modulos.conversaciones import atencion, salidas
from app.modulos.conversaciones import servicio as conversaciones
from app.modulos.conversaciones.dueno import Humano, decidir_dueno_inicial
from app.modulos.conversaciones.esquemas import ResultadoEnvioPlantilla
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import cumplimiento as cumplimiento_wa
from app.modulos.whatsapp import plantillas_render as render
from app.modulos.whatsapp import servicio_estado, servicio_plantillas
from app.modulos.whatsapp.modelos import PlantillaWhatsApp
from app.modulos.whatsapp.ventana import Rechazar, Retener, decidir_respuesta, ventana_abierta
from app.trabajos.cola import encolar
from app.trabajos.registro import ErrorTrabajo, ReprogramarTrabajo

logger = logging.getLogger("app")
MAX_TEXTO = 4096
RUTA_ESTADO = "/api/v1/whatsapp/webhooks/estado"


def url_estado() -> str:
    return get_settings().public_base_url + RUTA_ESTADO


def encolar_envio(
    db: Session, mensaje: Mensaje, ahora: datetime, desde: datetime | None = None
) -> None:
    encolar(
        db,
        "whatsapp.enviar_mensaje",
        {"mensaje_id": mensaje.id},
        clave_unica=f"enviar:{mensaje.id}",
        disponible_desde=desde or ahora,
        ahora=ahora,
    )


def _nuevo_saliente(
    conv: Conversacion, ahora: datetime, *, autor: str, usuario_id: int | None, tipo: str, **kw: Any
) -> Mensaje:
    return Mensaje(
        conversacion_id=conv.id,
        numero_cliente_e164=conv.numero_cliente_e164,
        direccion="saliente",
        autor=autor,
        usuario_id=usuario_id,
        tipo=tipo,
        estado="pendiente",
        creado_en=ahora,
        **kw,
    )


def crear_automatico(db: Session, conv: Conversacion, texto: str, ahora: datetime) -> Mensaje:
    """Mensaje automático (`autor=sistema`): acuse inmediato de un mensaje del cliente, exento
    de `decidir_respuesta` pero sujeto a la ventana al enviarse. No crea intentos."""
    m = _nuevo_saliente(conv, ahora, autor="sistema", usuario_id=None, tipo="texto", cuerpo=texto)
    db.add(m)
    db.flush()
    encolar_envio(db, m, ahora)
    if ahora > conv.ultimo_mensaje_en:
        conv.ultimo_mensaje_en = ahora
    conversaciones.publicar_mensaje(db, conv, m, "nuevo")
    return m


# ---- Idempotencia ------------------------------------------------------------------------------
def _por_clave(db: Session, clave: UUID) -> Mensaje | None:
    return db.scalar(select(Mensaje).where(Mensaje.idempotencia_clave == str(clave)))


def _conflicto() -> ErrorApp:
    return ErrorApp(
        409,
        "IDEMPOTENCIA_CONFLICTO",
        "La clave de idempotencia ya se usó con otro usuario o conversación.",
    )


# ---- Texto -------------------------------------------------------------------------------------
def _festivos(db: Session, ahora: datetime, politicas) -> dict[date, str]:
    resultado: dict[date, str] = {}
    for p in politicas:
        resultado.update(cumplimiento_wa.festivos_para(db, ahora, p))
    return resultado


def enviar_texto(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    texto: str,
    clave: UUID,
    ahora: datetime,
) -> tuple[Mensaje, bool]:
    """Devuelve (mensaje, creado). `creado=False` si es una repetición de la misma clave."""
    previa = conversaciones.cargar(db, conversacion_id)
    conversaciones.exigir_dueno(previa, usuario)
    conv = conversaciones.bloquear(db, conversacion_id)
    conversaciones.exigir_dueno(conv, usuario)
    existente = _por_clave(db, clave)
    if existente is not None:
        if existente.usuario_id == usuario.id and existente.conversacion_id == conv.id:
            return existente, False
        raise _conflicto()
    texto = texto.strip()
    if not 1 <= len(texto) <= MAX_TEXTO:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("texto", f"Debe tener entre 1 y {MAX_TEXTO} caracteres.")],
        )
    conversaciones.exigir_abierta(conv)
    margen = conversaciones.margen_ventana()
    if not ventana_abierta(conv, ahora, margen):
        raise ErrorApp(
            409,
            "VENTANA_CERRADA",
            "La ventana de 24 h está cerrada: solo se pueden enviar plantillas.",
        )
    if cumplimiento_wa.opt_out_posterior(db, conv):
        raise ErrorApp(409, "CLIENTE_OPT_OUT", "El cliente pidió no recibir más mensajes.")
    politicas = cumplimiento_wa.politicas_aplicables(db, conv.campana_id)
    assert conv.ventana_expira_en is not None
    decision = decidir_respuesta(
        ahora, politicas, _festivos(db, ahora, politicas), conv.ventana_expira_en, margen
    )
    if isinstance(decision, Rechazar):
        sugerida = decision.proxima_franja.isoformat() if decision.proxima_franja else "sin fecha"
        raise ErrorApp(
            409,
            "RESPUESTA_FUERA_DE_FRANJA",
            "La respuesta queda fuera de la franja horaria permitida.",
            [
                detalle(
                    "texto",
                    f"La próxima franja ({sugerida}) empieza después de que cierre la "
                    "ventana de 24 h. Use una plantilla.",
                )
            ],
        )
    m = _nuevo_saliente(
        conv,
        ahora,
        autor="agente",
        usuario_id=usuario.id,
        tipo="texto",
        cuerpo=texto,
        idempotencia_clave=str(clave),
    )
    retenido = isinstance(decision, Retener)
    if retenido:
        m.estado = "retenido"
        m.programado_para = decision.programado_para
    try:
        db.add(m)
        db.flush()
    except IntegrityError:
        db.rollback()
        existente = _por_clave(db, clave)
        if existente is not None and existente.usuario_id == usuario.id:
            return existente, False
        raise _conflicto() from None
    encolar_envio(db, m, ahora, m.programado_para)
    conv.ultimo_mensaje_en = ahora
    conversaciones.publicar_mensaje(db, conv, m, "nuevo")
    aviso = get_settings().whatsapp_mensaje_fuera_de_franja
    if retenido and conv.aviso_fuera_franja_enviado_en is None and aviso:
        crear_automatico(db, conv, aviso, ahora)
        conv.aviso_fuera_franja_enviado_en = ahora
    db.commit()
    return m, True


# ---- Plantilla ---------------------------------------------------------------------------------
def _resultado_existente(
    db: Session, existente: Mensaje, usuario: Usuario
) -> ResultadoEnvioPlantilla:
    version = None
    conv = db.get(Conversacion, existente.conversacion_id) if existente.conversacion_id else None
    if conv is not None and conv.intento_contacto_id is not None:
        from app.modulos.cumplimiento.modelos import IntentoContacto

        intento = db.get(IntentoContacto, conv.intento_contacto_id)
        version = intento.politica_version if intento else None
    return ResultadoEnvioPlantilla(
        permitido=True,
        motivos=[],
        proxima_ventana_inicio=None,
        politica_version=version,
        conversacion_id=existente.conversacion_id,
        mensaje=salidas.mensaje_salida(db, existente),
    )


def enviar_plantilla(
    db: Session,
    *,
    usuario: Usuario,
    campana_cliente: CampanaCliente,
    telefono: Telefono | None,
    plantilla: PlantillaWhatsApp | None,
    conversacion: Conversacion | None,
    idempotencia_clave: UUID,
    ahora: datetime,
) -> ResultadoEnvioPlantilla:
    """Servicio único de plantilla (consola: `conversacion is None`; bandeja: conversación dada).

    Validación 3-8 de §4.6; después cumplimiento (`permitido=false` NO es un error HTTP)."""
    cc = campana_cliente
    campana = db.get(Campana, cc.campana_id)
    assert campana is not None
    # 3. campaña activa con WhatsApp.
    if campana.estado != "activa" or not campana.whatsapp_habilitado:
        raise ErrorApp(
            409,
            "WHATSAPP_NO_HABILITADO",
            "La campaña no está activa o no tiene WhatsApp habilitado.",
        )
    # 4. teléfono móvil del cliente del registro.
    if telefono is None or telefono.cliente_id != cc.cliente_id or telefono.tipo_linea != "movil":
        raise ErrorApp(
            422,
            "TELEFONO_NO_VALIDO",
            "El teléfono no es un móvil del cliente del registro.",
            [detalle("telefono_id", "Debe ser un móvil del cliente del registro.")],
        )
    # 5. plantilla enviable para la finalidad de la campaña.
    if (
        plantilla is None
        or not servicio_plantillas.enviable(plantilla)
        or not servicio_plantillas.compatible_con(plantilla, campana.tipo)
    ):
        raise ErrorApp(
            422,
            "PLANTILLA_NO_DISPONIBLE",
            "La plantilla no existe, no está aprobada/activa o es de otra finalidad.",
            [detalle("plantilla_id", "Plantilla no disponible para esta campaña.")],
        )
    cliente = db.get(Cliente, cc.cliente_id)
    assert cliente is not None
    # 6. valores de variables.
    variables = servicio_plantillas.calcular_variables(plantilla, cliente, cc, usuario)
    # 7/8. Bloqueos en el orden global: estados_agente -> clientes -> conversaciones.
    if usuario.rol == "agente":
        estado_agente.bloquear(db, usuario.id)
    db.execute(select(Cliente.id).where(Cliente.id == cc.cliente_id).with_for_update()).all()
    db.refresh(cc)
    empresa = get_settings().whatsapp_numero_empresa
    if conversacion is not None:
        conv: Conversacion | None = conversaciones.bloquear(db, conversacion.id)
        conversaciones.exigir_dueno(conv, usuario)
        conversaciones.exigir_abierta(conv)
        numero = conv.numero_cliente_e164
    else:
        numero = telefono.numero_e164
        conv = db.scalar(
            select(Conversacion)
            .where(Conversacion.clave_abierta == conversaciones.clave_abierta(numero, empresa))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if conv is not None:
            margen = conversaciones.margen_ventana()
            if ventana_abierta(conv, ahora, margen):
                raise ErrorApp(
                    409,
                    "VENTANA_ABIERTA",
                    "La ventana de 24 h está abierta: responda en la conversación.",
                )
            if conv.atendida_por == "humano" and conv.usuario_asignado_id != usuario.id:
                raise ErrorApp(
                    409, "CONVERSACION_ASIGNADA", "La conversación ya la atiende otro usuario."
                )
            if conv.campana_cliente_id != cc.id:
                raise ErrorApp(
                    409,
                    "CONVERSACION_ABIERTA_OTRO_REGISTRO",
                    "El número tiene una conversación abierta de otro registro.",
                )
    # Cumplimiento: todos los motivos, en orden.
    motivos = cumplimiento_wa.motivos_plantilla(db, cc.cliente_id, numero, campana.tipo, ahora)
    if not motivos.permitido:
        auditoria.registrar(
            db,
            "whatsapp.plantilla_bloqueada",
            usuario.id,
            "campana_cliente",
            cc.id,
            {
                "campana_cliente_id": cc.id,
                "plantilla_id": plantilla.id,
                "codigos": [c for c, _ in motivos.motivos],
            },
        )
        db.commit()
        return ResultadoEnvioPlantilla(
            permitido=False,
            motivos=[MotivoSalida(codigo=c, mensaje=t) for c, t in motivos.motivos],
            proxima_ventana_inicio=(
                motivos.proxima_ventana_inicio.isoformat()
                if motivos.proxima_ventana_inicio
                else None
            ),
            politica_version=motivos.politica_version,
            conversacion_id=None,
            mensaje=None,
        )

    # Permitido: conversación nueva o reutilizada.
    if conv is None:
        atencion.exigir_capacidad(db, usuario)
        try:
            with db.begin_nested():
                intento = cumplimiento.registrar_intento(
                    db,
                    cliente_id=cc.cliente_id,
                    tipo_campana=campana.tipo,
                    canal="whatsapp_mensaje",
                    iniciado_por="empresa",
                    momento=ahora,
                    campana_id=campana.id,
                    campana_cliente_id=cc.id,
                    telefono_id=telefono.id,
                    contacto_directo=False,
                    politica_version=motivos.politica_version,
                )
                conv = conversaciones.crear_conversacion(
                    db,
                    numero_cliente=numero,
                    numero_empresa=empresa,
                    iniciada_por="empresa",
                    ahora=ahora,
                    dueno=decidir_dueno_inicial(None, campana, abre_agente_id=usuario.id),
                    cliente_id=cc.cliente_id,
                    campana_id=campana.id,
                    campana_cliente_id=cc.id,
                    telefono_id=telefono.id,
                    intento_contacto_id=intento.id,
                )
        except IntegrityError:
            db.rollback()
            raise ErrorApp(
                409,
                "CONVERSACION_ABIERTA_OTRO_REGISTRO",
                "El número tiene una conversación abierta de otro registro.",
            ) from None
        conversaciones.publicar_estado(db, conv)
    else:
        # Conversación reutilizada: cada plantilla es un contacto de la empresa y cuenta para la
        # frecuencia (Ley 2300), así que SIEMPRE se registra su intento.
        intento = cumplimiento.registrar_intento(
            db,
            cliente_id=cc.cliente_id,
            tipo_campana=campana.tipo,
            canal="whatsapp_mensaje",
            iniciado_por="empresa",
            momento=ahora,
            campana_id=campana.id,
            campana_cliente_id=cc.id,
            telefono_id=telefono.id,
            contacto_directo=False,
            politica_version=motivos.politica_version,
        )
        if conv.intento_contacto_id is None:
            conv.intento_contacto_id = intento.id
    if conv.atendida_por != "humano":
        atencion.exigir_capacidad(db, usuario)
        try:
            conversaciones.cambiar_dueno(db, conv, Humano(usuario.id), None, usuario.id, ahora)
        except conversaciones.ConflictoDueno:
            db.rollback()
            raise ErrorApp(
                409, "CONVERSACION_ASIGNADA", "La conversación ya la atiende otro usuario."
            ) from None
    m = _nuevo_saliente(
        conv,
        ahora,
        autor="agente",
        usuario_id=usuario.id,
        tipo="plantilla",
        cuerpo=render.renderizar(plantilla.cuerpo, variables),
        plantilla_id=plantilla.id,
        variables=variables,
        idempotencia_clave=str(idempotencia_clave),
    )
    try:
        db.add(m)
        db.flush()
    except IntegrityError:
        db.rollback()
        existente = _por_clave(db, idempotencia_clave)
        if existente is not None and existente.usuario_id == usuario.id:
            return _resultado_existente(db, existente, usuario)
        raise _conflicto() from None
    encolar_envio(db, m, ahora)
    conv.ultimo_mensaje_en = ahora
    if conversacion is None:
        cc.reservado_hasta = ahora + _reserva()
        cc.ultima_gestion_en = ahora
    auditoria.registrar(
        db,
        "whatsapp.plantilla_enviada",
        usuario.id,
        "mensaje",
        m.id,
        {
            "mensaje_id": m.id,
            "conversacion_id": conv.id,
            "plantilla_id": plantilla.id,
            "campana_cliente_id": cc.id,
        },
    )
    conversaciones.publicar_mensaje(db, conv, m, "nuevo")
    db.commit()
    return ResultadoEnvioPlantilla(
        permitido=True,
        motivos=[],
        proxima_ventana_inicio=None,
        politica_version=motivos.politica_version,
        conversacion_id=conv.id,
        mensaje=salidas.mensaje_salida(db, m),
    )


def _reserva():
    from datetime import timedelta

    return timedelta(minutes=get_settings().consola_reserva_minutos)


def enviar_plantilla_consola(
    db: Session,
    usuario: Usuario,
    registro_id: int,
    telefono_id: int,
    plantilla_id: int,
    clave: UUID,
    ahora: datetime,
) -> ResultadoEnvioPlantilla:
    """`POST /consola/registros/{id}/whatsapp/plantilla`: pasos 1-2 de §4.6 y servicio único."""
    cc = db.get(CampanaCliente, registro_id)
    if cc is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Registro no encontrado.")
    if not consola._asignada(db, usuario.id, cc.campana_id):
        raise consola._no_asignada()
    if not (consola.reserva_vigente(cc, ahora) and cc.reservado_por == usuario.id):
        raise ErrorApp(409, "REGISTRO_NO_RESERVADO", "No tiene una reserva vigente del registro.")
    existente = _por_clave(db, clave)
    if existente is not None:
        conv = (
            db.get(Conversacion, existente.conversacion_id) if existente.conversacion_id else None
        )
        if (
            existente.usuario_id == usuario.id
            and conv is not None
            and conv.campana_cliente_id == cc.id
        ):
            return _resultado_existente(db, existente, usuario)
        raise _conflicto()
    return enviar_plantilla(
        db,
        usuario=usuario,
        campana_cliente=cc,
        telefono=db.get(Telefono, telefono_id),
        plantilla=db.get(PlantillaWhatsApp, plantilla_id),
        conversacion=None,
        idempotencia_clave=clave,
        ahora=ahora,
    )


def enviar_plantilla_conversacion(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    plantilla_id: int,
    clave: UUID,
    ahora: datetime,
) -> ResultadoEnvioPlantilla:
    """`POST /conversaciones/{id}/plantillas` (dueño): registro y teléfono de la conversación."""
    conv = conversaciones.cargar(db, conversacion_id)
    conversaciones.exigir_dueno(conv, usuario)
    conversaciones.exigir_abierta(conv)
    existente = _por_clave(db, clave)
    if existente is not None:
        if existente.usuario_id == usuario.id and existente.conversacion_id == conv.id:
            return _resultado_existente(db, existente, usuario)
        raise _conflicto()
    cc = db.get(CampanaCliente, conv.campana_cliente_id) if conv.campana_cliente_id else None
    if cc is None:
        raise ErrorApp(
            409,
            "WHATSAPP_NO_HABILITADO",
            "La conversación no está vinculada a un registro de campaña.",
        )
    return enviar_plantilla(
        db,
        usuario=usuario,
        campana_cliente=cc,
        telefono=db.get(Telefono, conv.telefono_id) if conv.telefono_id else None,
        plantilla=db.get(PlantillaWhatsApp, plantilla_id),
        conversacion=conv,
        idempotencia_clave=clave,
        ahora=ahora,
    )


# ---- Trabajo whatsapp.enviar_mensaje -----------------------------------------------------------
def _revalidar_plantilla(
    db: Session, conv: Conversacion, m: Mensaje, ahora: datetime
) -> str | None:
    """Al ejecutar el trabajo: exclusión, autorización, plantilla enviable y franja/festivo
    (el trabajo puede ejecutarse horas después de encolarse). Devuelve el código de fallo."""
    campana = db.get(Campana, conv.campana_id) if conv.campana_id else None
    if campana is None:
        return "CONTACTO_NO_PERMITIDO"
    exc = cumplimiento_wa.exclusion_aplicable(db, conv.numero_cliente_e164, campana.tipo)
    if exc is not None:
        return "CLIENTE_OPT_OUT" if exc.motivo == "solicitud_titular" else "CONTACTO_NO_PERMITIDO"
    if not cumplimiento_wa.autorizacion_vigente(db, conv.numero_cliente_e164, campana.tipo):
        return "CONTACTO_NO_PERMITIDO"
    plantilla = db.get(PlantillaWhatsApp, m.plantilla_id) if m.plantilla_id else None
    if (
        plantilla is None
        or not servicio_plantillas.enviable(plantilla)
        or not servicio_plantillas.compatible_con(plantilla, campana.tipo)
    ):
        return "PLANTILLA_NO_ENVIABLE"
    politica, _ = cumplimiento.cargar_politica(db, campana.tipo)
    horario = motor.evaluar_horario(
        ahora, politica, cumplimiento.cargar_festivos(db, ahora, politica)
    )
    return None if horario.permitido else "FUERA_DE_FRANJA"


def _bloquear_mensaje(db: Session, mensaje_id: int) -> Mensaje | None:
    return db.scalar(
        select(Mensaje)
        .where(Mensaje.id == mensaje_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _fallar(
    db: Session, conv: Conversacion, m: Mensaje, codigo: str, accion: str = "estado"
) -> None:
    m.estado = "fallido"
    m.error_codigo = codigo[:30]
    conversaciones.publicar_mensaje(db, conv, m, accion)


def ejecutar_envio(db: Session, payload: dict[str, Any], ahora: datetime) -> None:
    """Tx 1 (revalidar y marcar `enviando`) -> llamada al proveedor -> Tx 2 (resultado)."""
    settings = get_settings()
    previo = db.get(Mensaje, payload["mensaje_id"])
    if previo is None or previo.conversacion_id is None:
        return
    conv = conversaciones.bloquear(db, previo.conversacion_id)
    m = _bloquear_mensaje(db, previo.id)
    assert m is not None
    if m.estado == "enviando":  # un intento anterior murió a mitad: no se reenvía
        _fallar(db, conv, m, "ENVIO_INCIERTO")
        db.commit()
        return
    if m.estado not in ("pendiente", "retenido"):
        db.rollback()
        return
    if conv.estado == "cerrada" and not (m.autor == "sistema" and conv.motivo_cierre == "opt_out"):
        m.estado = "cancelado"
        conversaciones.publicar_mensaje(db, conv, m, "estado")
        db.commit()
        return
    margen = conversaciones.margen_ventana()
    fallo: str | None = None
    if m.tipo == "texto":
        if not ventana_abierta(conv, ahora, margen):
            fallo = "VENTANA_CERRADA"
        elif m.autor == "agente":
            if cumplimiento_wa.opt_out_posterior(db, conv):
                fallo = "CLIENTE_OPT_OUT"
            else:
                politicas = cumplimiento_wa.politicas_aplicables(db, conv.campana_id)
                assert conv.ventana_expira_en is not None
                decision = decidir_respuesta(
                    ahora,
                    politicas,
                    _festivos(db, ahora, politicas),
                    conv.ventana_expira_en,
                    margen,
                )
                if isinstance(decision, Retener):
                    m.estado = "retenido"
                    m.programado_para = decision.programado_para
                    db.commit()
                    raise ReprogramarTrabajo(decision.programado_para)
                if isinstance(decision, Rechazar):
                    fallo = "RESPUESTA_FUERA_DE_FRANJA"
    elif m.tipo == "plantilla":
        fallo = _revalidar_plantilla(db, conv, m, ahora)
    if fallo is not None:
        _fallar(db, conv, m, fallo)
        db.commit()
        return
    m.estado = "enviando"
    destino, tipo, cuerpo = conv.numero_cliente_e164, m.tipo, m.cuerpo
    variables = dict(m.variables or {})
    plantilla = db.get(PlantillaWhatsApp, m.plantilla_id) if m.plantilla_id else None
    mensaje_id, conv_id = m.id, conv.id
    db.commit()  # Tx 1: confirma `enviando` antes de llamar al proveedor

    proveedor = obtener_proveedor_whatsapp()
    try:
        if tipo == "plantilla" and plantilla is not None:
            resultado = proveedor.enviar_plantilla(
                origen=settings.whatsapp_numero_empresa,
                destino=destino,
                plantilla_ref=plantilla.content_sid,
                variables=variables,
                url_estado=url_estado(),
            )
        else:
            resultado = proveedor.enviar_texto(
                origen=settings.whatsapp_numero_empresa,
                destino=destino,
                texto=cuerpo or "",
                url_estado=url_estado(),
            )
    except ErrorProveedorWhatsApp as exc:
        _tras_error(db, conv_id, mensaje_id, exc)
        return
    _tras_exito(db, conv_id, mensaje_id, resultado.proveedor_id, ahora)


def _tras_error(db: Session, conv_id: int, mensaje_id: int, exc: ErrorProveedorWhatsApp) -> None:
    conv = conversaciones.bloquear(db, conv_id)
    m = _bloquear_mensaje(db, mensaje_id)
    assert m is not None
    if exc.transitorio:
        m.estado = "pendiente"
        db.commit()
        raise ErrorTrabajo(exc.codigo, transitorio=True)
    _fallar(db, conv, m, exc.codigo)
    db.commit()


def _tras_exito(
    db: Session, conv_id: int, mensaje_id: int, proveedor_id: str, ahora: datetime
) -> None:
    """Tx 2: guarda el SID, `enviado` y aplica los estados que llegaron antes."""
    servicio_estado.bloquear_sid(db, proveedor_id)
    conv = conversaciones.bloquear(db, conv_id)
    m = _bloquear_mensaje(db, mensaje_id)
    assert m is not None
    m.proveedor_id = proveedor_id
    if m.estado == "enviando":
        m.estado = "enviado"
        m.error_codigo = None
        m.enviado_en = ahora
    servicio_estado.aplicar_eventos_pendientes(db, m, ahora)
    conversaciones.publicar_mensaje(db, conv, m, "estado")
    db.commit()


def envio_agotado(db: Session, payload: dict[str, Any], codigo: str, ahora: datetime) -> None:
    """Gancho: el trabajo agotó sus intentos; el mensaje pasa a `fallido`. Sin commit."""
    previo = db.get(Mensaje, payload.get("mensaje_id", 0))
    if previo is None or previo.conversacion_id is None:
        return
    conv = conversaciones.bloquear(db, previo.conversacion_id)
    m = _bloquear_mensaje(db, previo.id)
    if m is not None and m.estado in ("pendiente", "retenido", "enviando"):
        # Si estaba `enviando` el proveedor pudo haber recibido el mensaje: resultado incierto.
        _fallar(db, conv, m, "ENVIO_INCIERTO" if m.estado == "enviando" else codigo)
