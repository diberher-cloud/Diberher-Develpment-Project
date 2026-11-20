"""Supervisión en vivo del agente IA (fase-2c.md §6.5 y §6.8)."""

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.errores import ErrorApp, detalle
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
    BloqueoTurnoIA,
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
    ids = [conv.id for conv in filas]
    # Datos de la página en UNA consulta por tipo (sin N+1).
    gestiones = {
        t.conversacion_id: GestionIA(resultado=t.resultado, tipificacion_id=t.id)
        for t in db.scalars(select(Tipificacion).where(Tipificacion.conversacion_id.in_(ids)))
    }
    ultimas_ids = (
        select(func.max(AccionIA.id))
        .where(AccionIA.conversacion_id.in_(ids))
        .group_by(AccionIA.conversacion_id)
    )
    ultimas = {
        a.conversacion_id: a
        for a in db.scalars(select(AccionIA).where(AccionIA.id.in_(ultimas_ids)))
    }
    pendientes = dict(
        db.execute(
            select(InstruccionSupervisor.conversacion_id, func.count(InstruccionSupervisor.id))
            .where(
                InstruccionSupervisor.conversacion_id.in_(ids),
                InstruccionSupervisor.aplicada_en.is_(None),
            )
            .group_by(InstruccionSupervisor.conversacion_id)
        ).all()
    )
    en_curso = set(
        db.scalars(
            select(BloqueoTurnoIA.conversacion_id).where(
                BloqueoTurnoIA.conversacion_id.in_(ids), BloqueoTurnoIA.expira_en >= ahora
            )
        )
    )
    items = []
    for conv, base in zip(filas, bases, strict=True):
        ultima = ultimas.get(conv.id)
        items.append(
            ConversacionIAResumen(
                **base.model_dump(),
                ia=IAResumen(
                    identidad_verificada=conv.identidad_verificada,
                    turnos=conv.turnos_ia,
                    costo_usd=conv.costo_usd_acumulado,
                    modelo=conv.modelo_ia or "",
                    gestion=gestiones.get(conv.id),
                    ultima_accion=(
                        UltimaAccion(
                            herramienta=ultima.herramienta,
                            es_error=ultima.es_error,
                            creado_en=ultima.creado_en,
                        )
                        if ultima
                        else None
                    ),
                    turno_en_curso=conv.id in en_curso,
                    instrucciones_pendientes=pendientes.get(conv.id, 0),
                ),
            )
        )
    return items, total


def gestion_de(db: Session, conversacion_id: int) -> GestionIA | None:
    t = db.scalar(select(Tipificacion).where(Tipificacion.conversacion_id == conversacion_id))
    return GestionIA(resultado=t.resultado, tipificacion_id=t.id) if t else None


# ---- Acciones, uso, historial ------------------------------------------------------------------
def acciones(db: Session, usuario: Usuario, conv: Conversacion) -> list[AccionSalida]:
    if usuario.rol == "agente" and not servicio.es_dueno(conv, usuario):
        raise ErrorApp(404, "NO_ENCONTRADO", "Conversación no encontrada.")
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
    filtro = [c.modelo_ia.is_not(None), c.abierta_en >= ini, c.abierta_en < fin]
    if campana_id is not None:
        filtro.append(c.campana_id == campana_id)
    ids_q = select(c.id).where(*filtro)  # subconsulta: nada se trae a Python por conversación

    def suma(condicion):
        return func.coalesce(func.sum(case((condicion, 1), else_=0)), 0)

    total, verificadas, opt_outs, cerradas_ia, cerradas_inact = db.execute(
        select(
            func.count(c.id),
            suma(c.identidad_verificada.is_(True)),
            suma(c.motivo_cierre == "opt_out"),
            suma(c.motivo_cierre == "sistema"),
            suma(c.motivo_cierre == "inactividad"),
        ).where(*filtro)
    ).one()
    resultados = dict(
        db.execute(
            select(Tipificacion.resultado, func.count(Tipificacion.id))
            .where(Tipificacion.conversacion_id.in_(ids_q), Tipificacion.origen == "agente_ia")
            .group_by(Tipificacion.resultado)
        ).all()
    )
    n_acuerdos, monto_acuerdos = db.execute(
        select(func.count(PromesaPago.id), func.coalesce(func.sum(PromesaPago.monto), 0))
        .join(Tipificacion, Tipificacion.id == PromesaPago.tipificacion_id)
        .where(Tipificacion.conversacion_id.in_(ids_q), Tipificacion.origen == "agente_ia")
    ).one()
    n_ventas, valor_ventas = db.execute(
        select(func.count(Venta.id), func.coalesce(func.sum(Venta.valor), 0))
        .join(Tipificacion, Tipificacion.id == Venta.tipificacion_id)
        .where(Tipificacion.conversacion_id.in_(ids_q), Tipificacion.origen == "agente_ia")
    ).one()
    derivaciones = dict(
        db.execute(
            select(ColaAtencion.motivo, func.count(ColaAtencion.id))
            .where(ColaAtencion.conversacion_id.in_(ids_q), ColaAtencion.motivo.in_(MOTIVOS_IA))
            .group_by(ColaAtencion.motivo)
        ).all()
    )
    entradas, salida, escritura, lectura, costo = db.execute(
        select(
            func.coalesce(func.sum(UsoIA.input_tokens), 0),
            func.coalesce(func.sum(UsoIA.output_tokens), 0),
            func.coalesce(func.sum(UsoIA.cache_creation_input_tokens), 0),
            func.coalesce(func.sum(UsoIA.cache_read_input_tokens), 0),
            func.coalesce(func.sum(UsoIA.costo_usd), 0),
        ).where(UsoIA.conversacion_id.in_(ids_q))
    ).one()
    costo = Decimal(costo)
    monto_acuerdos, valor_ventas = Decimal(monto_acuerdos), Decimal(valor_ventas)
    tiempos = _tiempos_respuesta(db, ids_q)
    errores: dict[str, int] = {}
    consulta_err = select(ErrorIA.codigo, func.count(ErrorIA.id)).where(
        ErrorIA.creado_en >= ini, ErrorIA.creado_en < fin
    )
    if campana_id is not None:
        consulta_err = consulta_err.where(ErrorIA.campana_id == campana_id)
    for codigo, n in db.execute(consulta_err.group_by(ErrorIA.codigo)):
        errores[codigo] = n
    guardas: dict[str, int] = {}
    if total:
        ids = set(db.scalars(ids_q))
        for detalle in db.scalars(
            select(Auditoria.detalle).where(
                Auditoria.accion == "ia.guarda",
                Auditoria.creado_en >= ini,
                Auditoria.creado_en < fin,
            )
        ):
            if detalle.get("conversacion_id") in ids:
                codigo = detalle.get("codigo", "?")
                guardas[codigo] = guardas.get(codigo, 0) + 1
    return MetricasIA(
        campana_id=campana_id,
        desde=desde.isoformat(),
        hasta=hasta.isoformat(),
        conversaciones=total,
        con_identidad_verificada=verificadas,
        tasa_verificacion=round(verificadas / total, 4) if total else None,
        acuerdos=Importe(numero=n_acuerdos, monto_total=monto_acuerdos),
        ventas=ImporteVenta(numero=n_ventas, valor_total=valor_ventas),
        resultados=resultados,
        derivaciones=derivaciones,
        opt_outs=opt_outs,
        cerradas_por_ia=cerradas_ia,
        cerradas_por_inactividad=cerradas_inact,
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


def _tiempos_respuesta(db: Session, ids_q) -> list[int]:
    """Del `creado_en` del último entrante de cada turno al del mensaje `ia` siguiente (solo
    columnas, en flujo; el emparejamiento por turno no es una agregación SQL simple)."""
    tiempos: list[int] = []
    ultimo: dict[int, datetime | None] = {}
    for conv_id, autor, creado in db.execute(
        select(Mensaje.conversacion_id, Mensaje.autor, Mensaje.creado_en)
        .where(Mensaje.conversacion_id.in_(ids_q), Mensaje.autor.in_(("cliente", "ia")))
        .order_by(Mensaje.conversacion_id, Mensaje.id)
    ).yield_per(1000):
        if autor == "cliente":
            ultimo[conv_id] = creado
        elif ultimo.get(conv_id) is not None:
            tiempos.append(int((creado - ultimo[conv_id]).total_seconds() * 1000))
            ultimo[conv_id] = None
    return tiempos
