"""Endpoints de la bandeja: `/conversaciones/*` y `/atencion/*` (fase-2b.md §4.8, §4.10, §4.11)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogos import MOTIVOS_COLA
from app.db import get_db
from app.dependencias import requiere_rol, usuario_actual
from app.errores import ErrorApp, error_validacion
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.consola import servicio as consola
from app.modulos.consola.esquemas import FichaCliente
from app.modulos.conversaciones import atencion, cierre, salidas, servicio
from app.modulos.conversaciones.esquemas import (
    AsignarEntrada,
    CampanaRef,
    CierreConversacion,
    CierreConversacionCrear,
    Conversacion,
    ConversacionResumen,
    ItemCola,
    Mensaje,
    MensajeTextoCrear,
    OptOutEntrada,
    PaginaMensajes,
    PlantillaEnvioCrear,
    RegistroCandidato,
    ResultadoEnvioPlantilla,
    VincularRegistro,
)
from app.modulos.conversaciones.modelos import ColaAtencion
from app.modulos.conversaciones.modelos import Conversacion as ConversacionModelo
from app.modulos.conversaciones.modelos import Mensaje as MensajeModelo
from app.modulos.conversaciones.resolucion import candidatos
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import servicio_autorizaciones, servicio_envio, servicio_medios
from app.modulos.whatsapp.esquemas import AutorizacionConversacionCrear, AutorizacionSalida
from app.paginacion import IdRuta, Pagina, Paginacion, paginar
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/conversaciones", tags=["conversaciones"])
router_atencion = APIRouter(prefix="/atencion", tags=["atención"])
Cualquiera = Annotated[Usuario, Depends(usuario_actual)]
Gestor = Annotated[Usuario, Depends(requiere_rol("administrador", "supervisor"))]
Agente = Annotated[Usuario, Depends(requiere_rol("agente"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]


def _conversacion(db: Session, conv: ConversacionModelo, usuario: Usuario, ahora: datetime):
    return salidas.conversacion_salida(db, conv, usuario, ahora)


# ---- Lectura -----------------------------------------------------------------------------------
@router.get("", response_model=Pagina[ConversacionResumen])
def listar(
    usuario: Cualquiera,
    params: Paginacion,
    db: Db,
    reloj: RelojDep,
    estado: Literal["abierta", "cerrada"] = "abierta",
    atendida_por: Literal["sin_asignar", "humano", "ia"] | None = None,
    campana_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    sin_campana: bool | None = None,
    usuario_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
) -> Pagina[ConversacionResumen]:
    consulta = select(ConversacionModelo).where(ConversacionModelo.estado == estado)
    if usuario.rol == "agente":
        # Filtro implícito: solo las suyas (se ignoran `usuario_id` y `sin_campana`).
        consulta = consulta.where(ConversacionModelo.usuario_asignado_id == usuario.id)
    else:
        if usuario_id is not None:
            consulta = consulta.where(ConversacionModelo.usuario_asignado_id == usuario_id)
        if sin_campana:
            consulta = consulta.where(ConversacionModelo.campana_id.is_(None))
    if atendida_por is not None:
        consulta = consulta.where(ConversacionModelo.atendida_por == atendida_por)
    if campana_id is not None:
        consulta = consulta.where(ConversacionModelo.campana_id == campana_id)
    consulta = consulta.order_by(
        ConversacionModelo.ultimo_mensaje_en.desc(), ConversacionModelo.id.desc()
    )
    filas, total = paginar(db, consulta, params)
    return Pagina(
        items=salidas.resumenes(db, filas, usuario, reloj()),
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{conversacion_id}", response_model=Conversacion)
def ver(
    conversacion_id: IdRuta,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
    apertura: bool = False,
) -> Conversacion:
    """`apertura=true` (solo al abrir la conversación en la bandeja) audita `conversacion.ver`;
    las recargas y los refrescos por eventos no auditan."""
    conv = servicio.cargar(db, conversacion_id)
    servicio.exigir_acceso(conv, usuario)
    if apertura:
        auditoria.registrar(
            db,
            "conversacion.ver",
            usuario.id,
            "conversacion",
            conv.id,
            {"conversacion_id": conv.id},
        )
        db.commit()
    return _conversacion(db, conv, usuario, reloj())


@router.get("/{conversacion_id}/mensajes", response_model=PaginaMensajes)
def mensajes(
    conversacion_id: IdRuta,
    usuario: Cualquiera,
    db: Db,
    antes_de: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PaginaMensajes:
    conv = servicio.cargar(db, conversacion_id)
    servicio.exigir_acceso(conv, usuario)
    consulta = select(MensajeModelo).where(MensajeModelo.conversacion_id == conv.id)
    if antes_de is not None:
        consulta = consulta.where(MensajeModelo.id < antes_de)
    filas = list(db.scalars(consulta.order_by(MensajeModelo.id.desc()).limit(limite + 1)))
    hay_mas = len(filas) > limite
    return PaginaMensajes(
        items=salidas.mensajes_salida(db, list(reversed(filas[:limite]))), hay_mas=hay_mas
    )


@router.post("/{conversacion_id}/leida", status_code=204)
def leida(conversacion_id: IdRuta, usuario: Cualquiera, db: Db) -> Response:
    servicio.marcar_leida(db, usuario, conversacion_id)
    return Response(status_code=204)


# ---- Dueño -------------------------------------------------------------------------------------
@router.post("/{conversacion_id}/tomar", response_model=Conversacion)
def tomar(conversacion_id: IdRuta, usuario: Cualquiera, db: Db, reloj: RelojDep) -> Conversacion:
    ahora = reloj()
    conv = servicio.tomar(db, usuario, conversacion_id, ahora)
    return _conversacion(db, conv, usuario, ahora)


@router.post("/{conversacion_id}/asignar", response_model=Conversacion)
def asignar(
    conversacion_id: IdRuta, datos: AsignarEntrada, usuario: Gestor, db: Db, reloj: RelojDep
) -> Conversacion:
    ahora = reloj()
    conv = servicio.asignar(db, usuario, conversacion_id, datos.usuario_id, ahora)
    return _conversacion(db, conv, usuario, ahora)


@router.post("/{conversacion_id}/liberar", response_model=Conversacion)
def liberar(conversacion_id: IdRuta, usuario: Cualquiera, db: Db, reloj: RelojDep) -> Conversacion:
    ahora = reloj()
    conv = servicio.liberar(db, usuario, conversacion_id, ahora)
    return _conversacion(db, conv, usuario, ahora)


@router.post("/{conversacion_id}/cerrar", response_model=CierreConversacion)
def cerrar(
    conversacion_id: IdRuta,
    datos: CierreConversacionCrear,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
) -> CierreConversacion:
    ahora = reloj()
    conv, tip = cierre.cerrar_conversacion(db, usuario, conversacion_id, datos.tipificacion, ahora)
    return CierreConversacion(
        conversacion=_conversacion(db, conv, usuario, ahora), tipificacion=tip
    )


# ---- Registro ----------------------------------------------------------------------------------
@router.get("/{conversacion_id}/registros-candidatos", response_model=list[RegistroCandidato])
def registros_candidatos(
    conversacion_id: IdRuta, usuario: Cualquiera, db: Db
) -> list[RegistroCandidato]:
    conv = servicio.cargar(db, conversacion_id)
    if usuario.rol == "agente":
        servicio.exigir_dueno(conv, usuario)
    resultado = []
    for c in candidatos(db, conv.numero_cliente_e164):
        if usuario.rol == "agente" and not servicio.agente_asignado(db, usuario.id, c.campana.id):
            continue
        resultado.append(
            RegistroCandidato(
                campana_cliente_id=c.campana_cliente.id,
                campana=CampanaRef(id=c.campana.id, nombre=c.campana.nombre, tipo=c.campana.tipo),  # type: ignore[arg-type]
                cliente_nombre=c.cliente.nombre,
                estado=c.campana_cliente.estado,  # type: ignore[arg-type]
            )
        )
    return resultado


@router.put("/{conversacion_id}/registro", response_model=Conversacion)
def vincular(
    conversacion_id: IdRuta, datos: VincularRegistro, usuario: Cualquiera, db: Db, reloj: RelojDep
) -> Conversacion:
    ahora = reloj()
    conv = servicio.vincular(db, usuario, conversacion_id, datos.campana_cliente_id, ahora)
    return _conversacion(db, conv, usuario, ahora)


@router.get("/{conversacion_id}/ficha", response_model=FichaCliente)
def ficha(conversacion_id: IdRuta, usuario: Cualquiera, db: Db, reloj: RelojDep) -> FichaCliente:
    conv = servicio.cargar(db, conversacion_id)
    servicio.exigir_acceso(conv, usuario)
    cc = db.get(CampanaCliente, conv.campana_cliente_id) if conv.campana_cliente_id else None
    campana = db.get(Campana, cc.campana_id) if cc else None
    if cc is None or campana is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "La conversación no tiene un registro vinculado.")
    ahora = reloj()
    resultado = consola.construir_ficha(db, cc, campana, usuario, ahora)
    auditoria.registrar(
        db,
        "consola.ficha_ver",
        usuario.id,
        "campana_cliente",
        cc.id,
        {"campana_cliente_id": cc.id, "conversacion_id": conv.id},
    )
    db.commit()
    return resultado


# ---- Envío -------------------------------------------------------------------------------------
@router.post("/{conversacion_id}/mensajes", response_model=Mensaje, status_code=202)
def enviar_texto(
    conversacion_id: IdRuta,
    datos: MensajeTextoCrear,
    response: Response,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
) -> Mensaje:
    mensaje, creado = servicio_envio.enviar_texto(
        db, usuario, conversacion_id, datos.texto, datos.idempotencia_clave, reloj()
    )
    if not creado:
        response.status_code = 200
    return salidas.mensaje_salida(db, mensaje)


@router.post("/{conversacion_id}/plantillas", response_model=ResultadoEnvioPlantilla)
def enviar_plantilla(
    conversacion_id: IdRuta,
    datos: PlantillaEnvioCrear,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
) -> ResultadoEnvioPlantilla:
    return servicio_envio.enviar_plantilla_conversacion(
        db, usuario, conversacion_id, datos.plantilla_id, datos.idempotencia_clave, reloj()
    )


# ---- Opt-out y autorización --------------------------------------------------------------------
@router.post("/{conversacion_id}/opt-out", response_model=Conversacion)
def opt_out(
    conversacion_id: IdRuta, datos: OptOutEntrada, usuario: Cualquiera, db: Db, reloj: RelojDep
) -> Conversacion:
    ahora = reloj()
    conv = servicio_autorizaciones.opt_out_manual(
        db, usuario, conversacion_id, datos.alcance, ahora
    )
    return _conversacion(db, conv, usuario, ahora)


@router.post("/{conversacion_id}/autorizacion", response_model=AutorizacionSalida, status_code=201)
def autorizacion(
    conversacion_id: IdRuta,
    datos: AutorizacionConversacionCrear,
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
) -> AutorizacionSalida:
    return servicio_autorizaciones.crear_desde_conversacion(
        db, usuario, conversacion_id, datos.finalidad, datos.evidencia, reloj()
    )


# ---- Medios ------------------------------------------------------------------------------------
@router.get("/{conversacion_id}/mensajes/{mensaje_id}/media/{indice}")
def media(
    conversacion_id: IdRuta,
    mensaje_id: IdRuta,
    indice: Annotated[int, Path(ge=0, le=9)],
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
) -> Response:
    medio = servicio_medios.descargar(db, usuario, conversacion_id, mensaje_id, indice, reloj())
    return Response(content=medio.contenido, headers=medio.cabeceras)


# ---- Cola de atención --------------------------------------------------------------------------
@router_atencion.get("/cola", response_model=list[ItemCola])
def cola(
    usuario: Cualquiera,
    db: Db,
    reloj: RelojDep,
    campana_id: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
    motivo: str | None = None,
) -> list[ItemCola]:
    if motivo is not None and motivo not in MOTIVOS_COLA:
        raise error_validacion("motivo", "Motivo de cola desconocido.")
    ahora = reloj()
    consulta = (
        select(ColaAtencion, ConversacionModelo.numero_cliente_e164, Campana.nombre)
        .join(ConversacionModelo, ConversacionModelo.id == ColaAtencion.conversacion_id)
        .outerjoin(Campana, Campana.id == ColaAtencion.campana_id)
        .where(ColaAtencion.estado == "pendiente")
    )
    if usuario.rol == "agente":
        consulta = consulta.where(
            ColaAtencion.campana_id.in_(atencion.campanas_atendibles_por(db, usuario.id))
        )
    if campana_id is not None:
        consulta = consulta.where(ColaAtencion.campana_id == campana_id)
    if motivo is not None:
        consulta = consulta.where(ColaAtencion.motivo == motivo)
    consulta = consulta.order_by(ColaAtencion.prioridad, ColaAtencion.creado_en, ColaAtencion.id)
    return [
        ItemCola(
            id=fila.id,
            conversacion_id=fila.conversacion_id,
            campana={"id": fila.campana_id, "nombre": nombre} if fila.campana_id else None,
            motivo=fila.motivo,
            prioridad=fila.prioridad,
            resumen=fila.resumen,
            numero_mascara=consola.enmascarar_telefono(numero),
            creado_en=fila.creado_en,
            espera_segundos=max(int((ahora - fila.creado_en).total_seconds()), 0),
        )
        for fila, numero, nombre in db.execute(consulta).all()
    ]


@router_atencion.post("/tomar-siguiente", response_model=Conversacion, responses={204: {}})
def tomar_siguiente(usuario: Agente, db: Db, reloj: RelojDep):
    ahora = reloj()
    conv = atencion.tomar_siguiente(db, usuario, ahora)
    if conv is None:
        return Response(status_code=204)
    return _conversacion(db, conv, usuario, ahora)
