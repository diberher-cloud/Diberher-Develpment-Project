"""Ejecución de herramientas con validación en servidor (fase-2c.md §4.4.2 y §4.8).

Cada herramienta corre en SU transacción (Tx C): `clientes` FOR UPDATE (si tiene efectos) ->
`conversaciones` FOR UPDATE -> revalida dueño `ia`, apertura, `ia_disponible` y arrendamiento ->
idempotencia por `tool_use_id` -> valida -> ejecuta -> `acciones_ia` + auditoría -> commit.
El cliente, la campaña, el registro y el teléfono salen SIEMPRE del `ContextoInteraccion`.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.agente_ia import arrendamiento, configuracion, eventos
from app.modulos.agente_ia import guardas as guardas_mod
from app.modulos.agente_ia import limites as lim
from app.modulos.agente_ia.canal import CanalIA
from app.modulos.agente_ia.contexto import ContextoInteraccion
from app.modulos.agente_ia.herramientas import definiciones, entradas
from app.modulos.agente_ia.herramientas.resultados import (
    ErrorHerramienta,
    Resultado,
    enmascarar_entrada,
)
from app.modulos.agente_ia.modelos import AccionIA, ConfiguracionIACampana, OfertaCampana
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola import servicio as consola
from app.modulos.consola import tipificacion as tip
from app.modulos.consola.esquemas import PromesaEntrada, TipificacionDatos
from app.modulos.consola.guion import formatear_fecha, formatear_monto
from app.modulos.consola.modelos import PromesaPago, Tipificacion
from app.modulos.conversaciones.modelos import Conversacion
from app.modulos.cumplimiento import motor
from app.modulos.cumplimiento import servicio as cumplimiento
from app.modulos.cumplimiento.modelos import IntentoContacto
from app.modulos.whatsapp import servicio_autorizaciones

CON_CLIENTE = frozenset(
    {"registrar_acuerdo_pago", "registrar_venta", "programar_seguimiento", "cerrar_conversacion"}
)
PLURAL_PERIODO = {"semanal": "semanales", "quincenal": "quincenales", "mensual": "mensuales"}


@dataclass
class EstadoTurno:
    """Estado en memoria del turno (acciones terminales propias)."""

    terminal: str | None = None  # derivar | identidad | optout | cierre
    cola_id: int | None = None
    cierre_resultado: str | None = None


@dataclass
class Ejecucion:
    resultado: dict[str, Any]
    es_error: bool
    accion_id: int


# ---- Utilidades --------------------------------------------------------------------------------
def _hoy(ctx: ContextoInteraccion, ahora: datetime) -> date:
    return ahora.astimezone(ZoneInfo(ctx.zona_horaria)).date()


def _cfg(db: Session, ctx: ContextoInteraccion) -> ConfiguracionIACampana:
    cfg = db.get(ConfiguracionIACampana, ctx.campana_id)
    if cfg is None:
        raise ErrorHerramienta("HERRAMIENTA_NO_DISPONIBLE", "La campaña no tiene IA configurada.")
    return cfg


def _reglas_cobranza(cfg: ConfiguracionIACampana) -> lim.ReglasCobranza:
    try:
        return lim.validar_reglas_cobranza(cfg.reglas)
    except lim.ErroresReglas:
        raise ErrorHerramienta(
            "HERRAMIENTA_NO_DISPONIBLE", "Las reglas de la campaña no están disponibles."
        ) from None


def _reglas_venta(cfg: ConfiguracionIACampana) -> lim.ReglasVenta:
    try:
        return lim.validar_reglas_venta(cfg.reglas)
    except lim.ErroresReglas:
        raise ErrorHerramienta(
            "HERRAMIENTA_NO_DISPONIBLE", "Las reglas de la campaña no están disponibles."
        ) from None


def _cc(db: Session, ctx: ContextoInteraccion) -> CampanaCliente:
    cc = db.get(CampanaCliente, ctx.campana_cliente_id)
    assert cc is not None
    db.refresh(cc)
    return cc


def _obligacion(cc: CampanaCliente) -> lim.Obligacion:
    return lim.Obligacion(cc.saldo_total, cc.saldo_mora)


def _gestion(db: Session, conv: Conversacion) -> Tipificacion | None:
    return db.scalar(select(Tipificacion).where(Tipificacion.conversacion_id == conv.id))


def _exigir_sin_gestion(db: Session, conv: Conversacion) -> None:
    if _gestion(db, conv) is not None:
        raise ErrorHerramienta(
            "GESTION_YA_REGISTRADA",
            "Ya se registró una gestión en esta conversación; no se puede registrar otra.",
        )


def _promesa_vigente(db: Session, cc: CampanaCliente) -> PromesaPago | None:
    return db.scalar(
        select(PromesaPago)
        .where(PromesaPago.campana_cliente_id == cc.id, PromesaPago.estado == "vigente")
        .order_by(PromesaPago.id.desc())
        .limit(1)
    )


def mascara_obligacion(numero: str | None) -> str | None:
    """`***` + últimos 3 caracteres (conservando un guion que los preceda: `***-001`)."""
    if not numero:
        return None
    sep = "-" if len(numero) > 3 and numero[-4] == "-" else ""
    return "***" + sep + numero[-3:]


def _acciones(db: Session, conv: Conversacion, herramienta: str) -> list[AccionIA]:
    return list(
        db.scalars(
            select(AccionIA)
            .where(
                AccionIA.conversacion_id == conv.id,
                AccionIA.herramienta == herramienta,
                AccionIA.es_error.is_(False),
            )
            .order_by(AccionIA.id.desc())
        )
    )


def _error_cita(codigo: str) -> ErrorHerramienta:
    mensajes = {
        "CITA_INVALIDA": "La cita debe tener entre 2 y 300 caracteres.",
        "CITA_NO_ENCONTRADA": "La cita no aparece en ningún mensaje del cliente.",
        "CITA_ANTERIOR_A_PROPUESTA": (
            "La cita solo aparece en mensajes anteriores a tu propuesta; "
            "pide al cliente que la acepte de nuevo."
        ),
    }
    return ErrorHerramienta(codigo, mensajes[codigo])


def _localizar_cita(
    db: Session, canal: CanalIA, ctx: ContextoInteraccion, cita: str, desde: datetime | None
) -> int | None:
    """Verifica la cita contra los mensajes del cliente; devuelve el id del mensaje."""
    textos = canal.textos_cliente(db, ctx.ref, None)
    codigo = guardas_mod.verificar_cita(cita, textos, desde)
    if codigo is not None:
        raise _error_cita(codigo)
    norm = f" {guardas_mod.opt_out.normalizar_sin_cortesia(cita)} "
    for t in textos:
        if norm in f" {guardas_mod.opt_out.normalizar_sin_cortesia(t.texto)} " and (
            desde is None or t.momento > desde
        ):
            return t.id
    return None


def _registrar_gestion(
    db: Session,
    ctx: ContextoInteraccion,
    conv: Conversacion,
    datos: TipificacionDatos,
    ahora: datetime,
    *,
    festivos: dict | None = None,
    **kw: Any,
):
    """Tipificación de la IA (una por conversación) con los efectos de 2A/2B. Sin commit."""
    cc = _cc(db, ctx)
    campana = db.get(Campana, ctx.campana_id)
    assert campana is not None
    politica, _ = cumplimiento.cargar_politica(db, campana.tipo)
    val = tip.Validada(politica=politica, festivos=festivos or {}, observacion=datos.observacion)
    telefono = db.get(Telefono, ctx.telefono_id) if ctx.telefono_id else None
    aplicada = tip.aplicar_efectos(
        db,
        datos,
        val,
        cc,
        campana,
        telefono,
        ahora,
        canal=ctx.canal_gestion,
        origen="agente_ia",
        actor_id=None,
        gestor_id=None,
        conversacion_id=conv.id,
        origen_exclusion="agente_ia",
        **kw,
    )
    if conv.intento_contacto_id is not None:
        intento = db.get(IntentoContacto, conv.intento_contacto_id)
        if intento is not None:
            intento.contacto_directo = intento.contacto_directo or aplicada.efecto.contacto_directo
            intento.resultado = datos.resultado
    auditoria.registrar(
        db,
        "tipificacion.crear",
        None,
        "tipificacion",
        aplicada.tip.id,
        {
            "tipificacion_id": aplicada.tip.id,
            "conversacion_id": conv.id,
            "resultado": datos.resultado,
            "origen": "agente_ia",
        },
    )
    if aplicada.es_dueno:
        consola.publicar_registro(
            db, campana.id, cc.id, "gestionado" if aplicada.efecto.cierra_registro else "liberado"
        )
    return aplicada


def _enviar_constancia(
    db: Session, canal: CanalIA, ctx: ContextoInteraccion, texto: str, ahora: datetime
) -> None:
    canal.enviar(db, ctx.ref, texto, ahora, "sistema")


def texto_constancia_acuerdo(plan: lim.Plan, referencia: str, empresa: str) -> str:
    n = plan.numero_cuotas
    if n == 1:
        resumen = f"Total: {formatear_monto(plan.monto_total)} en 1 cuota."
    else:
        resumen = (
            f"Total: {formatear_monto(plan.monto_total)} en {n} cuotas "
            f"{PLURAL_PERIODO[plan.periodicidad]}."
        )
    lineas = [
        f"*Constancia de su acuerdo de pago con {empresa}*",
        resumen,
        *(
            f"{c.numero}) {formatear_fecha(c.fecha)}: {formatear_monto(c.monto)}"
            for c in plan.cuotas
        ),
        f"Referencia: {referencia}. "
        "Si algo no coincide con lo que acordó, responda a este mensaje.",
    ]
    return "\n".join(lineas)


def _pct(valor: Decimal) -> str:
    texto = f"{valor.normalize():f}".replace(".", ",")
    return texto


def texto_constancia_venta(
    cot: lim.Cotizacion, referencia: str, empresa: str, retracto: str
) -> str:
    descuento = (
        f" (descuento {_pct(cot.descuento_porcentaje)} %)" if cot.descuento_porcentaje else ""
    )
    lineas = [
        f"*Constancia de su compra con {empresa}*",
        f"{cot.oferta.nombre} x {cot.unidades}. Valor total: {formatear_monto(cot.valor_total)}"
        f"{descuento}.",
    ]
    if cot.oferta.condiciones:
        lineas.append(f"Condiciones: {cot.oferta.condiciones}")
    lineas.append(f"Referencia: {referencia}." + (f" {retracto}" if retracto else ""))
    return "\n".join(lineas)


# ---- Herramientas ------------------------------------------------------------------------------
Contexto = tuple[Session, CanalIA, ContextoInteraccion, Conversacion, datetime, EstadoTurno]


def _verificar_identidad(c: Contexto, e: entradas.VerificarIdentidad) -> Resultado:
    db, canal, ctx, conv, ahora, estado = c
    cfg = _cfg(db, ctx)
    maximo = int(cfg.verificacion.get("max_intentos", 3))
    if conv.identidad_verificada:
        return Resultado({"verificada": True}, efecto="identidad")
    if conv.identidad_intentos >= maximo:
        raise ErrorHerramienta(
            "IDENTIDAD_BLOQUEADA", "Verificación bloqueada.", extra={"derivada": True}
        )
    cliente = db.get(Cliente, ctx.cliente_id)
    assert cliente is not None
    dado = re.sub(r"\D", "", e.numero_documento)
    real = re.sub(r"\D", "", cliente.numero_documento)
    if dado and dado == real:
        conv.identidad_verificada = True
        auditoria.registrar(
            db, "ia.identidad", None, "conversacion", conv.id,
            {"conversacion_id": conv.id, "resultado": "verificada"},
        )  # fmt: skip
        return Resultado({"verificada": True}, efecto="identidad")
    conv.identidad_intentos += 1
    restantes = maximo - conv.identidad_intentos
    auditoria.registrar(
        db, "ia.identidad", None, "conversacion", conv.id,
        {"conversacion_id": conv.id, "resultado": "fallida" if restantes > 0 else "bloqueada"},
    )  # fmt: skip
    if restantes > 0:
        return Resultado(
            {
                "codigo": "IDENTIDAD_NO_COINCIDE",
                "mensaje": "El documento no coincide con el registrado.",
                "intentos_restantes": restantes,
            },
            es_error=True,
            efecto="identidad",
        )
    from app.modulos.agente_ia.derivacion import resumen_fijo

    cola_id = canal.derivar(
        db, ctx.ref, "identidad_bloqueada", resumen_fijo(db, conv, "identidad_bloqueada"), ahora
    )
    auditoria.registrar(
        db, "ia.derivacion", None, "conversacion", conv.id,
        {"conversacion_id": conv.id, "motivo": "identidad_bloqueada", "origen": "guarda"},
    )  # fmt: skip
    estado.terminal, estado.cola_id = "identidad", cola_id
    return Resultado(
        {
            "codigo": "IDENTIDAD_BLOQUEADA",
            "mensaje": "Demasiados intentos fallidos: la conversación pasa a un asesor.",
            "derivada": True,
        },
        es_error=True,
        efecto="derivacion",
        referencia=("cola", cola_id),
    )


def _consultar_obligacion(c: Contexto, _e: entradas.SinEntrada) -> Resultado:
    db, _canal, ctx, _conv, ahora, _estado = c
    cc = _cc(db, ctx)
    reglas = _reglas_cobranza(_cfg(db, ctx))
    ob = _obligacion(cc)
    if ob.base(reglas) is None:
        raise ErrorHerramienta(
            "OBLIGACION_SIN_SALDO", "La obligación no tiene saldo para negociar."
        )
    vigente = _promesa_vigente(db, cc)
    hoy = _hoy(ctx, ahora)
    return Resultado(
        {
            "obligacion": {
                "numero_mascara": mascara_obligacion(cc.numero_obligacion),
                "producto": cc.producto,
                "saldo_total": lim.dos_decimales(cc.saldo_total)
                if cc.saldo_total is not None
                else None,
                "saldo_mora": lim.dos_decimales(cc.saldo_mora)
                if cc.saldo_mora is not None
                else None,
                "dias_mora": cc.dias_mora,
                "fecha_vencimiento": cc.fecha_vencimiento.isoformat()
                if cc.fecha_vencimiento
                else None,
            },
            "acuerdo_vigente": _acuerdo_dict(db, vigente),
            "condiciones": lim.condiciones_negociacion(ob, reglas, hoy),
            "fecha_hoy": hoy.isoformat(),
        }
    )


def _acuerdo_dict(db: Session, p: PromesaPago | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "monto_total": lim.dos_decimales(p.monto),
        "numero_cuotas": p.numero_cuotas,
        "fecha_primer_pago": p.fecha_pago.isoformat(),
        "estado": p.estado,
    }


def _rechazo(r: lim.Rechazo) -> ErrorHerramienta:
    return ErrorHerramienta(r.codigo, r.mensaje, r.limites)


def _plan(
    db: Session, ctx: ContextoInteraccion, ahora: datetime, e: entradas.SimularAcuerdo
) -> tuple[lim.Plan, ConfiguracionIACampana]:
    cfg = _cfg(db, ctx)
    r = lim.simular_acuerdo(
        _obligacion(_cc(db, ctx)),
        _reglas_cobranza(cfg),
        e.monto_total,
        e.numero_cuotas,
        e.fecha_primer_pago,
        e.periodicidad,
        _hoy(ctx, ahora),
    )
    if isinstance(r, lim.Rechazo):
        raise _rechazo(r)
    return r, cfg


def _simular_acuerdo(c: Contexto, e: entradas.SimularAcuerdo) -> Resultado:
    db, _canal, ctx, _conv, ahora, _estado = c
    cc = _cc(db, ctx)
    if _promesa_vigente(db, cc) is not None:
        raise ErrorHerramienta(
            "PROMESA_VIGENTE", "El cliente ya tiene un acuerdo de pago vigente en esta campaña."
        )
    plan, _ = _plan(db, ctx, ahora, e)
    return Resultado(plan.como_dict())


def _misma_simulacion(a: AccionIA, e: entradas.SimularAcuerdo) -> bool:
    x = a.entrada or {}
    try:
        return (
            lim.pesos(str(x.get("monto_total"))) == lim.pesos(e.monto_total)
            and x.get("numero_cuotas") == e.numero_cuotas
            and str(x.get("fecha_primer_pago")) == e.fecha_primer_pago.isoformat()
            and x.get("periodicidad") == e.periodicidad
        )
    except (ValueError, TypeError):
        return False


def _registrar_acuerdo(c: Contexto, e: entradas.RegistrarAcuerdo) -> Resultado:
    db, canal, ctx, conv, ahora, _estado = c
    _exigir_sin_gestion(db, conv)
    cc = _cc(db, ctx)
    if _promesa_vigente(db, cc) is not None:
        raise ErrorHerramienta("PROMESA_VIGENTE", "El cliente ya tiene un acuerdo vigente.")
    sim = next(
        (a for a in _acciones(db, conv, "simular_acuerdo_pago") if _misma_simulacion(a, e)), None
    )
    if sim is None:
        raise ErrorHerramienta(
            "SIMULACION_REQUERIDA",
            "Simula primero el acuerdo con exactamente los mismos valores.",
        )
    plan, cfg = _plan(db, ctx, ahora, e)
    mensaje_id = _localizar_cita(db, canal, ctx, e.confirmacion_cliente, sim.creado_en)
    datos = TipificacionDatos(
        resultado="promesa_pago",
        promesa=PromesaEntrada(monto=str(plan.monto_total), fecha_pago=plan.cuotas[0].fecha),
    )
    aplicada = _registrar_gestion(
        db,
        ctx,
        conv,
        datos,
        ahora,
        detalle_promesa=tip.DetallePromesa(
            plan.monto_total,
            [(q.fecha, q.monto) for q in plan.cuotas],
            plan.periodicidad,
            plan.descuento_porcentaje,
            cfg.version,
        ),
    )
    promesa = aplicada.promesa
    assert promesa is not None
    referencia = f"AP-{promesa.id}"
    _enviar_constancia(
        db,
        canal,
        ctx,
        texto_constancia_acuerdo(plan, referencia, get_settings().empresa_nombre),
        ahora,
    )
    auditoria.registrar(
        db, "ia.acuerdo_registrado", None, "promesa", promesa.id,
        {
            "conversacion_id": conv.id,
            "tipificacion_id": aplicada.tip.id,
            "promesa_id": promesa.id,
            "reglas_version": cfg.version,
        },
    )  # fmt: skip
    del mensaje_id
    return Resultado(
        {"registrado": True, "referencia": referencia, "constancia_enviada": True},
        efecto="promesa",
        referencia=("promesa", promesa.id),
        reglas_version=cfg.version,
    )


def _consultar_ofertas(c: Contexto, _e: entradas.SinEntrada) -> Resultado:
    db, _canal, ctx, _conv, _ahora, _estado = c
    reglas = _reglas_venta(_cfg(db, ctx))
    ofertas = db.scalars(
        select(OfertaCampana)
        .where(OfertaCampana.campana_id == ctx.campana_id, OfertaCampana.activa.is_(True))
        .order_by(OfertaCampana.codigo)
    )
    return Resultado(
        {
            "ofertas": [
                {
                    "codigo": o.codigo,
                    "nombre": o.nombre,
                    "descripcion": o.descripcion,
                    "precio": lim.dos_decimales(o.precio),
                    "descuento_max_pct": lim.dos_decimales(o.descuento_max_pct),
                    "max_unidades": o.max_unidades,
                    "condiciones": o.condiciones,
                }
                for o in ofertas
            ],
            "requiere_aceptacion_terminos": reglas.requiere_aceptacion_terminos,
        }
    )


def _oferta(db: Session, ctx: ContextoInteraccion, codigo: str) -> lim.OfertaDatos | None:
    o = db.scalar(
        select(OfertaCampana).where(
            OfertaCampana.campana_id == ctx.campana_id,
            OfertaCampana.codigo == codigo.strip().upper(),
        )
    )
    if o is None:
        return None
    return lim.OfertaDatos(
        o.codigo, o.nombre, o.descripcion, o.precio, o.descuento_max_pct, o.max_unidades,
        o.condiciones, o.activa,
    )  # fmt: skip


def _cotizar(db: Session, ctx: ContextoInteraccion, e: entradas.CotizarVenta):
    cfg = _cfg(db, ctx)
    r = lim.cotizar_venta(
        _oferta(db, ctx, e.codigo_oferta), _reglas_venta(cfg), e.unidades, e.descuento_porcentaje
    )
    if isinstance(r, lim.Rechazo):
        raise _rechazo(r)
    return r, cfg


def _cotizar_venta(c: Contexto, e: entradas.CotizarVenta) -> Resultado:
    cot, _ = _cotizar(c[0], c[2], e)
    return Resultado(cot.como_dict())


def _misma_cotizacion(a: AccionIA, e: entradas.CotizarVenta) -> bool:
    x = a.entrada or {}
    return (
        str(x.get("codigo_oferta", "")).strip().upper() == e.codigo_oferta.strip().upper()
        and x.get("unidades") == e.unidades
        and lim.parsear_porcentaje(str(x.get("descuento_porcentaje")))
        == lim.parsear_porcentaje(e.descuento_porcentaje)
        is not None
    )


def _registrar_venta(c: Contexto, e: entradas.RegistrarVenta) -> Resultado:
    db, canal, ctx, conv, ahora, _estado = c
    _exigir_sin_gestion(db, conv)
    cot_previa = next(
        (a for a in _acciones(db, conv, "cotizar_venta") if _misma_cotizacion(a, e)), None
    )
    if cot_previa is None:
        raise ErrorHerramienta(
            "COTIZACION_REQUERIDA", "Cotiza primero la venta con exactamente los mismos valores."
        )
    cot, cfg = _cotizar(db, ctx, e)
    _localizar_cita(db, canal, ctx, e.confirmacion_cliente, cot_previa.creado_en)
    oferta = db.scalar(
        select(OfertaCampana).where(
            OfertaCampana.campana_id == ctx.campana_id,
            OfertaCampana.codigo == cot.oferta.codigo,
        )
    )
    assert oferta is not None
    aplicada = _registrar_gestion(
        db,
        ctx,
        conv,
        TipificacionDatos(resultado="venta"),
        ahora,
        detalle_venta=tip.DetalleVenta(
            cot.oferta.nombre,
            cot.valor_total,
            cot.unidades,
            oferta.id,
            cot.descuento_porcentaje,
            cfg.version,
        ),  # fmt: skip
    )
    venta = aplicada.venta
    assert venta is not None
    referencia = f"V-{venta.id}"
    s = get_settings()
    _enviar_constancia(
        db,
        canal,
        ctx,
        texto_constancia_venta(cot, referencia, s.empresa_nombre, s.ia_texto_retracto),
        ahora,
    )
    auditoria.registrar(
        db, "ia.venta_registrada", None, "venta", venta.id,
        {
            "conversacion_id": conv.id,
            "tipificacion_id": aplicada.tip.id,
            "venta_id": venta.id,
            "oferta_id": oferta.id,
        },
    )  # fmt: skip
    return Resultado(
        {"registrado": True, "referencia": referencia, "constancia_enviada": True},
        efecto="venta",
        referencia=("venta", venta.id),
        reglas_version=cfg.version,
    )


def _historial(c: Contexto, _e: entradas.SinEntrada) -> Resultado:
    db, _canal, ctx, _conv, _ahora, _estado = c
    zona = ZoneInfo(ctx.zona_horaria)
    gestiones = []
    for t in db.scalars(
        select(Tipificacion)
        .where(Tipificacion.campana_cliente_id == ctx.campana_cliente_id)
        .order_by(Tipificacion.id.desc())
        .limit(10)
    ):
        promesa = db.scalar(select(PromesaPago).where(PromesaPago.tipificacion_id == t.id))
        gestiones.append(
            {
                "fecha": t.creado_en.astimezone(zona).date().isoformat(),
                "canal": t.canal,
                "resultado": t.resultado,
                "acuerdo": _acuerdo_dict(db, promesa),
            }
        )
    return Resultado({"gestiones": gestiones})


_FECHA_LOCAL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _seguimiento(c: Contexto, e: entradas.ProgramarSeguimiento) -> Resultado:
    db, _canal, ctx, conv, ahora, _estado = c
    _exigir_sin_gestion(db, conv)
    if not _FECHA_LOCAL.fullmatch(e.fecha_hora_local):
        raise ErrorHerramienta(
            "ENTRADA_INVALIDA",
            "Formato de fecha inválido; usa AAAA-MM-DDTHH:MM.",
            extra={"campos": ["fecha_hora_local"]},
        )
    zona = ZoneInfo(ctx.zona_horaria)
    try:
        cuando = datetime.strptime(e.fecha_hora_local, "%Y-%m-%dT%H:%M").replace(tzinfo=zona)
    except ValueError:
        raise ErrorHerramienta(
            "ENTRADA_INVALIDA", "Fecha inválida.", extra={"campos": ["fecha_hora_local"]}
        ) from None
    if not ahora + timedelta(minutes=5) < cuando <= ahora + timedelta(days=30):
        raise ErrorHerramienta(
            "FECHA_INVALIDA",
            "La fecha debe ser posterior a 5 minutos desde ahora y no exceder 30 días.",
        )
    politica, _ = cumplimiento.cargar_politica(db, ctx.tipo_campana)
    festivos = cumplimiento.cargar_festivos(db, cuando, politica)
    horario = motor.evaluar_horario(cuando, politica, festivos)
    if not horario.permitido:
        prox = horario.proxima_ventana_inicio
        raise ErrorHerramienta(
            "FUERA_DE_FRANJA",
            "Esa fecha está fuera del horario permitido para contactar.",
            {"proxima_ventana": prox.astimezone(zona).strftime("%Y-%m-%dT%H:%M") if prox else None},
        )
    datos = TipificacionDatos(
        resultado="volver_a_llamar",
        contacto_directo=conv.identidad_verificada,
        volver_a_llamar_en=cuando.astimezone(ahora.tzinfo),
        observacion=e.motivo or None,
    )
    _registrar_gestion(db, ctx, conv, datos, ahora, festivos=festivos)
    return Resultado(
        {"registrado": True, "fecha_hora_local": e.fecha_hora_local},
        efecto="seguimiento",
        referencia=None,
    )


def _autorizacion(c: Contexto, e: entradas.RegistrarAutorizacion) -> Resultado:
    db, canal, ctx, conv, ahora, _estado = c
    mensaje_id = _localizar_cita(db, canal, ctx, e.cita_cliente, None)
    try:
        a = servicio_autorizaciones.crear_por_ia(
            db,
            conv,
            ctx.tipo_campana,
            f"Conversación {conv.id}, mensaje {mensaje_id}: cita verificada",
            ahora,
        )
    except ErrorApp as exc:
        raise ErrorHerramienta(exc.codigo, exc.mensaje) from None
    auditoria.registrar(
        db, "ia.autorizacion", None, "autorizacion", a.id,
        {"conversacion_id": conv.id, "autorizacion_id": a.id},
    )  # fmt: skip
    return Resultado({"registrada": True}, efecto="autorizacion", referencia=("autorizacion", a.id))


def _opt_out(c: Contexto, e: entradas.RegistrarOptOut) -> Resultado:
    db, canal, ctx, conv, ahora, estado = c
    _localizar_cita(db, canal, ctx, e.cita_cliente, None)
    alcance = {"whatsapp": "whatsapp", "llamadas": "llamadas", "todos_los_canales": "todos"}[
        e.alcance
    ]
    canal.aplicar_opt_out(db, ctx.ref, alcance, ahora)
    auditoria.registrar(
        db, "ia.opt_out", None, "conversacion", conv.id,
        {"conversacion_id": conv.id, "alcance": e.alcance},
    )  # fmt: skip
    cerrada = alcance != "llamadas"
    if cerrada:
        estado.terminal = "optout"
    return Resultado(
        {"registrado": True, "conversacion_cerrada": cerrada},
        efecto="exclusion",
    )


def _derivar(c: Contexto, e: entradas.DerivarAHumano) -> Resultado:
    db, canal, ctx, conv, ahora, estado = c
    cola_id = canal.derivar(db, ctx.ref, e.motivo, e.resumen, ahora)
    auditoria.registrar(
        db, "ia.derivacion", None, "conversacion", conv.id,
        {"conversacion_id": conv.id, "motivo": e.motivo, "origen": "modelo"},
    )  # fmt: skip
    estado.terminal, estado.cola_id = "derivar", cola_id
    return Resultado(
        {"derivada": True, "hay_asesor_disponible": canal.hay_humano_disponible(db, ctx)},
        efecto="derivacion",
        referencia=("cola", cola_id),
    )


def _cerrar(c: Contexto, e: entradas.CerrarConversacion) -> Resultado:
    db, _canal, ctx, conv, ahora, estado = c
    if e.resultado in ("contactado", "rechazo") and not conv.identidad_verificada:
        raise ErrorHerramienta(
            "IDENTIDAD_NO_VERIFICADA", "Ese resultado exige haber verificado la identidad."
        )
    if e.resultado != "ninguno":
        _exigir_sin_gestion(db, conv)
        _registrar_gestion(
            db, ctx, conv, TipificacionDatos(resultado=e.resultado, observacion=e.resumen), ahora
        )
    estado.terminal, estado.cierre_resultado = "cierre", e.resultado
    return Resultado({"cierre_programado": True}, efecto="cierre_pendiente")


EJECUTORES: dict[str, Callable[[Contexto, Any], Resultado]] = {
    "verificar_identidad": _verificar_identidad,
    "consultar_obligacion": _consultar_obligacion,
    "simular_acuerdo_pago": _simular_acuerdo,
    "registrar_acuerdo_pago": _registrar_acuerdo,
    "consultar_ofertas": _consultar_ofertas,
    "cotizar_venta": _cotizar_venta,
    "registrar_venta": _registrar_venta,
    "consultar_historial_gestiones": _historial,
    "programar_seguimiento": _seguimiento,
    "registrar_autorizacion_whatsapp": _autorizacion,
    "registrar_opt_out": _opt_out,
    "derivar_a_humano": _derivar,
    "cerrar_conversacion": _cerrar,
}


# ---- Orquestación (Tx C) -----------------------------------------------------------------------
def _campos_invalidos(exc: ValidationError) -> list[str]:
    return sorted({".".join(str(p) for p in e["loc"]) or "(raíz)" for e in exc.errors()})


def _ejecutar(c: Contexto, nombre: str, entrada: Any) -> Resultado:
    """Comprobaciones comunes 1-4 y la herramienta (a salvo con SAVEPOINT)."""
    db, _canal, ctx, conv, _ahora, estado = c
    if nombre not in definiciones.nombres(ctx.canal, ctx.tipo_campana):
        raise ErrorHerramienta(
            "HERRAMIENTA_NO_DISPONIBLE", "Esa herramienta no está disponible en esta conversación."
        )
    try:
        modelo = entradas.MODELOS[nombre].model_validate(entrada if entrada is not None else {})
    except ValidationError as exc:
        raise ErrorHerramienta(
            "ENTRADA_INVALIDA",
            "La entrada de la herramienta no es válida.",
            extra={"campos": _campos_invalidos(exc)},
        ) from None
    if estado.terminal is not None:
        if estado.terminal == "cierre":
            raise ErrorHerramienta("CONVERSACION_EN_CIERRE", "La conversación ya se está cerrando.")
        raise ErrorHerramienta(
            "CONVERSACION_EN_TRASPASO", "La conversación ya no la atiende el asistente."
        )
    if nombre in definiciones.REQUIEREN_IDENTIDAD and not conv.identidad_verificada:
        cfg = db.get(ConfiguracionIACampana, ctx.campana_id)
        maximo = int(cfg.verificacion.get("max_intentos", 3)) if cfg else 3
        if conv.identidad_intentos >= maximo:
            raise ErrorHerramienta("IDENTIDAD_BLOQUEADA", "Verificación bloqueada.")
        raise ErrorHerramienta(
            "IDENTIDAD_NO_VERIFICADA", "Verifica primero la identidad del titular."
        )
    return EJECUTORES[nombre](c, modelo)


def ejecutar_herramienta(
    sesion: Callable[[], Session],
    canal: CanalIA,
    ctx: ContextoInteraccion,
    tool_use: dict[str, Any],
    estado: EstadoTurno,
    reloj: Callable[[], datetime],
    trabajador: str,
) -> Ejecucion | None:
    """Tx C. Devuelve `None` si la revalidación falla (el turno debe detenerse sin añadir
    resultados: la reparación los completará como `INTERRUMPIDO`)."""
    nombre, tid = tool_use["name"], tool_use["id"]
    entrada = tool_use.get("input")
    inicio = time.perf_counter()
    with sesion() as db:
        ahora = reloj()
        if nombre in CON_CLIENTE:
            db.execute(
                select(Cliente.id).where(Cliente.id == ctx.cliente_id).with_for_update()
            ).all()
        est = canal.bloquear(db, ctx.ref)
        propia = estado.terminal is not None
        if not propia and not (est.abierta and est.dueno == "ia"):
            db.rollback()
            return None
        if not propia and not configuracion.ia_disponible(db, ctx.campana_id):
            db.rollback()
            return None
        if not arrendamiento.renovar(db, ctx.ref, trabajador, ahora):
            db.rollback()
            return None
        previa = db.scalar(select(AccionIA).where(AccionIA.tool_use_id == tid))
        if previa is not None:
            db.rollback()
            return Ejecucion(previa.resultado, previa.es_error, previa.id)
        conv = db.get(Conversacion, ctx.ref.id)
        assert conv is not None
        db.refresh(conv)
        contexto: Contexto = (db, canal, ctx, conv, ahora, estado)
        estado_previo = (estado.terminal, estado.cola_id, estado.cierre_resultado)
        try:
            with db.begin_nested():
                r = _ejecutar(contexto, nombre, entrada)
        except ErrorHerramienta as exc:
            estado.terminal, estado.cola_id, estado.cierre_resultado = estado_previo
            r = Resultado(exc.como_dict(), es_error=True)
        accion = AccionIA(
            conversacion_id=ctx.ref.id if ctx.ref.tipo == "conversacion" else None,
            llamada_id=ctx.ref.id if ctx.ref.tipo == "llamada" else None,
            campana_id=ctx.campana_id,
            tool_use_id=tid,
            herramienta=nombre,
            entrada=enmascarar_entrada(nombre, entrada),
            resultado=r.datos,
            es_error=r.es_error,
            codigo_error=r.codigo_error,
            efecto=r.efecto,
            referencia_tipo=r.referencia[0] if r.referencia else None,
            referencia_id=r.referencia[1] if r.referencia else None,
            reglas_version=r.reglas_version,
            duracion_ms=int((time.perf_counter() - inicio) * 1000),
            creado_en=ahora,
        )
        try:
            with db.begin_nested():
                db.add(accion)
                db.flush()
        except IntegrityError:  # otra transacción ejecutó el mismo tool_use_id
            db.rollback()
            ya = db.scalar(select(AccionIA).where(AccionIA.tool_use_id == tid))
            if ya is None:
                raise
            return Ejecucion(ya.resultado, ya.es_error, ya.id)
        eventos.publicar_accion(
            db, ctx.ref.tipo, ctx.ref.id, ctx.campana_id, accion.id, nombre, r.es_error,
            r.codigo_error,
        )  # fmt: skip
        db.commit()
        return Ejecucion(r.datos, r.es_error, accion.id)
