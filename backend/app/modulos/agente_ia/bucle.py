"""Bucle agéntico manual de un turno (fase-2c.md §4.4, ADR-0022).

Transacciones cortas e independientes (inicio, comprobación previa a cada llamada, registro de
cada respuesta, cada herramienta, resultados y cierre): NUNCA hay una abierta durante
`llm.crear_mensaje`. El historial solo recibe filas nuevas (append-only) y el `assistant` lleva
siempre `response.content` completo.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modulos.agente_ia import (
    arrendamiento,
    configuracion,
    derivacion,
    eventos,
    historial,
    mensajes,
    presupuesto,
)
from app.modulos.agente_ia import guardas as guardas_mod
from app.modulos.agente_ia.canal import CanalIA
from app.modulos.agente_ia.contexto import (
    ContextoInteraccion,
    RefInteraccion,
    SinContextoIA,
    cargar_contexto,
)
from app.modulos.agente_ia.costes import costo_usd
from app.modulos.agente_ia.herramientas import definiciones
from app.modulos.agente_ia.herramientas.ejecutores import EstadoTurno, ejecutar_herramienta
from app.modulos.agente_ia.llm import ClienteLLM, ErrorLLM, RespuestaLLM
from app.modulos.agente_ia.modelos import (
    AccionIA,
    ConfiguracionIACampana,
    InstruccionSupervisor,
    UsoIA,
)
from app.modulos.agente_ia.prompts import cargar_sistema
from app.modulos.auditoria import servicio as auditoria
from app.modulos.clientes.modelos import Cliente
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.whatsapp.ventana import Rechazar, Retener
from app.reloj import Reloj
from app.trabajos.registro import ErrorTrabajo, ReprogramarTrabajo

logger = logging.getLogger("app.ia")


@dataclass
class ResultadoTurno:
    estado: str  # sin_efectos | sin_respuesta | completado | derivado | error
    iteraciones: int = 0


class _Fin(Exception):
    """Termina el bucle con un estado final (la transacción final se aplica siempre)."""

    def __init__(self, estado: str, silencioso: bool = False) -> None:
        super().__init__(estado)
        self.estado = estado
        self.silencioso = silencioso


def _ttl_cache() -> dict[str, str]:
    return (
        {"type": "ephemeral"}
        if get_settings().ia_cache_ttl == "5m"
        else {"type": "ephemeral", "ttl": "1h"}
    )


def sistema_de(ctx: ContextoInteraccion) -> list[dict]:
    return [
        {
            "type": "text",
            "text": cargar_sistema(ctx.canal, ctx.prompt_version),
            "cache_control": _ttl_cache(),
        }
    ]


def _conv(db: Session, ref: RefInteraccion) -> Conversacion:
    conv = db.get(Conversacion, ref.id)
    assert conv is not None
    return conv


def _instrucciones_pendientes(db: Session, ref: RefInteraccion, ahora: datetime) -> list[str]:
    filas = db.scalars(
        select(InstruccionSupervisor)
        .where(
            InstruccionSupervisor.conversacion_id == ref.id,
            InstruccionSupervisor.aplicada_en.is_(None),
        )
        .order_by(InstruccionSupervisor.id)
    )
    textos = []
    for i in filas:
        i.aplicada_en = ahora
        textos.append(i.texto)
    return textos


def _agregar_instrucciones(db: Session, ref: RefInteraccion, ahora: datetime) -> None:
    for texto in _instrucciones_pendientes(db, ref, ahora):
        historial.agregar(
            db,
            ref,
            "system",
            "instruccion",
            {"texto": mensajes.instruccion_supervisor(texto)},
            ahora,
        )


# ---- Turno -------------------------------------------------------------------------------------
def ejecutar_turno(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ref: RefInteraccion,
    llm: ClienteLLM,
    reloj: Reloj,
    trabajador: str,
) -> ResultadoTurno:
    s = get_settings()
    estado = EstadoTurno()
    inicio = reloj()
    ctx = _tx_inicio(sesion, canal, ref, reloj, trabajador)
    if isinstance(ctx, ResultadoTurno):
        return ctx
    iteraciones = 0
    correcciones = 0
    final = "completado"
    try:
        while True:
            if iteraciones >= s.ia_max_iteraciones:
                _derivar(sesion, canal, ctx, "ia_iteraciones", reloj, estado)
                raise _Fin("derivado")
            iteraciones += 1
            peticion = _tx_previa(sesion, canal, ctx, estado, reloj, trabajador, inicio)
            try:
                r = llm.crear_mensaje(
                    modelo=ctx.modelo,
                    max_tokens=s.ia_max_tokens,
                    esfuerzo=ctx.esfuerzo,
                    sistema=sistema_de(ctx),
                    herramientas=definiciones.catalogo(ctx.canal, ctx.tipo_campana),
                    mensajes=peticion,
                    fallback_rechazo=s.ia_fallback_rechazo,
                    cache_ttl=s.ia_cache_ttl,
                )
            except ErrorLLM as exc:
                _tras_error_llm(sesion, canal, ctx, exc, reloj, trabajador, estado)
                raise _Fin("error") from None  # solo no transitorios llegan aquí
            accion = _tx_respuesta(sesion, canal, ctx, r, iteraciones, correcciones, estado, reloj)
            if accion == "corregir":
                correcciones += 1
                continue
            if accion == "continuar":
                continue
            if accion == "herramientas":
                if not _ejecutar_herramientas(sesion, canal, ctx, r, estado, reloj, trabajador):
                    _derivar_si_desactivada(sesion, canal, ctx, reloj)
                    raise _Fin("sin_respuesta", silencioso=True)
                if estado.terminal == "optout":
                    raise _Fin("completado")
                continue
            raise _Fin(accion)
    except _Fin as fin:
        final = fin.estado
    _tx_final(sesion, canal, ctx, estado, reloj, trabajador, final, iteraciones)
    return ResultadoTurno(final, iteraciones)


# ---- Tx A: inicio ------------------------------------------------------------------------------
def _tx_inicio(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ref: RefInteraccion,
    reloj: Reloj,
    trabajador: str,
) -> ContextoInteraccion | ResultadoTurno:
    s = get_settings()
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ref)
        if not est.abierta or est.dueno != "ia":
            db.rollback()
            return ResultadoTurno("sin_efectos")
        conv = _conv(db, ref)
        try:
            ctx = cargar_contexto(db, ref)
        except SinContextoIA:
            db.rollback()
            return ResultadoTurno("sin_efectos")
        cfg = db.get(ConfiguracionIACampana, ctx.campana_id)
        if cfg is None or not configuracion.ia_disponible(db, ctx.campana_id):
            derivacion.derivar_determinista(db, canal, ref, "ia_desactivada", ahora)
            eventos.publicar_turno(db, ref.tipo, ref.id, ctx.campana_id, "derivado")
            db.commit()
            return ResultadoTurno("derivado")
        if not arrendamiento.adquirir(db, ref, trabajador, ahora):
            db.rollback()
            raise ReprogramarTrabajo(ahora + timedelta(seconds=s.ia_reintento_arriendo_segundos))
        historial.reparar_pendientes(db, ref, ahora)
        entradas = canal.entradas_nuevas(db, ref)
        espera = historial.espera_respuesta(db, ref)
        if not entradas and not espera:
            arrendamiento.liberar(db, ref, trabajador)
            db.commit()
            return ResultadoTurno("sin_respuesta")
        g = guardas_mod.entrada(
            entradas,
            guardas_mod.cargar_frases_humano(s.ia_frases_humano),
            s.ia_payload_asesor,
            s.ia_max_caracteres_entrada,
        )

        def terminar(motivo: str, estado: str, enviar: bool = True) -> ResultadoTurno:
            derivacion.derivar_determinista(db, canal, ref, motivo, ahora, enviar=enviar)
            if entradas:
                canal.marcar_procesadas(db, entradas, ahora)
            arrendamiento.liberar(db, ref, trabajador)
            eventos.publicar_turno(db, ref.tipo, ref.id, ctx.campana_id, estado)
            db.commit()
            return ResultadoTurno(estado)

        if entradas and g.pide_humano:
            return terminar("solicitud_cliente", "derivado")
        if entradas:
            d = canal.decidir_respuesta(db, ref, ahora)
            if isinstance(d, Retener):
                arrendamiento.liberar(db, ref, trabajador)
                db.commit()
                raise ReprogramarTrabajo(d.programado_para)
            if isinstance(d, Rechazar):
                return terminar("entrante", "derivado", enviar=False)
        if presupuesto.conversacion_excedida(conv, cfg, True) or presupuesto.comprobar_campana(
            db, cfg, ctx.tipo_campana, ahora
        ):
            return terminar("presupuesto_excedido", "derivado")
        omitidas = getattr(canal, "omitidas", {}).get(ref.clave, 0)
        previas = historial.filas(db, ref)
        zona = ctx.zona_horaria
        if entradas:
            historial.agregar(
                db, ref, "user", "entradas_cliente",
                mensajes.formatear_entradas(g.entradas, zona, omitidas), ahora,
            )  # fmt: skip
            hoy = ahora.astimezone(ZoneInfo(zona)).date().isoformat()
            if not previas:
                cliente = db.get(Cliente, ctx.cliente_id)
                nombre = (cliente.nombre.split() or [None])[0] if cliente else None
                historial.agregar(
                    db, ref, "system", "contexto",
                    {
                        "texto": mensajes.contexto_sistema(
                            tipo_campana=ctx.tipo_campana,
                            tratamiento=ctx.tratamiento,
                            nombre_pila=nombre,
                            ahora=ahora,
                            zona=zona,
                            iniciada_por=conv.iniciada_por,
                            identidad_verificada=conv.identidad_verificada,
                            instrucciones=cfg.instrucciones,
                        ),
                        "fecha_local": hoy,
                    },
                    ahora,
                )  # fmt: skip
            elif historial.ultima_fecha_contexto(db, ref) not in (None, hoy):
                historial.agregar(
                    db, ref, "system", "contexto",
                    {"texto": mensajes.cambio_de_fecha(ahora, zona), "fecha_local": hoy}, ahora,
                )  # fmt: skip
            canal.marcar_procesadas(db, entradas, ahora)
        _agregar_instrucciones(db, ref, ahora)
        conv.turnos_ia += 1
        eventos.publicar_turno(db, ref.tipo, ref.id, ctx.campana_id, "en_curso")
        db.commit()
        return ctx


# ---- Comprobación previa a cada llamada --------------------------------------------------------
def _derivar(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    motivo: str,
    reloj: Reloj,
    estado: EstadoTurno,
    enviar: bool = True,
) -> None:
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ctx.ref)
        if est.abierta and est.dueno == "ia":
            derivacion.derivar_determinista(db, canal, ctx.ref, motivo, ahora, enviar=enviar)
            eventos.publicar_turno(db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, "derivado")
        db.commit()


def _derivar_si_desactivada(
    sesion: Callable[[], Session], canal: CanalIA, ctx: ContextoInteraccion, reloj: Reloj
) -> None:
    """Si el turno se detuvo porque la IA se desactivó y la conversación sigue siendo suya,
    pasa a la cola humana (las conversaciones tomadas por terceros no se tocan)."""
    with sesion() as db:
        est = canal.bloquear(db, ctx.ref)
        if (
            est.abierta
            and est.dueno == "ia"
            and not configuracion.ia_disponible(db, ctx.campana_id)
        ):
            derivacion.derivar_determinista(db, canal, ctx.ref, "ia_desactivada", reloj())
        db.commit()


def _tx_previa(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    estado: EstadoTurno,
    reloj: Reloj,
    trabajador: str,
    inicio: datetime,
) -> list[dict]:
    s = get_settings()
    motivo: str | None = None
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ctx.ref)
        if estado.terminal is None:
            if not est.abierta or est.dueno != "ia":
                db.rollback()
                raise _Fin("sin_respuesta", silencioso=True)
            conv = _conv(db, ctx.ref)
            cfg = db.get(ConfiguracionIACampana, ctx.campana_id)
            if cfg is None or not configuracion.ia_disponible(db, ctx.campana_id):
                motivo = "ia_desactivada"
            elif presupuesto.conversacion_excedida(
                conv, cfg, False
            ) or presupuesto.comprobar_campana(db, cfg, ctx.tipo_campana, ahora):
                motivo = "presupuesto_excedido"
            elif (ahora - inicio).total_seconds() >= s.ia_turno_max_segundos:
                motivo = "ia_iteraciones"
        if motivo is None:
            if not arrendamiento.renovar(db, ctx.ref, trabajador, ahora):
                db.rollback()
                raise _Fin("sin_respuesta", silencioso=True)
            filas = historial.leer(db, ctx.ref)
            db.commit()
            return mensajes.construir_peticion(filas, ctx.modelo, s.modelos_ia_sin_system)
        if est.abierta and est.dueno == "ia":
            derivacion.derivar_determinista(db, canal, ctx.ref, motivo, ahora)
            eventos.publicar_turno(db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, "derivado")
        db.commit()
    raise _Fin("derivado")


# ---- Errores del proveedor ---------------------------------------------------------------------
def _tras_error_llm(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    exc: ErrorLLM,
    reloj: Reloj,
    trabajador: str,
    estado: EstadoTurno,
) -> None:
    with sesion() as db:
        ahora = reloj()
        canal.bloquear(db, ctx.ref)
        presupuesto.registrar_error(
            db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, exc.codigo, exc.transitorio, ahora
        )
        if exc.transitorio:
            arrendamiento.liberar(db, ctx.ref, trabajador)
            db.commit()
            raise ErrorTrabajo(exc.codigo, transitorio=True)
        presupuesto.comprobar_errores(db, ctx.campana_id, ahora)
        est = canal.bloquear(db, ctx.ref)
        if est.abierta and est.dueno == "ia":
            derivacion.derivar_determinista(db, canal, ctx.ref, "ia_error", ahora)
            eventos.publicar_turno(db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, "derivado")
        db.commit()


# ---- Tx B: registro de la respuesta ------------------------------------------------------------
def _registrar_uso(
    db: Session,
    ctx: ContextoInteraccion,
    r: RespuestaLLM,
    iteracion: int,
    conv: Conversacion,
    ahora: datetime,
) -> UsoIA:
    s = get_settings()
    precios = s.precios_ia.get(r.modelo) or s.precios_ia[ctx.modelo]
    costo = costo_usd(r.uso, precios, s.ia_cache_ttl)
    uso = UsoIA(
        conversacion_id=ctx.ref.id if ctx.ref.tipo == "conversacion" else None,
        llamada_id=ctx.ref.id if ctx.ref.tipo == "llamada" else None,
        campana_id=ctx.campana_id,
        canal=ctx.canal_gestion,
        modelo=ctx.modelo,
        modelo_servido=r.modelo[:40],
        esfuerzo=ctx.esfuerzo,
        respuesta_id=r.id[:80],
        request_id=(r.request_id or None) and r.request_id[:80],
        iteracion=iteracion,
        stop_reason=r.stop_reason[:20],
        stop_categoria=r.stop_categoria,
        input_tokens=r.uso.get("input_tokens", 0),
        output_tokens=r.uso.get("output_tokens", 0),
        cache_creation_input_tokens=r.uso.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=r.uso.get("cache_read_input_tokens", 0),
        costo_usd=costo,
        duracion_ms=r.duracion_ms,
        creado_en=ahora,
    )
    db.add(uso)
    db.flush()
    conv.costo_usd_acumulado = (conv.costo_usd_acumulado or Decimal(0)) + costo
    logger.info(
        "ia.llamada conversacion=%s modelo=%s stop=%s in=%s out=%s cache_r=%s cache_w=%s ms=%s "
        "request_id=%s",
        ctx.ref.id, r.modelo, r.stop_reason, uso.input_tokens, uso.output_tokens,
        uso.cache_read_input_tokens, uso.cache_creation_input_tokens, r.duracion_ms, r.request_id,
    )  # fmt: skip
    return uso


def _contexto_guardas(
    db: Session, ctx: ContextoInteraccion, conv: Conversacion
) -> guardas_mod.ContextoGuardas:
    s = get_settings()
    cliente = db.get(Cliente, ctx.cliente_id)
    acciones = db.execute(
        select(AccionIA.resultado, AccionIA.es_error).where(AccionIA.conversacion_id == ctx.ref.id)
    ).all()
    montos, pct = guardas_mod.valores_respaldados((a, e) for a, e in acciones)
    return guardas_mod.ContextoGuardas(
        numero_documento=cliente.numero_documento if cliente else None,
        identidad_verificada=conv.identidad_verificada,
        montos_respaldados=frozenset(montos),
        porcentajes_respaldados=frozenset(pct),
        dominios_permitidos=s.dominios_ia_permitidos,
        max_caracteres=s.ia_max_caracteres_salida,
    )


def _enviar_texto(
    db: Session, canal: CanalIA, ctx: ContextoInteraccion, conv: Conversacion, texto: str,
    ahora: datetime,
) -> None:  # fmt: skip
    """Texto del modelo (`autor=ia`); el primero lleva antepuesto el aviso de asistente."""
    if conv.aviso_ia_enviado_en is None:
        texto = get_settings().ia_aviso_asistente + "\n\n" + texto
        conv.aviso_ia_enviado_en = ahora
    canal.enviar(db, ctx.ref, texto, ahora, "ia")


def _mensaje_fijo(db: Session, canal: CanalIA, ctx: ContextoInteraccion, ahora: datetime) -> None:
    s = get_settings()
    hay = canal.hay_humano_disponible(db, ctx)
    texto = s.ia_mensaje_traspaso if hay else s.whatsapp_mensaje_espera
    if texto:
        canal.enviar(db, ctx.ref, texto, ahora, "sistema")


def _tx_respuesta(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    r: RespuestaLLM,
    iteracion: int,
    correcciones: int,
    estado: EstadoTurno,
    reloj: Reloj,
) -> str:
    """Devuelve: `herramientas` | `continuar` | `corregir` | estado final del turno."""
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ctx.ref)
        conv = _conv(db, ctx.ref)
        uso = _registrar_uso(db, ctx, r, iteracion, conv, ahora)
        propio = estado.terminal is not None
        if not propio and not (est.abierta and est.dueno == "ia"):
            db.commit()  # solo el uso: la respuesta NO entra en el historial
            raise _Fin("sin_respuesta", silencioso=True)
        if not propio and not configuracion.ia_disponible(db, ctx.campana_id):
            # Kill switch durante la llamada: la respuesta no se registra ni se envía.
            derivacion.derivar_determinista(db, canal, ctx.ref, "ia_desactivada", ahora)
            eventos.publicar_turno(db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, "derivado")
            db.commit()
            return "derivado"
        historial.agregar(
            db,
            ctx.ref,
            "assistant",
            "respuesta",
            r.contenido,
            ahora,
            modelo=r.modelo,
            uso_ia_id=uso.id,
        )
        sr = r.stop_reason
        if sr == "tool_use":
            if not any(b.get("type") == "tool_use" for b in r.contenido):
                derivacion.derivar_determinista(db, canal, ctx.ref, "ia_stop_inesperado", ahora)
                db.commit()
                return "derivado"
            db.commit()
            return "herramientas"
        if sr == "pause_turn":
            db.commit()
            return "continuar"
        if sr == "end_turn":
            return _fin_de_turno(db, canal, ctx, conv, est, r, estado, correcciones, ahora)
        if sr == "refusal":
            auditoria.registrar(
                db, "ia.rechazo_modelo", None, "conversacion", conv.id,
                {"conversacion_id": conv.id, "categoria": r.stop_categoria},
            )  # fmt: skip
            eventos.publicar_alerta(db, "rechazo_modelo", "aviso", ctx.campana_id, conv.id)
            motivo = "ia_rechazo"
        elif sr == "max_tokens":
            motivo = "ia_max_tokens"
        else:
            motivo = "ia_stop_inesperado"
        derivacion.derivar_determinista(db, canal, ctx.ref, motivo, ahora)
        db.commit()
        return "derivado"


def _fin_de_turno(
    db: Session,
    canal: CanalIA,
    ctx: ContextoInteraccion,
    conv: Conversacion,
    est,
    r: RespuestaLLM,
    estado: EstadoTurno,
    correcciones: int,
    ahora: datetime,
) -> str:
    texto = "\n\n".join(
        b["text"] for b in r.contenido if b.get("type") == "text" and b.get("text")
    ).strip()
    terminal = estado.terminal
    if terminal == "optout":
        db.commit()
        return "completado"
    fallo = guardas_mod.salida(texto, _contexto_guardas(db, ctx, conv)) if texto else None
    if fallo is not None:
        auditoria.registrar(
            db, "ia.guarda", None, "conversacion", conv.id,
            {"conversacion_id": conv.id, "codigo": fallo.codigo},
        )  # fmt: skip
    if terminal in ("derivar", "identidad"):
        sigue = est.dueno == "sin_asignar" and est.cola_id_activa == estado.cola_id
        if sigue:
            if texto and fallo is None:
                _enviar_texto(db, canal, ctx, conv, texto, ahora)
            else:
                _mensaje_fijo(db, canal, ctx, ahora)
        db.commit()
        return "derivado"
    if terminal == "cierre":
        if texto and fallo is None and est.abierta:
            _enviar_texto(db, canal, ctx, conv, texto, ahora)
        db.commit()
        return "completado"
    if not texto:
        db.commit()
        return "sin_respuesta"
    if fallo is None:
        _enviar_texto(db, canal, ctx, conv, texto, ahora)
        db.commit()
        return "completado"
    if correcciones == 0:
        ref = ctx.ref
        historial.agregar(
            db, ref, "user", "control",
            [{"type": "text", "text": mensajes.CONTROL_RESPUESTA_BLOQUEADA}], ahora,
        )  # fmt: skip
        historial.agregar(
            db, ref, "system", "correccion", {"texto": mensajes.correccion(fallo.motivo)}, ahora
        )
        db.commit()
        return "corregir"
    motivo = (
        "ia_monto_no_respaldado"
        if fallo.codigo in ("MONTO_ANTES_DE_VERIFICAR", "MONTO_NO_RESPALDADO")
        else "ia_no_resuelve"
    )
    derivacion.derivar_determinista(db, canal, ctx.ref, motivo, ahora)
    db.commit()
    return "derivado"


# ---- Herramientas ------------------------------------------------------------------------------
def _ejecutar_herramientas(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    r: RespuestaLLM,
    estado: EstadoTurno,
    reloj: Reloj,
    trabajador: str,
) -> bool:
    """Ejecuta los `tool_use` en orden (cada uno en su Tx) y añade UN `user` con todos los
    `tool_result`. Devuelve False si el turno debe detenerse sin resultados."""
    bloques = []
    for b in r.contenido:
        if b.get("type") != "tool_use":
            continue
        ej = ejecutar_herramienta(sesion, canal, ctx, b, estado, reloj, trabajador)
        if ej is None:
            return False
        bloques.append(historial.bloque_resultado(b["id"], ej.resultado, ej.es_error))
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ctx.ref)
        if estado.terminal is None and not (est.abierta and est.dueno == "ia"):
            db.rollback()
            return False
        historial.agregar(db, ctx.ref, "user", "resultados_herramientas", bloques, ahora)
        _agregar_instrucciones(db, ctx.ref, ahora)
        db.commit()
    return True


# ---- Tx final ----------------------------------------------------------------------------------
def _tx_final(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    estado: EstadoTurno,
    reloj: Reloj,
    trabajador: str,
    final: str,
    iteraciones: int,
) -> None:
    with sesion() as db:
        ahora = reloj()
        est = canal.bloquear(db, ctx.ref)
        if estado.terminal == "cierre" and est.abierta:
            canal.cerrar(db, ctx.ref, ahora)
            auditoria.registrar(
                db, "ia.cierre", None, "conversacion", ctx.ref.id,
                {"conversacion_id": ctx.ref.id, "resultado": estado.cierre_resultado},
            )  # fmt: skip
        arrendamiento.liberar(db, ctx.ref, trabajador)
        eventos.publicar_turno(db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, final, iteraciones)
        db.commit()
