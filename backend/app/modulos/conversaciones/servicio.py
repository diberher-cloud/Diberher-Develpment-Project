"""Conversaciones: carga y permisos, creación, `cambiar_dueno` (ÚNICO punto de transición de
dueño), cierre, vinculación de registro y operaciones de la bandeja (fase-2b.md §3.3, §4.8).

Orden global de bloqueos: estados_agente -> clientes -> conversaciones -> cola_atencion ->
mensajes. Las funciones de este módulo asumen que quien las llama ya tiene bloqueada la
conversación (`bloquear`).
"""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.catalogos import MOTIVOS_COLA
from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente
from app.modulos.conversaciones import atencion
from app.modulos.conversaciones import dueno as dueno_mod
from app.modulos.conversaciones.dueno import IA, Dueno, Humano, SinAsignar
from app.modulos.conversaciones.modelos import Conversacion, Mensaje
from app.modulos.conversaciones.resolucion import candidatos
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.usuarios.modelos import Usuario
from app.tiempo_real import bus

__all__ = ["IA", "ConflictoDueno", "Humano", "SinAsignar"]


class ConflictoDueno(Exception):
    """El dueño cambió entre la lectura y la escritura (UPDATE condicional sin filas)."""


def clave_abierta(numero_cliente: str, numero_empresa: str) -> str:
    return f"{numero_cliente}|{numero_empresa}"


# ---- Carga y permisos --------------------------------------------------------------------------
def _no_encontrada() -> ErrorApp:
    return ErrorApp(404, "NO_ENCONTRADO", "Conversación no encontrada.")


def cargar(db: Session, conversacion_id: int) -> Conversacion:
    conv = db.get(Conversacion, conversacion_id)
    if conv is None:
        raise _no_encontrada()
    return conv


def bloquear(db: Session, conversacion_id: int) -> Conversacion:
    """`FOR UPDATE` con datos frescos (orden: tras estados_agente y clientes)."""
    conv = db.scalar(
        select(Conversacion)
        .where(Conversacion.id == conversacion_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if conv is None:
        raise _no_encontrada()
    return conv


def es_dueno(conv: Conversacion, usuario: Usuario) -> bool:
    return conv.atendida_por == "humano" and conv.usuario_asignado_id == usuario.id


def no_asignada() -> ErrorApp:
    return ErrorApp(403, "CONVERSACION_NO_ASIGNADA", "No es el dueño de la conversación.")


def exigir_dueno(conv: Conversacion, usuario: Usuario) -> None:
    if not es_dueno(conv, usuario):
        raise no_asignada()


def exigir_acceso(conv: Conversacion, usuario: Usuario) -> None:
    """Lectura: A/S ven todo; el agente solo las suyas."""
    if usuario.rol != "agente" and usuario.rol in ("administrador", "supervisor"):
        return
    if not es_dueno(conv, usuario):
        raise no_asignada()


def exigir_abierta(conv: Conversacion) -> None:
    if conv.estado != "abierta":
        raise ErrorApp(409, "CONVERSACION_CERRADA", "La conversación está cerrada.")


def agente_asignado(db: Session, usuario_id: int, campana_id: int) -> bool:
    return (
        db.scalar(
            select(CampanaAgente.id).where(
                CampanaAgente.campana_id == campana_id, CampanaAgente.usuario_id == usuario_id
            )
        )
        is not None
    )


# ---- Eventos -----------------------------------------------------------------------------------
def publicar_estado(
    db: Session, conv: Conversacion, usuario_anterior_id: int | None = None
) -> None:
    bus.publicar(
        db,
        "conversacion.estado",
        {
            "conversacion_id": conv.id,
            "campana_id": conv.campana_id,
            "estado": conv.estado,
            "atendida_por": conv.atendida_por,
            "usuario_asignado_id": conv.usuario_asignado_id,
            "usuario_anterior_id": usuario_anterior_id,
            "motivo_cierre": conv.motivo_cierre,
        },
    )


def publicar_mensaje(db: Session, conv: Conversacion, mensaje: Mensaje, accion: str) -> None:
    bus.publicar(
        db,
        "conversacion.mensaje",
        {
            "conversacion_id": conv.id,
            "mensaje_id": mensaje.id,
            "campana_id": conv.campana_id,
            "usuario_asignado_id": conv.usuario_asignado_id,
            "direccion": mensaje.direccion,
            "autor": mensaje.autor,
            "estado": mensaje.estado,
            "accion": accion,
        },
    )


# ---- Creación ----------------------------------------------------------------------------------
def crear_conversacion(
    db: Session,
    *,
    numero_cliente: str,
    numero_empresa: str,
    iniciada_por: str,
    ahora: datetime,
    dueno: Dueno,
    nombre_perfil: str | None = None,
    cliente_id: int | None = None,
    campana_id: int | None = None,
    campana_cliente_id: int | None = None,
    telefono_id: int | None = None,
    intento_contacto_id: int | None = None,
) -> Conversacion:
    """Apertura (no es una transición): el dueño inicial lo decide `decidir_dueno_inicial`.
    Hace `flush` (puede fallar por la UNIQUE de `clave_abierta`); quien la llama publica los
    eventos una vez confirmada la creación. Si el dueño inicial es humano no hay fila de cola."""
    humano = isinstance(dueno, Humano)
    conv = Conversacion(
        clave_abierta=clave_abierta(numero_cliente, numero_empresa),
        numero_cliente_e164=numero_cliente,
        numero_empresa_e164=numero_empresa,
        nombre_perfil=nombre_perfil,
        cliente_id=cliente_id,
        campana_id=campana_id,
        campana_cliente_id=campana_cliente_id,
        telefono_id=telefono_id,
        estado="abierta",
        atendida_por=dueno_mod.nombre(dueno),
        usuario_asignado_id=dueno.usuario_id if isinstance(dueno, Humano) else None,
        asignada_en=ahora if humano else None,
        iniciada_por=iniciada_por,
        intento_contacto_id=intento_contacto_id,
        ultimo_mensaje_en=ahora,
        abierta_en=ahora,
    )
    db.add(conv)
    db.flush()
    return conv


# ---- Cambio de dueño (único punto) -------------------------------------------------------------
def cambiar_dueno(
    db: Session,
    conv: Conversacion,
    nuevo: Dueno,
    motivo_cola: str | None,
    actor_id: int | None,
    ahora: datetime,
) -> None:
    """Transición de dueño con efectos en la cola, auditoría y eventos (misma transacción).

    El UPDATE es condicional al dueño que se leyó: si cambió, lanza `ConflictoDueno`.
    `SinAsignar -> SinAsignar` con `motivo_cola` no cambia de dueño: (re)coloca la conversación
    en la cola con ese motivo (apertura de la cola de una conversación nueva, o vinculación de
    un registro a una conversación `sin_campana`).
    """
    exigir_abierta(conv)
    actual = dueno_mod.de_conversacion(conv)
    if actual == nuevo:
        if isinstance(nuevo, SinAsignar) and motivo_cola is not None:
            _recolocar_en_cola(db, conv, motivo_cola, ahora)
        return
    dueno_mod.validar_transicion(actual, nuevo)
    anterior_usuario = conv.usuario_asignado_id
    nuevo_usuario = nuevo.usuario_id if isinstance(nuevo, Humano) else None
    condicion = [
        Conversacion.id == conv.id,
        Conversacion.estado == "abierta",
        Conversacion.atendida_por == conv.atendida_por,
        (
            Conversacion.usuario_asignado_id.is_(None)
            if conv.usuario_asignado_id is None
            else Conversacion.usuario_asignado_id == conv.usuario_asignado_id
        ),
    ]
    r = db.execute(
        update(Conversacion)
        .where(*condicion)
        .values(
            atendida_por=dueno_mod.nombre(nuevo),
            usuario_asignado_id=nuevo_usuario,
            asignada_en=ahora if nuevo_usuario is not None else None,
        )
        .execution_options(synchronize_session=False)
    )
    if r.rowcount != 1:
        raise ConflictoDueno
    db.refresh(conv)

    fila = atencion.fila_activa(db, conv.id)
    if isinstance(nuevo, SinAsignar):
        motivo = motivo_cola or "liberada"
        if motivo not in MOTIVOS_COLA:
            raise ValueError("Motivo de cola desconocido.")
        if fila is not None:
            atencion.cerrar(db, fila, ahora)
        atencion.abrir(db, conv, motivo, ahora)
    elif isinstance(nuevo, Humano):
        if fila is not None:
            atencion.asignar(db, fila, nuevo.usuario_id, ahora)
    elif fila is not None:  # IA: la conversación sale de la cola
        atencion.cerrar(db, fila, ahora)
    auditoria.registrar(
        db,
        "conversacion.dueno",
        actor_id,
        "conversacion",
        conv.id,
        {
            "conversacion_id": conv.id,
            "de": dueno_mod.nombre(actual),
            "a": dueno_mod.nombre(nuevo),
            "motivo": motivo_cola,
        },
    )
    publicar_estado(db, conv, anterior_usuario)


def _recolocar_en_cola(db: Session, conv: Conversacion, motivo: str, ahora: datetime) -> None:
    fila = atencion.fila_activa(db, conv.id)
    if fila is not None and fila.motivo == motivo and fila.campana_id == conv.campana_id:
        return
    creado = fila.creado_en if fila is not None else None
    if fila is not None:
        atencion.cerrar(db, fila, ahora)
    atencion.abrir(db, conv, motivo, ahora, creado)


# ---- Cierre ------------------------------------------------------------------------------------
def cancelar_pendientes(db: Session, conversacion_id: int) -> None:
    db.execute(
        update(Mensaje)
        .where(
            Mensaje.conversacion_id == conversacion_id,
            Mensaje.estado.in_(("pendiente", "retenido")),
        )
        .values(estado="cancelado")
        .execution_options(synchronize_session=False)
    )


def cerrar(
    db: Session,
    conv: Conversacion,
    motivo: str,
    cerrada_por: int | None,
    ahora: datetime,
    cancelar: bool = True,
) -> None:
    """Cierre irreversible: cierra la cola y cancela los salientes pendientes/retenidos.
    Conserva `atendida_por` y `usuario_asignado_id`. Sin commit."""
    exigir_abierta(conv)
    conv.estado = "cerrada"
    conv.clave_abierta = None
    conv.cerrada_en = ahora
    conv.motivo_cierre = motivo
    conv.cerrada_por = cerrada_por
    db.flush()
    atencion.cerrar_activa(db, conv.id, ahora)
    if cancelar:
        cancelar_pendientes(db, conv.id)
    publicar_estado(db, conv)


# ---- Agente desconectado -----------------------------------------------------------------------
def liberar_del_agente(db: Session, usuario_id: int, ahora: datetime) -> int:
    """Al pasar el agente a `desconectado`, sus conversaciones abiertas vuelven a la cola
    (motivo `agente_desconectado`). Se llama con `estados_agente` ya bloqueado."""
    convs = list(
        db.scalars(
            select(Conversacion)
            .where(
                Conversacion.estado == "abierta",
                Conversacion.atendida_por == "humano",
                Conversacion.usuario_asignado_id == usuario_id,
            )
            .order_by(Conversacion.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for conv in convs:
        cambiar_dueno(db, conv, SinAsignar(), "agente_desconectado", None, ahora)
    return len(convs)


# ---- Operaciones de la bandeja -----------------------------------------------------------------
def auditar_tomar(db: Session, conv: Conversacion, usuario: Usuario) -> None:
    auditoria.registrar(
        db, "conversacion.tomar", usuario.id, "conversacion", conv.id, {"conversacion_id": conv.id}
    )


def tomar(db: Session, usuario: Usuario, conversacion_id: int, ahora: datetime) -> Conversacion:
    from app.modulos.consola import estado as estado_agente

    previa = cargar(db, conversacion_id)
    if es_dueno(previa, usuario) and previa.estado == "abierta":
        return previa
    if usuario.rol == "agente":
        if previa.campana_id is None:
            raise no_asignada()
        if not agente_asignado(db, usuario.id, previa.campana_id):
            raise ErrorApp(
                403, "CAMPANA_NO_ASIGNADA", "No está asignado a la campaña de la conversación."
            )
        estado_agente.bloquear(db, usuario.id)  # estados_agente primero
        if estado_agente.estado_actual(db, usuario.id) != "disponible":
            raise ErrorApp(
                409, "AGENTE_NO_DISPONIBLE", "El agente debe estar en estado 'disponible'."
            )
    conv = bloquear(db, conversacion_id)
    exigir_abierta(conv)
    if es_dueno(conv, usuario):
        return conv
    if conv.atendida_por != "sin_asignar":
        raise ErrorApp(409, "CONVERSACION_ASIGNADA", "La conversación ya la atiende otro usuario.")
    atencion.exigir_capacidad(db, usuario)
    try:
        cambiar_dueno(db, conv, Humano(usuario.id), None, usuario.id, ahora)
    except ConflictoDueno:
        db.rollback()
        raise ErrorApp(
            409, "CONVERSACION_ASIGNADA", "La conversación ya la atiende otro usuario."
        ) from None
    auditar_tomar(db, conv, usuario)
    db.commit()
    return conv


def asignar(
    db: Session, actor: Usuario, conversacion_id: int, usuario_id: int, ahora: datetime
) -> Conversacion:
    cargar(db, conversacion_id)
    conv = bloquear(db, conversacion_id)
    exigir_abierta(conv)
    destino = db.get(Usuario, usuario_id)
    if destino is None or not destino.activo:
        raise ErrorApp(
            422,
            "VALIDACION",
            "Los datos enviados no son válidos.",
            [detalle("usuario_id", "El usuario no existe o no está activo.")],
        )
    if destino.rol == "agente":
        if conv.campana_id is None:
            mensaje = "Solo un supervisor o administrador puede atender conversaciones sin campaña."
        elif not agente_asignado(db, destino.id, conv.campana_id):
            mensaje = "El agente no está asignado a la campaña."
        else:
            mensaje = ""
        if mensaje:
            raise ErrorApp(
                422,
                "VALIDACION",
                "Los datos enviados no son válidos.",
                [detalle("usuario_id", mensaje)],
            )
    if not es_dueno(conv, destino):
        try:
            cambiar_dueno(db, conv, Humano(destino.id), None, actor.id, ahora)
        except ConflictoDueno:
            db.rollback()
            raise ErrorApp(409, "CONVERSACION_ASIGNADA", "El dueño cambió; reintente.") from None
        auditoria.registrar(
            db,
            "conversacion.asignar",
            actor.id,
            "conversacion",
            conv.id,
            {"conversacion_id": conv.id, "usuario_id": destino.id},
        )
    db.commit()
    return conv


def liberar(db: Session, usuario: Usuario, conversacion_id: int, ahora: datetime) -> Conversacion:
    previa = cargar(db, conversacion_id)
    if usuario.rol == "agente" and not es_dueno(previa, usuario):
        raise no_asignada()
    conv = bloquear(db, conversacion_id)
    if usuario.rol == "agente":
        exigir_dueno(conv, usuario)
    exigir_abierta(conv)
    if conv.atendida_por == "humano":
        try:
            cambiar_dueno(db, conv, SinAsignar(), "liberada", usuario.id, ahora)
        except ConflictoDueno:
            db.rollback()
            raise ErrorApp(409, "CONVERSACION_ASIGNADA", "El dueño cambió; reintente.") from None
    db.commit()
    return conv


def marcar_leida(db: Session, usuario: Usuario, conversacion_id: int) -> None:
    cargar(db, conversacion_id)
    conv = bloquear(db, conversacion_id)
    exigir_dueno(conv, usuario)
    conv.mensajes_sin_leer = 0
    db.commit()


# ---- Vinculación de registro -------------------------------------------------------------------
def registrar_intento_entrante(
    db: Session, conv: Conversacion, cc: CampanaCliente, campana: Campana, telefono_id: int | None
) -> None:
    """Intento `iniciado_por=cliente` de una conversación que empezó el cliente."""
    politica, version = cumplimiento.cargar_politica(db, campana.tipo)
    intento = cumplimiento.registrar_intento(
        db,
        cliente_id=cc.cliente_id,
        tipo_campana=campana.tipo,
        canal="whatsapp_mensaje",
        iniciado_por="cliente",
        momento=conv.abierta_en,
        campana_id=campana.id,
        campana_cliente_id=cc.id,
        telefono_id=telefono_id,
        contacto_directo=politica.entrantes.establecen_contacto_directo,
        politica_version=version,
    )
    conv.intento_contacto_id = intento.id


def vincular_registro(
    db: Session, conv: Conversacion, candidato, actor_id: int | None, ahora: datetime
) -> None:
    """Fija cliente/campaña/registro/teléfono de la conversación. `candidato` es un
    `resolucion.Candidato`. Registra el intento si la conversación la inició el cliente."""
    conv.cliente_id = candidato.cliente.id
    conv.campana_id = candidato.campana.id
    conv.campana_cliente_id = candidato.campana_cliente.id
    conv.telefono_id = candidato.telefono.id
    db.flush()
    if conv.iniciada_por == "cliente":
        registrar_intento_entrante(
            db, conv, candidato.campana_cliente, candidato.campana, candidato.telefono.id
        )
        db.flush()


def vincular(
    db: Session,
    usuario: Usuario,
    conversacion_id: int,
    campana_cliente_id: int,
    ahora: datetime,
) -> Conversacion:
    previa = cargar(db, conversacion_id)
    if usuario.rol == "agente" and not es_dueno(previa, usuario):
        raise no_asignada()
    # Orden global de bloqueos: `clientes` del candidato ANTES que la conversación (igual que el
    # envío de plantilla); si no, vincular y una plantilla simultánea se interbloquean.
    elegido = next(
        (
            c
            for c in candidatos(db, previa.numero_cliente_e164)
            if c.campana_cliente.id == campana_cliente_id
        ),
        None,
    )
    if elegido is not None:
        db.execute(
            select(Cliente.id).where(Cliente.id == elegido.cliente.id).with_for_update()
        ).all()
    conv = bloquear(db, conversacion_id)
    exigir_abierta(conv)
    if conv.campana_cliente_id is not None:
        raise ErrorApp(
            409, "CONVERSACION_YA_VINCULADA", "La conversación ya está vinculada a un registro."
        )
    if elegido is None:
        raise ErrorApp(
            422,
            "REGISTRO_NO_COINCIDE",
            "El registro no tiene el número de la conversación.",
            [detalle("campana_cliente_id", "El registro no tiene el número de la conversación.")],
        )
    if usuario.rol == "agente" and not agente_asignado(db, usuario.id, elegido.campana.id):
        raise ErrorApp(
            403, "CAMPANA_NO_ASIGNADA", "No está asignado a la campaña de este registro."
        )
    vincular_registro(db, conv, elegido, usuario.id, ahora)
    fila = atencion.fila_activa(db, conv.id)
    if fila is not None:
        if fila.estado == "pendiente" and fila.motivo == "sin_campana":
            cambiar_dueno(db, conv, SinAsignar(), "entrante", usuario.id, ahora)
        else:
            fila.campana_id = conv.campana_id
    auditoria.registrar(
        db,
        "conversacion.vincular",
        usuario.id,
        "conversacion",
        conv.id,
        {"conversacion_id": conv.id, "campana_cliente_id": elegido.campana_cliente.id},
    )
    publicar_estado(db, conv)
    db.commit()
    return conv


def margen_ventana() -> timedelta:
    return timedelta(seconds=get_settings().whatsapp_margen_ventana_segundos)
