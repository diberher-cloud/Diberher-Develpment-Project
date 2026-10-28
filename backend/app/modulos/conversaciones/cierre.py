"""Cierre de una conversación con tipificación (`canal=whatsapp_mensaje`), fase-2b.md §4.8.

Orden de bloqueos: cliente sin bloquear -> `clientes` FOR UPDATE -> `conversaciones` FOR UPDATE
(se revalida que el cliente no cambió) -> tipificación.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalle
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import servicio as consola
from app.modulos.consola import tipificacion
from app.modulos.consola.esquemas import TipificacionDatos, TipificacionSalida
from app.modulos.conversaciones import servicio
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.usuarios.modelos import Usuario


def _bloquear_con_cliente(db: Session, usuario: Usuario, conversacion_id: int) -> Conversacion:
    for _ in range(3):
        previa = servicio.cargar(db, conversacion_id)
        if usuario.rol == "agente":
            servicio.exigir_dueno(previa, usuario)
        cliente_id = previa.cliente_id
        if cliente_id is not None:
            db.execute(select(Cliente.id).where(Cliente.id == cliente_id).with_for_update()).all()
        conv = servicio.bloquear(db, conversacion_id)
        if conv.cliente_id == cliente_id:
            return conv
        db.rollback()  # se vinculó un registro mientras esperábamos: reintentar
    raise ErrorApp(409, "CONVERSACION_CONCURRENTE", "La conversación cambió; reintente.")


def cerrar_conversacion(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    datos: TipificacionDatos | None,
    ahora: datetime,
) -> tuple[Conversacion, TipificacionSalida | None]:
    conv = _bloquear_con_cliente(db, usuario, conversacion_id)
    if usuario.rol == "agente":
        servicio.exigir_dueno(conv, usuario)
    servicio.exigir_abierta(conv)
    tiene_registro = conv.campana_cliente_id is not None
    if tiene_registro and datos is None:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [
                detalle(
                    "tipificacion", "La tipificación es obligatoria si hay un registro vinculado."
                )
            ],
        )
    if not tiene_registro and datos is not None:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("tipificacion", "No aplica: la conversación no tiene registro vinculado.")],
        )
    salida: TipificacionSalida | None = None
    publicar: tuple[int, int, bool] | None = None
    if datos is not None:
        cc = db.get(CampanaCliente, conv.campana_cliente_id)
        campana = db.get(Campana, cc.campana_id) if cc else None
        assert cc is not None and campana is not None
        db.refresh(cc)
        hay_entrantes = (
            db.scalar(
                select(Mensaje.id)
                .where(Mensaje.conversacion_id == conv.id, Mensaje.direccion == "entrante")
                .limit(1)
            )
            is not None
        )

        def coherencia() -> None:
            if hay_entrantes and datos.resultado == "no_contesta":
                raise ErrorApp(
                    422,
                    "RESULTADO_INCOHERENTE",
                    "El cliente escribió: el resultado no puede ser 'no_contesta'.",
                )
            if not hay_entrantes and datos.resultado != "no_contesta":
                raise ErrorApp(
                    422,
                    "RESULTADO_INCOHERENTE",
                    "El cliente no escribió: el único resultado posible es 'no_contesta'.",
                )

        val = tipificacion.validar_comun(db, datos, cc, campana, ahora, coherencia)
        telefono = db.get(Telefono, conv.telefono_id) if conv.telefono_id else None
        aplicada = tipificacion.aplicar_efectos(
            db,
            datos,
            val,
            cc,
            campana,
            telefono,
            ahora,
            canal="whatsapp_mensaje",
            origen="agente",
            actor_id=usuario.id,
            gestor_id=usuario.id,
            conversacion_id=conv.id,
        )
        if conv.intento_contacto_id is not None:
            intento = db.get(IntentoContacto, conv.intento_contacto_id)
            if intento is not None:
                intento.contacto_directo = (
                    intento.contacto_directo or aplicada.efecto.contacto_directo
                )
                intento.resultado = datos.resultado
        auditoria.registrar(
            db,
            "tipificacion.crear",
            usuario.id,
            "tipificacion",
            aplicada.tip.id,
            {
                "tipificacion_id": aplicada.tip.id,
                "conversacion_id": conv.id,
                "resultado": datos.resultado,
            },
        )
        salida = tipificacion._salida(aplicada.tip, aplicada.promesa, aplicada.venta, cc)
        if aplicada.es_dueno:
            publicar = (campana.id, cc.id, aplicada.efecto.cierra_registro)
    motivo = "agente" if usuario.rol == "agente" else "supervisor"
    servicio.cerrar(db, conv, motivo, usuario.id, ahora)
    auditoria.registrar(
        db,
        "conversacion.cerrar",
        usuario.id,
        "conversacion",
        conv.id,
        {"conversacion_id": conv.id, "motivo_cierre": motivo, "tipificada": datos is not None},
    )
    if publicar is not None:
        consola.publicar_registro(
            db, publicar[0], publicar[1], "gestionado" if publicar[2] else "liberado"
        )
    db.commit()
    return conv, salida
