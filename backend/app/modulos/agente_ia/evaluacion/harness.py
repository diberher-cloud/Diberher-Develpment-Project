"""Arnés de evaluación: ejecuta un caso en una BD SQLite en memoria AISLADA (nunca la de la
aplicación) con el flujo real de WhatsApp (webhook simulado -> trabajos -> turno) y califica el
resultado (fase-2c.md §7.3)."""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app import registro_modelos  # noqa: F401
from app.config import get_settings
from app.db import Base, crear_engine
from app.integraciones.whatsapp import fabrica
from app.integraciones.whatsapp.falso import ProveedorWhatsAppFalso
from app.modulos.agente_ia.evaluacion import calificadores
from app.modulos.agente_ia.evaluacion.casos import resolver_reglas
from app.modulos.agente_ia.evaluacion.informe import ResultadoCaso
from app.modulos.agente_ia.llm import ClienteLLM, establecer_cliente_llm
from app.modulos.agente_ia.llm_falso import ClienteLLMFalso
from app.modulos.agente_ia.modelos import AccionIA, ConfiguracionIACampana, OfertaCampana, UsoIA
from app.modulos.auditoria.modelos import Auditoria
from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola.modelos import EstadoAgente, PromesaPago, Tipificacion, Venta
from app.modulos.conversaciones.modelos import ColaAtencion, Conversacion, Mensaje
from app.modulos.cumplimiento.modelos import PoliticaCumplimiento
from app.modulos.cumplimiento.politica import politica_por_defecto
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.usuarios.modelos import Usuario
from app.modulos.whatsapp.modelos import AutorizacionCanal
from app.modulos.whatsapp.servicio_entrante import recibir
from app.tiempo_real import bus
from app.trabajos.cola import ejecutar_pendientes

NUMERO_DEFECTO = "+573001234567"
MOTIVOS_NO_IA = ("entrante", "sin_campana", "liberada", "agente_desconectado")
CANAL_OPT_OUT = {"whatsapp": "whatsapp", "todos": "todos_los_canales", "voz": "llamadas"}


class RelojCaso:
    def __init__(self, inicio: datetime) -> None:
        self.actual = inicio

    def __call__(self) -> datetime:
        return self.actual

    def avanzar(self, segundos: float) -> None:
        self.actual += timedelta(seconds=segundos)


class Registrador:
    """Envuelve un `ClienteLLM` real y guarda las peticiones (evaluación online)."""

    def __init__(self, cliente: ClienteLLM) -> None:
        self.cliente = cliente
        self.peticiones: list[dict[str, Any]] = []
        self.llamadas = 0

    def crear_mensaje(self, **kw: Any):
        self.llamadas += 1
        self.peticiones.append(
            {
                "sistema": kw["sistema"],
                "herramientas": kw["herramientas"],
                "mensajes": kw["mensajes"],
            }
        )
        return self.cliente.crear_mensaje(**kw)


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lineas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lineas.append(record.getMessage())


def _sembrar(
    db, caso: dict[str, Any], reloj: RelojCaso, modelo: str | None, esfuerzo: str | None
) -> dict[str, Any]:
    ahora = reloj()
    for tipo in ("venta", "cobranza"):
        cfg = politica_por_defecto()
        for clave, valor in caso.get("politica", {}).items():
            cfg[clave] = {**cfg[clave], **valor} if isinstance(valor, dict) else valor
        db.add(PoliticaCumplimiento(tipo_campana=tipo, version=1, configuracion=cfg, activa=True))
    admin = Usuario(
        email="evaluacion@ejemplo.invalid",
        nombre="Evaluación",
        rol="administrador",
        password_hash="x",
        activo=True,
    )
    agente = Usuario(
        email="agente@ejemplo.invalid",
        nombre="Agente",
        rol="agente",
        password_hash="x",
        activo=True,
    )
    db.add_all([admin, agente])
    db.flush()
    c = caso["campana"]
    campana = Campana(
        nombre="Campaña de evaluación",
        tipo=c["tipo"],
        estado="activa",
        whatsapp_habilitado=True,
        creado_por=admin.id,
    )
    db.add(campana)
    db.flush()
    db.add(CampanaAgente(campana_id=campana.id, usuario_id=agente.id))
    db.add(
        EstadoAgente(usuario_id=agente.id, estado="disponible", desde=ahora, actualizado_en=ahora)
    )
    valores: dict[str, Any] = {
        "campana_id": campana.id,
        "activa": True,
        "version": 1,
        "modelo": modelo or get_settings().ia_modelo_por_defecto,
        "esfuerzo": esfuerzo or get_settings().ia_esfuerzo_por_defecto,
        "prompt_version": 1,
        "tratamiento": c.get("tratamiento", "usted"),
        "instrucciones": c.get("instrucciones"),
        "verificacion": {"factores": ["numero_documento"], "max_intentos": 3},
        "reglas": resolver_reglas(caso),
        "presupuesto_usd_mensual": Decimal("200.00"),
        "max_costo_conversacion_usd": Decimal("0.8000"),
        "max_turnos_conversacion": 30,
        "actualizado_por": admin.id,
        "actualizado_en": ahora,
        "creado_en": ahora,
    }
    for k, v in c.get("config", {}).items():
        valores[k] = Decimal(v) if isinstance(v, str) else v
    db.add(ConfiguracionIACampana(**valores))
    for o in c.get("ofertas", []):
        db.add(
            OfertaCampana(
                campana_id=campana.id,
                codigo=o["codigo"],
                nombre=o["nombre"],
                descripcion=o.get("descripcion"),
                precio=Decimal(o["precio"]),
                descuento_max_pct=Decimal(o.get("descuento_max_pct", "0")),
                max_unidades=o.get("max_unidades", 1),
                condiciones=o.get("condiciones"),
                creado_en=ahora,
                actualizado_en=ahora,
            )
        )

    def registro(datos: dict[str, Any], numero: str) -> CampanaCliente:
        cliente = Cliente(
            tipo_documento=datos.get("tipo_documento", "CC"),
            numero_documento=datos["numero_documento"],
            nombre=datos["nombre"],
        )
        db.add(cliente)
        db.flush()
        db.add(Telefono(cliente_id=cliente.id, numero_e164=numero, tipo_linea="movil", prioridad=1))
        ob = datos.get("obligacion", {})
        cc = CampanaCliente(
            campana_id=campana.id,
            cliente_id=cliente.id,
            numero_obligacion=ob.get("numero_obligacion"),
            saldo_total=Decimal(ob["saldo_total"]) if ob.get("saldo_total") else None,
            saldo_mora=Decimal(ob["saldo_mora"]) if ob.get("saldo_mora") else None,
            dias_mora=ob.get("dias_mora"),
            fecha_vencimiento=date.fromisoformat(ob["fecha_vencimiento"])
            if ob.get("fecha_vencimiento")
            else None,
            producto=ob.get("producto"),
        )
        db.add(cc)
        db.flush()
        return cc

    numero = caso["cliente"].get("numero", NUMERO_DEFECTO)
    cc = registro(caso["cliente"], numero)
    if caso.get("otro_cliente_mismo_campana"):
        registro(
            {
                "nombre": "Pedro Gómez",
                "numero_documento": "99887766",
                "obligacion": {
                    "numero_obligacion": "OB-002",
                    "saldo_total": "777777.00",
                    "saldo_mora": "777777.00",
                    "dias_mora": 30,
                },
            },
            "+573009998877",
        )
    if caso["cliente"].get("autorizacion"):
        db.add(
            AutorizacionCanal(
                numero_e164=numero,
                canal="whatsapp",
                finalidad=c["tipo"],
                origen="importacion",
                evidencia="evaluacion",
                otorgada_en=ahora - timedelta(days=30),
                clave_vigente=f"{numero}|whatsapp|{c['tipo']}",
                creado_en=ahora,
            )
        )
    pv = caso["cliente"].get("promesa_vigente")
    if pv:
        tip = Tipificacion(
            campana_cliente_id=cc.id,
            canal="voz",
            origen="agente",
            usuario_id=admin.id,
            resultado="promesa_pago",
            contacto_directo=True,
            creado_en=ahora - timedelta(days=2),
        )
        db.add(tip)
        db.flush()
        db.add(
            PromesaPago(
                tipificacion_id=tip.id,
                campana_cliente_id=cc.id,
                monto=Decimal(pv["monto"]),
                fecha_pago=date.fromisoformat(pv["fecha_pago"]),
                numero_cuotas=1,
                descuento_porcentaje=Decimal("0"),
                estado="vigente",
                origen="agente",
                creado_en=ahora - timedelta(days=2),
            )
        )
    db.commit()
    return {"campana_id": campana.id, "numero": numero, "cc_id": cc.id}


def _params(texto: str | dict[str, Any], numero: str) -> dict[str, str]:
    empresa = get_settings().whatsapp_numero_empresa
    p = {
        "MessageSid": "SM" + uuid.uuid4().hex,
        "From": f"whatsapp:{numero}",
        "To": f"whatsapp:{empresa}",
        "Body": "",
        "NumMedia": "0",
    }
    if isinstance(texto, str):
        p["Body"] = texto
    else:
        p["Body"] = texto.get("texto", "")
        if texto.get("media"):
            p["NumMedia"] = "1"
            p["MediaUrl0"] = "https://media.falso.invalid/evaluacion"
            p["MediaContentType0"] = texto["media"].get("tipo_contenido", "audio/ogg")
    return p


def _preparar_guion(guion: list[dict[str, Any]], motor) -> list[dict[str, Any]]:
    pasos = []
    for paso in guion:
        paso = dict(paso)
        if paso.get("antes") == "desactivar_ia":
            paso["antes"] = lambda _p: _desactivar_ia(motor)
        pasos.append(paso)
    return pasos


def _desactivar_ia(motor) -> None:
    fabrica_s = sessionmaker(bind=motor, expire_on_commit=False)
    with fabrica_s() as s:
        s.execute(update(ConfiguracionIACampana).values(activa=False, desactivada_motivo="manual"))
        s.commit()


def _estado(db, caso, ctx) -> dict[str, Any]:
    conv = db.scalar(
        select(Conversacion)
        .where(Conversacion.numero_cliente_e164 == ctx["numero"])
        .order_by(Conversacion.id.desc())
    )
    if conv is None:
        return {
            "acciones": [],
            "textos_enviados": [],
            "mensajes_ia": [],
            "promesa": None,
            "venta": None,
            "identidad_verificada": False,
            "verificada_en": None,
            "derivacion": None,
            "opt_out": None,
            "cerrada": False,
            "motivo_cierre": None,
            "resultado_tipificacion": None,
            "guardas": set(),
            "costo_usd": 0.0,
            "auditoria": set(),
            "llamadas_modelo": 0,
        }
    acciones = [
        {
            "herramienta": a.herramienta,
            "codigo_error": a.codigo_error,
            "es_error": a.es_error,
            "efecto": a.efecto,
            "resultado": a.resultado,
            "creado_en": a.creado_en,
        }
        for a in db.scalars(
            select(AccionIA).where(AccionIA.conversacion_id == conv.id).order_by(AccionIA.id)
        )
    ]
    salientes = [
        m
        for m in db.scalars(
            select(Mensaje)
            .where(Mensaje.conversacion_id == conv.id, Mensaje.direccion == "saliente")
            .order_by(Mensaje.id)
        )
        if m.estado != "cancelado"
    ]
    ia = [
        {"cuerpo": m.cuerpo or "", "creado_en": m.creado_en} for m in salientes if m.autor == "ia"
    ]
    tip = db.scalar(select(Tipificacion).where(Tipificacion.conversacion_id == conv.id))
    promesa = venta = None
    if tip:
        p = db.scalar(select(PromesaPago).where(PromesaPago.tipificacion_id == tip.id))
        if p:
            promesa = {"monto_total": f"{p.monto:.2f}", "numero_cuotas": p.numero_cuotas}
        v = db.scalar(select(Venta).where(Venta.tipificacion_id == tip.id))
        if v:
            venta = {"valor": f"{v.valor:.2f}", "unidades": v.unidades}
    cola = [
        f.motivo
        for f in db.scalars(
            select(ColaAtencion)
            .where(ColaAtencion.conversacion_id == conv.id)
            .order_by(ColaAtencion.id)
        )
        if f.motivo not in MOTIVOS_NO_IA
    ]
    exc = [
        e.canal
        for e in db.scalars(
            select(Exclusion).where(
                Exclusion.numero_e164 == ctx["numero"], Exclusion.motivo == "solicitud_titular"
            )
        )
    ]
    opt = None
    if exc:
        opt = CANAL_OPT_OUT["todos" if "todos" in exc else exc[0]]
    verif = [
        a["creado_en"]
        for a in acciones
        if a["herramienta"] == "verificar_identidad" and (a["resultado"] or {}).get("verificada")
    ]
    auditoria = list(db.scalars(select(Auditoria).where(Auditoria.entidad_id.is_not(None))))
    ids_conv = {str(conv.id)}
    guardas = {
        a.detalle.get("codigo")
        for a in auditoria
        if a.accion == "ia.guarda" and str(a.detalle.get("conversacion_id")) in ids_conv
    }
    acc_aud = {a.accion for a in db.scalars(select(Auditoria))}
    usos = list(db.scalars(select(UsoIA).where(UsoIA.conversacion_id == conv.id)))
    return {
        "acciones": acciones,
        "textos_enviados": [m.cuerpo or "" for m in salientes if m.autor in ("ia", "sistema")],
        "mensajes_ia": ia,
        "promesa": promesa,
        "venta": venta,
        "identidad_verificada": conv.identidad_verificada,
        "verificada_en": min(verif) if verif else None,
        "derivacion": cola[-1] if cola else None,
        "opt_out": opt,
        "cerrada": conv.estado == "cerrada",
        "motivo_cierre": conv.motivo_cierre,
        "resultado_tipificacion": tip.resultado if tip else None,
        "guardas": guardas,
        "costo_usd": float(sum((u.costo_usd for u in usos), Decimal(0))),
        "auditoria": acc_aud,
        "llamadas_modelo": len(usos),
        "_usos": usos,
    }


def ejecutar_caso(
    caso: dict[str, Any],
    modo: str = "offline",
    cliente_llm: ClienteLLM | None = None,
    max_costo_online: Decimal = Decimal("0.50"),
    modelo: str | None = None,
    esfuerzo: str | None = None,
) -> ResultadoCaso:
    inicio = time.perf_counter()
    motor = crear_engine("sqlite+pysqlite://")
    Base.metadata.create_all(motor)
    fabrica_s = sessionmaker(bind=motor, autoflush=True, expire_on_commit=False)
    reloj = RelojCaso(datetime.fromisoformat(caso["reloj"]).astimezone(UTC))
    manejador_logs = _Logs()
    raiz = logging.getLogger()
    nivel_previo = raiz.level
    raiz.addHandler(manejador_logs)
    raiz.setLevel(logging.INFO)
    bus_previo, proveedor_previo = bus._bus, fabrica._instancia
    bus.establecer_bus(bus.BusMemoria())
    fabrica._instancia = ProveedorWhatsAppFalso(get_settings().twilio_auth_token)
    fallos: list[str] = []
    try:
        with fabrica_s() as db:
            ctx = _sembrar(db, caso, reloj, modelo, esfuerzo)
        if modo == "offline":
            llm: Any = ClienteLLMFalso(_preparar_guion(caso.get("guion_llm_falso", []), motor))
        else:
            assert cliente_llm is not None
            llm = Registrador(cliente_llm)
        establecer_cliente_llm(llm)
        pasos = caso.get("pasos_por_turno") or []
        debounce = get_settings().ia_debounce_segundos + 1
        proveedor = fabrica._instancia
        for i, turno in enumerate(caso["turnos_cliente"]):
            antes = llm.llamadas
            with fabrica_s() as db:
                recibir(db, proveedor, _params(turno, ctx["numero"]), reloj())
                ejecutar_pendientes(db, reloj())
                reloj.avanzar(debounce)
                ejecutar_pendientes(db, reloj())
            reloj.avanzar(30)
            if modo == "offline" and pasos and llm.llamadas - antes != pasos[i]:
                fallos.append(
                    f"turno {i + 1}: {llm.llamadas - antes} llamadas al modelo "
                    f"(se esperaban {pasos[i]})"
                )
            if modo == "online":
                with fabrica_s() as db:
                    gastado = sum((u.costo_usd for u in db.scalars(select(UsoIA))), Decimal(0))
                limite = Decimal(str(caso["expectativas"].get("max_costo_usd", max_costo_online)))
                if gastado > limite:
                    fallos.append(f"se superó el coste máximo del caso ({gastado} > {limite})")
                    break
        if modo == "offline" and llm.llamadas != len(caso.get("guion_llm_falso", [])):
            fallos.append(
                f"el guion no se consumió entero ({llm.llamadas} de {len(caso['guion_llm_falso'])})"
            )
        with fabrica_s() as db:
            estado = _estado(db, caso, ctx)
        fallos += calificadores.evaluar_expectativas(caso, estado)
        fallos += calificadores.evaluar_siempre(caso, estado, llm.peticiones, manejador_logs.lineas)
        usos = estado.pop("_usos", [])
    except Exception as exc:  # un fallo del arnés es un fallo del caso (sin datos personales)
        fallos.append(f"error del arnés: {type(exc).__name__}")
        usos = []
    finally:
        raiz.removeHandler(manejador_logs)
        raiz.setLevel(nivel_previo)
        establecer_cliente_llm(None)
        bus.establecer_bus(bus_previo)
        fabrica._instancia = proveedor_previo
        motor.dispose()
    return ResultadoCaso(
        id=caso["id"],
        categoria=caso["categoria"],
        aprobado=not fallos,
        fallos=fallos,
        costo_usd=sum((u.costo_usd for u in usos), Decimal(0)),
        input_tokens=sum(u.input_tokens for u in usos),
        cache_read=sum(u.cache_read_input_tokens for u in usos),
        cache_creation=sum(u.cache_creation_input_tokens for u in usos),
        duracion_ms=int((time.perf_counter() - inicio) * 1000),
    )


def ejecutar_casos(
    casos: list[dict[str, Any]],
    modo: str = "offline",
    cliente_llm: ClienteLLM | None = None,
    al_terminar: Callable[[ResultadoCaso], None] | None = None,
    modelo: str | None = None,
    esfuerzo: str | None = None,
) -> list[ResultadoCaso]:
    resultados = []
    for caso in casos:
        r = ejecutar_caso(caso, modo, cliente_llm, modelo=modelo, esfuerzo=esfuerzo)
        resultados.append(r)
        if al_terminar:
            al_terminar(r)
    return resultados
