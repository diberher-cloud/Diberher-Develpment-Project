"""Supervisión en vivo del agente IA (fase-2c.md §6.5 y §6.8)."""

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalle
from app.modulos.agente_ia import arrendamiento
from app.modulos.agente_ia.contexto import RefInteraccion
from app.modulos.agente_ia.esquemas import (
    AccionIA as AccionSalida,
)
from app.modulos.agente_ia.esquemas import (
    ConversacionIAResumen,
    FilaHistorialSalida,
    GestionIA,
    IAResumen,
    Importe,
    ImporteVenta,
    Instruccion,
    LlamadaModelo,
    MetricasIA,
    Tiempos,
    Tokens,
    TotalUso,
    UltimaAccion,
    UsoIAConversacion,
)
from app.modulos.agente_ia.modelos import (
    AccionIA,
    ErrorIA,
    HistorialIA,
    InstruccionSupervisor,
    UsoIA,
)
from app.modulos.auditoria import servicio as auditoria
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.consola.modelos import PromesaPago, Tipificacion, Venta
from app.modulos.conversaciones import salidas, servicio
from app.modulos.conversaciones.esquemas import UsuarioRef
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import ParamsPaginacion, paginar

MOTIVOS_IA = (
    "solicitud_cliente",
    "queja",
    "ia_no_resuelve",
    "identidad_bloqueada",
    "ia_rechazo",
    "ia_max_tokens",
    "ia_iteraciones",
    "ia_stop_inesperado",
    "ia_monto_no_respaldado",
    "ia_error",
    "presupuesto_excedido",
    "ia_desactivada",
)
CONSULTAS_SENSIBLES = ("consultar_obligacion", "consultar_historial_gestiones")


def _validacion(campo: str, mensaje: str) -> ErrorApp:
    return ErrorApp(
        422, "VALIDACION", "Los datos enviados no son válidos.", [detalle(campo, mensaje)]
    )


# ---- Listado -----------------------------------------------------------------------------------
def _rango(db: Session, desde: date | None, hasta: date | None, tipo: str = "cobranza"):
    politica, _ = cumplimiento.cargar_politica(db, tipo)
    zona = ZoneInfo(politica.zona_horaria)
    ini = datetime.combine(desde, time.min, tzinfo=zona) if desde else None
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=zona) if hasta else None
    return ini, fin


def listar_conversaciones(
    db: Session,
    usuario: Usuario,
    params: ParamsPaginacion,
    ahora: datetime,
    *,
    campana_id: int | None,
    estado: str,
    atendida_por: str,
    con_gestion: bool | None,
    identidad: str | None,
    desde: date | None,
    hasta: date | None,
) -> tuple[list[ConversacionIAResumen], int]:
    c = Conversacion
    consulta = select(c).where(c.modelo_ia.is_not(None), c.estado == estado)
    if atendida_por != "todas":
        consulta = consulta.where(c.atendida_por == atendida_por)
    if campana_id is not None:
        consulta = consulta.where(c.campana_id == campana_id)
    if con_gestion is not None:
        existe = select(Tipificacion.id).where(Tipificacion.conversacion_id == c.id).exists()
        consulta = consulta.where(existe if con_gestion else ~existe)
    if identidad == "verificada":
        consulta = consulta.where(c.identidad_verificada.is_(True))
    elif identidad == "no_verificada":
        consulta = consulta.where(c.identidad_verificada.is_(False))
    ini, fin = _rango(db, desde, hasta)
    if ini:
        consulta = consulta.where(c.abierta_en >= ini)
    if fin:
        consulta = consulta.where(c.abierta_en < fin)
    consulta = consulta.order_by(c.ultimo_mensaje_en.desc(), c.id.desc())
    filas, total = paginar(db, consulta, params)
    bases = salidas.resumenes(db, filas, usuario, ahora)
    items = []
    for conv, base in zip(filas, bases, strict=True):
        ref = RefInteraccion("conversacion", conv.id)
        ultima = db.scalar(
            select(AccionIA)
            .where(AccionIA.conversacion_id == conv.id)
            .order_by(AccionIA.id.desc())
            .limit(1)
        )
        pendientes = db.scalar(
            select(func.count(InstruccionSupervisor.id)).where(
                InstruccionSupervisor.conversacion_id == conv.id,
                InstruccionSupervisor.aplicada_en.is_(None),
            )
        )
        items.append(
            ConversacionIAResumen(
                **base.model_dump(),
                ia=IAResumen(
                    identidad_verificada=conv.identidad_verificada,
                    turnos=conv.turnos_ia,
                    costo_usd=conv.costo_usd_acumulado,
                    modelo=conv.modelo_ia or "",
                    gestion=gestion_de(db, conv.id),
                    ultima_accion=(
                        UltimaAccion(
                            herramienta=ultima.herramienta,
                            es_error=ultima.es_error,
                            creado_en=ultima.creado_en,
                        )
                        if ultima
                        else None
                    ),
                    turno_en_curso=arrendamiento.vigente(db, ref, ahora),
                    instrucciones_pendientes=pendientes or 0,
                ),
            )
        )
    return items, total


def gestion_de(db: Session, conversacion_id: int) -> GestionIA | None:
    t = db.scalar(select(Tipificacion).where(Tipificacion.conversacion_id == conversacion_id))
    return GestionIA(resultado=t.resultado, tipificacion_id=t.id) if t else None


# ---- Acciones, uso, historial ------------------------------------------------------------------
def acciones(db: Session, usuario: Usuario, conv: Conversacion) -> list[AccionSalida]:
    servicio.exigir_acceso(conv, usuario)
    ve_todo = usuario.rol in ("administrador", "supervisor")
    salida = []
    for a in db.scalars(
        select(AccionIA).where(AccionIA.conversacion_id == conv.id).order_by(AccionIA.id)
    ):
        oculto = not ve_todo and a.herramienta in CONSULTAS_SENSIBLES
        salida.append(
            AccionSalida(
                id=a.id,
                tool_use_id=a.tool_use_id,
                herramienta=a.herramienta,
                entrada=a.entrada,
                resultado=None if oculto else a.resultado,
                es_error=a.es_error,
                codigo_error=a.codigo_error,
                efecto=a.efecto,
                referencia=(
                    {"tipo": a.referencia_tipo, "id": a.referencia_id}
                    if a.referencia_tipo
                    else None
                ),
                duracion_ms=a.duracion_ms,
                creado_en=a.creado_en,
            )
        )
    return salida


def tasa_cache(entrada: int, lectura: int, escritura: int) -> float | None:
    total = entrada + lectura + escritura
    return round(lectura / total, 4) if total else None


def uso(db: Session, conv: Conversacion) -> UsoIAConversacion:
    filas = list(
        db.scalars(select(UsoIA).where(UsoIA.conversacion_id == conv.id).order_by(UsoIA.id))
    )
    entrada = sum(f.input_tokens for f in filas)
    salida = sum(f.output_tokens for f in filas)
    escritura = sum(f.cache_creation_input_tokens for f in filas)
    lectura = sum(f.cache_read_input_tokens for f in filas)
    return UsoIAConversacion(
        total=TotalUso(
            llamadas=len(filas),
            input_tokens=entrada,
            output_tokens=salida,
            cache_creation_input_tokens=escritura,
            cache_read_input_tokens=lectura,
            costo_usd=sum((f.costo_usd for f in filas), Decimal(0)),
            tasa_cache=tasa_cache(entrada, lectura, escritura),
        ),
        llamadas=[
            LlamadaModelo(
                id=f.id,
                iteracion=f.iteracion,
                modelo=f.modelo,
                modelo_servido=f.modelo_servido,
                stop_reason=f.stop_reason,
                input_tokens=f.input_tokens,
                output_tokens=f.output_tokens,
                cache_creation_input_tokens=f.cache_creation_input_tokens,
                cache_read_input_tokens=f.cache_read_input_tokens,
                costo_usd=f.costo_usd,
                duracion_ms=f.duracion_ms,
                request_id=f.request_id,
                creado_en=f.creado_en,
            )
            for f in filas
        ],
    )


def _sin_thinking(contenido):
    if not isinstance(contenido, list):
        return contenido
    return [
        {"type": "thinking", "omitido": True}
        if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
        else b
        for b in contenido
    ]


def ver_historial(db: Session, usuario: Usuario, conv: Conversacion) -> list[FilaHistorialSalida]:
    auditoria.registrar(
        db, "ia.historial_ver", usuario.id, "conversacion", conv.id, {"conversacion_id": conv.id}
    )
    db.commit()
    return [
        FilaHistorialSalida(
            secuencia=f.secuencia,
            rol=f.rol,
            tipo=f.tipo,
            contenido=_sin_thinking(f.contenido),
            creado_en=f.creado_en,
        )
        for f in db.scalars(
            select(HistorialIA)
            .where(HistorialIA.conversacion_id == conv.id)
            .order_by(HistorialIA.secuencia)
        )
    ]


# ---- Instrucciones -----------------------------------------------------------------------------
def _instruccion(db: Session, i: InstruccionSupervisor) -> Instruccion:
    u = db.get(Usuario, i.usuario_id)
    assert u is not None and i.conversacion_id is not None
    return Instruccion(
        id=i.id,
        conversacion_id=i.conversacion_id,
        usuario=UsuarioRef(id=u.id, nombre=u.nombre),
        texto=i.texto,
        creado_en=i.creado_en,
        aplicada_en=i.aplicada_en,
    )


def listar_instrucciones(db: Session, conv: Conversacion) -> list[Instruccion]:
    return [
        _instruccion(db, i)
        for i in db.scalars(
            select(InstruccionSupervisor)
            .where(InstruccionSupervisor.conversacion_id == conv.id)
            .order_by(InstruccionSupervisor.id)
        )
    ]


def instruir(
    db: Session, usuario: Usuario, conversacion_id: int, texto: str, ahora: datetime
) -> Instruccion:
    servicio.cargar(db, conversacion_id)
    conv = servicio.bloquear(db, conversacion_id)
    limpio = texto.strip()
    if not 1 <= len(limpio) <= 1000:
        raise _validacion("texto", "Debe tener entre 1 y 1000 caracteres.")
    servicio.exigir_abierta(conv)
    if conv.atendida_por != "ia":
        raise ErrorApp(409, "CONVERSACION_NO_IA", "La conversación no la atiende la IA.")
    fila = InstruccionSupervisor(
        conversacion_id=conv.id, usuario_id=usuario.id, texto=limpio, creado_en=ahora
    )
    db.add(fila)
    db.flush()
    auditoria.registrar(
        db,
        "ia.instruccion",
        usuario.id,
        "conversacion",
        conv.id,
        {"conversacion_id": conv.id, "instruccion_id": fila.id},
    )
    db.commit()
    return _instruccion(db, fila)


# ---- Métricas ----------------------------------------------------------------------------------
def _percentil(valores: list[int], p: float) -> int | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[max(math.ceil(p * len(ordenados)) - 1, 0)]


def metricas(
    db: Session,
    campana_id: int | None,
    desde: date | None,
    hasta: date | None,
    ahora: datetime,
) -> MetricasIA:
    if campana_id is not None and db.get(Campana, campana_id) is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    politica, _ = cumplimiento.cargar_politica(db, "cobranza")
    hoy = ahora.astimezone(ZoneInfo(politica.zona_horaria)).date()
    desde, hasta = desde or hoy, hasta or hoy
    if desde > hasta:
        raise _validacion("desde", "No puede ser posterior a 'hasta'.")
    ini, fin = _rango(db, desde, hasta)
    c = Conversacion
    consulta = select(c).where(c.modelo_ia.is_not(None), c.abierta_en >= ini, c.abierta_en < fin)
    if campana_id is not None:
        consulta = consulta.where(c.campana_id == campana_id)
    convs = list(db.scalars(consulta))
    ids = [x.id for x in convs]

    resultados: dict[str, int] = {}
    monto_acuerdos, n_acuerdos = Decimal(0), 0
    valor_ventas, n_ventas = Decimal(0), 0
    derivaciones: dict[str, int] = {}
    entradas = salida = escritura = lectura = 0
    costo = Decimal(0)
    if ids:
        for t, p, v in db.execute(
            select(Tipificacion, PromesaPago, Venta)
            .outerjoin(PromesaPago, PromesaPago.tipificacion_id == Tipificacion.id)
            .outerjoin(Venta, Venta.tipificacion_id == Tipificacion.id)
            .where(Tipificacion.conversacion_id.in_(ids), Tipificacion.origen == "agente_ia")
        ):
            resultados[t.resultado] = resultados.get(t.resultado, 0) + 1
            if p is not None:
                n_acuerdos += 1
                monto_acuerdos += p.monto
            if v is not None:
                n_ventas += 1
                valor_ventas += v.valor
        for motivo, n in db.execute(
            select(ColaAtencion.motivo, func.count(ColaAtencion.id))
            .where(ColaAtencion.conversacion_id.in_(ids), ColaAtencion.motivo.in_(MOTIVOS_IA))
            .group_by(ColaAtencion.motivo)
        ):
            derivaciones[motivo] = n
        for u in db.scalars(select(UsoIA).where(UsoIA.conversacion_id.in_(ids))):
            entradas += u.input_tokens
            salida += u.output_tokens
            escritura += u.cache_creation_input_tokens
            lectura += u.cache_read_input_tokens
            costo += u.costo_usd
    tiempos = _tiempos_respuesta(db, ids)
    errores: dict[str, int] = {}
    consulta_err = select(ErrorIA.codigo, func.count(ErrorIA.id)).where(
        ErrorIA.creado_en >= ini, ErrorIA.creado_en < fin
    )
    if campana_id is not None:
        consulta_err = consulta_err.where(ErrorIA.campana_id == campana_id)
    for codigo, n in db.execute(consulta_err.group_by(ErrorIA.codigo)):
        errores[codigo] = n
    guardas: dict[str, int] = {}
    if ids:
        for fila in db.scalars(
            select(Auditoria).where(
                Auditoria.accion == "ia.guarda",
                Auditoria.creado_en >= ini,
                Auditoria.creado_en < fin,
            )
        ):
            if fila.detalle.get("conversacion_id") in ids:
                codigo = fila.detalle.get("codigo", "?")
                guardas[codigo] = guardas.get(codigo, 0) + 1
    verificadas = sum(1 for x in convs if x.identidad_verificada)
    return MetricasIA(
        campana_id=campana_id,
        desde=desde.isoformat(),
        hasta=hasta.isoformat(),
        conversaciones=len(convs),
        con_identidad_verificada=verificadas,
        tasa_verificacion=round(verificadas / len(convs), 4) if convs else None,
        acuerdos=Importe(numero=n_acuerdos, monto_total=monto_acuerdos),
        ventas=ImporteVenta(numero=n_ventas, valor_total=valor_ventas),
        resultados=resultados,
        derivaciones=derivaciones,
        opt_outs=sum(1 for x in convs if x.motivo_cierre == "opt_out"),
        cerradas_por_ia=sum(1 for x in convs if x.motivo_cierre == "sistema"),
        cerradas_por_inactividad=sum(1 for x in convs if x.motivo_cierre == "inactividad"),
        costo_usd=costo,
        costo_por_acuerdo_usd=(costo / n_acuerdos) if n_acuerdos else None,
        tokens=Tokens(
            entrada=entradas, salida=salida, cache_escritura=escritura, cache_lectura=lectura
        ),
        tasa_cache=tasa_cache(entradas, lectura, escritura),
        tiempo_respuesta_ms=Tiempos(p50=_percentil(tiempos, 0.5), p95=_percentil(tiempos, 0.95)),
        errores=errores,
        guardas=guardas,
    )


def _tiempos_respuesta(db: Session, ids: list[int]) -> list[int]:
    """Del `creado_en` del último entrante de cada turno al del mensaje `ia` siguiente."""
    if not ids:
        return []
    tiempos: list[int] = []
    ultimo: dict[int, datetime | None] = {}
    for m in db.scalars(
        select(Mensaje)
        .where(Mensaje.conversacion_id.in_(ids), Mensaje.autor.in_(("cliente", "ia")))
        .order_by(Mensaje.conversacion_id, Mensaje.id)
    ):
        if m.autor == "cliente":
            ultimo[m.conversacion_id] = m.creado_en
        elif ultimo.get(m.conversacion_id) is not None:
            tiempos.append(int((m.creado_en - ultimo[m.conversacion_id]).total_seconds() * 1000))
            ultimo[m.conversacion_id] = None
    return tiempos
