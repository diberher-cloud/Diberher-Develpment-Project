"""Plantillas de WhatsApp: sincronización con el proveedor, mapeo de variables a la lista blanca,
finalidad y activación (fase-2b.md §4.9)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp, detalle
from app.integraciones.whatsapp.proveedor import ErrorProveedorWhatsApp, ProveedorWhatsApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp import plantillas_render as render
from app.modulos.whatsapp.esquemas import (
    BotonSalida,
    PlantillaActualizar,
    PlantillaSalida,
    ResultadoSincronizacion,
)
from app.modulos.whatsapp.modelos import PlantillaWhatsApp


def _mapeo_completo(p: PlantillaWhatsApp) -> bool:
    return set(p.mapeo_variables or {}) == set(p.variables or []) and all(
        v in render.CAMPOS for v in (p.mapeo_variables or {}).values()
    )


def enviable(p: PlantillaWhatsApp) -> bool:
    """activa ∧ aprobada ∧ finalidad ∧ mapeo completo."""
    marketing_sin_baja = p.categoria == "marketing" and not p.tiene_boton_baja
    return (
        p.activa
        and p.estado_aprobacion == "aprobada"
        and p.finalidad is not None
        and _mapeo_completo(p)
        and not marketing_sin_baja
    )


def compatible_con(p: PlantillaWhatsApp, tipo_campana: str) -> bool:
    return p.finalidad in ("todas", tipo_campana)


def a_salida(p: PlantillaWhatsApp) -> PlantillaSalida:
    return PlantillaSalida(
        id=p.id,
        content_sid=p.content_sid,
        nombre=p.nombre,
        idioma=p.idioma,
        categoria=p.categoria,  # type: ignore[arg-type]
        estado_aprobacion=p.estado_aprobacion,  # type: ignore[arg-type]
        motivo_rechazo=p.motivo_rechazo,
        cuerpo=p.cuerpo,
        variables=list(p.variables or []),
        botones=[BotonSalida(**b) for b in (p.botones or [])],
        tiene_boton_baja=p.tiene_boton_baja,
        mapeo_variables=dict(p.mapeo_variables or {}),  # type: ignore[arg-type]
        finalidad=p.finalidad,  # type: ignore[arg-type]
        activa=p.activa,
        enviable=enviable(p),
        sincronizada_en=p.sincronizada_en,
    )


def obtener(db: Session, plantilla_id: int) -> PlantillaWhatsApp:
    p = db.get(PlantillaWhatsApp, plantilla_id)
    if p is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Plantilla no encontrada.")
    return p


def listar(
    db: Session,
    usuario: Usuario,
    campana_id: int | None,
    solo_enviables: bool | None,
) -> list[PlantillaSalida]:
    tipo: str | None = None
    if usuario.rol == "agente":
        if campana_id is None:
            raise ErrorApp(
                422,
                "VALIDACION",
                "Los datos enviados no son válidos.",
                [detalle("campana_id", "Campo obligatorio.")],
            )
        from app.modulos.conversaciones.servicio import agente_asignado

        if not agente_asignado(db, usuario.id, campana_id):
            raise ErrorApp(403, "CAMPANA_NO_ASIGNADA", "No está asignado a la campaña indicada.")
        solo_enviables = True
    if campana_id is not None:
        campana = db.get(Campana, campana_id)
        if campana is None:
            raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
        tipo = campana.tipo
    filas = db.scalars(
        select(PlantillaWhatsApp).order_by(PlantillaWhatsApp.nombre, PlantillaWhatsApp.id)
    )
    resultado = []
    for p in filas:
        if solo_enviables and not enviable(p):
            continue
        if (
            tipo is not None
            and (usuario.rol == "agente" or solo_enviables)
            and not compatible_con(p, tipo)
        ):
            continue
        resultado.append(a_salida(p))
    return resultado


# ---- Sincronización ----------------------------------------------------------------------------
def sincronizar(
    db: Session, proveedor: ProveedorWhatsApp, usuario: Usuario, ahora: datetime
) -> ResultadoSincronizacion:
    try:
        remotas = proveedor.listar_plantillas()
    except ErrorProveedorWhatsApp:
        raise ErrorApp(
            502, "PROVEEDOR_NO_DISPONIBLE", "No se pudo consultar al proveedor de WhatsApp."
        ) from None
    baja = get_settings().whatsapp_payload_baja
    existentes = {p.content_sid: p for p in db.scalars(select(PlantillaWhatsApp))}
    creadas = actualizadas = desactivadas = 0
    vistas: set[str] = set()
    for r in remotas:
        vistas.add(r.ref)
        botones = [{"tipo": b.tipo, "texto": b.texto, "payload": b.payload} for b in r.botones]
        tiene_baja = any(b.payload == baja for b in r.botones if b.payload)
        p = existentes.get(r.ref)
        if p is None:
            db.add(
                PlantillaWhatsApp(
                    content_sid=r.ref,
                    nombre=r.nombre,
                    idioma=r.idioma,
                    categoria=r.categoria,
                    estado_aprobacion=r.estado_aprobacion,
                    motivo_rechazo=r.motivo_rechazo,
                    cuerpo=r.cuerpo,
                    variables=list(r.variables),
                    botones=botones,
                    tiene_boton_baja=tiene_baja,
                    mapeo_variables={},
                    finalidad=None,
                    activa=False,
                    sincronizada_en=ahora,
                    actualizado_en=ahora,
                )
            )
            creadas += 1
            continue
        antes = (
            p.nombre, p.idioma, p.categoria, p.estado_aprobacion, p.motivo_rechazo, p.cuerpo,
            list(p.variables), p.botones, p.tiene_boton_baja,
        )  # fmt: skip
        cambio_contenido = p.cuerpo != r.cuerpo or list(p.variables) != list(r.variables)
        p.nombre, p.idioma, p.categoria = r.nombre, r.idioma, r.categoria
        p.estado_aprobacion, p.motivo_rechazo = r.estado_aprobacion, r.motivo_rechazo
        p.cuerpo, p.variables, p.botones = r.cuerpo, list(r.variables), botones
        p.tiene_boton_baja = tiene_baja
        despues = (
            p.nombre, p.idioma, p.categoria, p.estado_aprobacion, p.motivo_rechazo, p.cuerpo,
            list(p.variables), p.botones, p.tiene_boton_baja,
        )  # fmt: skip
        sin_baja = r.categoria == "marketing" and not tiene_baja
        desactivar = p.activa and (
            cambio_contenido or r.estado_aprobacion != "aprobada" or sin_baja
        )
        if p.activa and sin_baja:
            auditoria.registrar(
                db,
                "whatsapp.plantilla_desactivada",
                usuario.id,
                "plantilla_whatsapp",
                p.id,
                {"plantilla_id": p.id, "motivo": "marketing_sin_baja"},
            )
        if cambio_contenido:
            p.mapeo_variables = {}
        if desactivar:
            p.activa = False
            desactivadas += 1
        if antes != despues or desactivar:
            actualizadas += 1
        p.sincronizada_en = ahora
    for sid, p in existentes.items():
        if sid in vistas or p.estado_aprobacion == "eliminada":
            continue
        p.estado_aprobacion = "eliminada"
        p.sincronizada_en = ahora
        if p.activa:
            p.activa = False
            desactivadas += 1
        actualizadas += 1
    auditoria.registrar(
        db,
        "whatsapp.plantillas_sincronizar",
        usuario.id,
        "plantilla_whatsapp",
        None,
        {"creadas": creadas, "actualizadas": actualizadas, "desactivadas": desactivadas},
    )
    db.commit()
    return ResultadoSincronizacion(
        creadas=creadas, actualizadas=actualizadas, desactivadas=desactivadas
    )


# ---- Edición -----------------------------------------------------------------------------------
def actualizar(
    db: Session, plantilla_id: int, datos: PlantillaActualizar, usuario: Usuario, ahora: datetime
) -> PlantillaSalida:
    p = obtener(db, plantilla_id)
    campos = datos.model_dump(exclude_unset=True)
    if "finalidad" in campos and campos["finalidad"] is not None:
        p.finalidad = campos["finalidad"]
    if "mapeo_variables" in campos and campos["mapeo_variables"] is not None:
        mapeo = campos["mapeo_variables"]
        errores = []
        for clave in sorted(set(p.variables or []) - set(mapeo)):
            errores.append(detalle(f"mapeo_variables.{clave}", "Falta mapear la variable."))
        for clave, campo in mapeo.items():
            if clave not in (p.variables or []):
                errores.append(
                    detalle(f"mapeo_variables.{clave}", "La plantilla no tiene esa variable.")
                )
            elif campo not in render.CAMPOS:
                errores.append(
                    detalle(
                        f"mapeo_variables.{clave}",
                        "Campo no permitido; use: " + ", ".join(render.CAMPOS) + ".",
                    )
                )
        if errores:
            raise ErrorApp(
                422, "PLANTILLA_MAPEO_INVALIDO", "El mapeo de variables no es válido.", errores
            )
        p.mapeo_variables = dict(mapeo)
    if campos.get("activa") is True:
        if p.estado_aprobacion != "aprobada" or p.finalidad is None or not _mapeo_completo(p):
            raise ErrorApp(
                422,
                "PLANTILLA_NO_DISPONIBLE",
                "Para activar la plantilla debe estar aprobada, con finalidad y mapeo completo.",
            )
        if p.categoria == "marketing" and not p.tiene_boton_baja:
            raise ErrorApp(
                422,
                "PLANTILLA_SIN_BAJA",
                "Una plantilla de marketing debe incluir un botón de baja.",
            )
        p.activa = True
    elif campos.get("activa") is False:
        p.activa = False
    p.actualizado_por = usuario.id
    p.actualizado_en = ahora
    auditoria.registrar(
        db,
        "whatsapp.plantilla_actualizar",
        usuario.id,
        "plantilla_whatsapp",
        p.id,
        {"plantilla_id": p.id, "campos": sorted(campos)},
    )
    db.commit()
    return a_salida(p)


# ---- Valores de variables ------------------------------------------------------------------------
def valores_de_campos(cliente: Cliente, cc: CampanaCliente, usuario: Usuario) -> dict[str, str]:
    return {
        "primer_nombre": render.primera_palabra(cliente.nombre),
        "empresa": render.limpiar_valor(get_settings().empresa_nombre),
        "agente": render.primera_palabra(usuario.nombre),
        "producto": render.limpiar_valor(cc.producto),
    }


def calcular_variables(
    p: PlantillaWhatsApp, cliente: Cliente, cc: CampanaCliente, usuario: Usuario
) -> dict[str, str]:
    """Valores por variable (`{"1": "María"}`); 422 `PLANTILLA_VARIABLE_VACIA` si falta alguno."""
    campos = valores_de_campos(cliente, cc, usuario)
    resultado: dict[str, str] = {}
    for clave in p.variables or []:
        campo = (p.mapeo_variables or {}).get(clave)
        valor = campos.get(campo or "", "")
        if not valor:
            raise ErrorApp(
                422,
                "PLANTILLA_VARIABLE_VACIA",
                "Una variable de la plantilla no tiene valor para este registro.",
                [detalle("plantilla_id", f"Falta el valor de {{{{{clave}}}}} ({campo}).")],
            )
        resultado[clave] = valor
    return resultado
