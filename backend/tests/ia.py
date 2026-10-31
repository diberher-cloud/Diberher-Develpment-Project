"""Ayudantes de los tests de la subfase 2C (agente IA): escenario, cliente falso y webhooks."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from wa import NUMERO, entrante, plantilla

from app.modulos.agente_ia.llm import establecer_cliente_llm
from app.modulos.agente_ia.llm_falso import ClienteLLMFalso
from app.modulos.agente_ia.modelos import ConfiguracionIACampana, OfertaCampana
from app.modulos.campanas.modelos import CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono

REGLAS_COBRANZA = {
    "base_descuento": "saldo_mora",
    "descuento_max_pct": "20.00",
    "descuento_max_pct_por_cuotas": [
        {"max_cuotas": 1, "descuento_max_pct": "20.00"},
        {"max_cuotas": 3, "descuento_max_pct": "10.00"},
        {"max_cuotas": 6, "descuento_max_pct": "0.00"},
    ],
    "monto_minimo_promesa": "100000.00",
    "monto_minimo_cuota": "50000.00",
    "max_cuotas": 6,
    "plazo_max_dias_primer_pago": 14,
    "plazo_max_dias_total": 90,
    "periodicidades": ["quincenal", "mensual"],
}
REGLAS_VENTA = {"max_unidades_por_venta": 2, "requiere_aceptacion_terminos": True}
DOC_MARIA = "1020304050"
DOC_PEDRO = "99887766"
NUMERO_PEDRO = "+573009998877"


def crear_config(db, campana, usuario_id, reglas=None, **kw):
    ahora = datetime(2026, 10, 1, tzinfo=UTC)
    valores = {
        "campana_id": campana.id,
        "activa": True,
        "version": 1,
        "modelo": "claude-opus-5-5",
        "esfuerzo": "medium",
        "prompt_version": 1,
        "tratamiento": "usted",
        "instrucciones": None,
        "verificacion": {"factores": ["numero_documento"], "max_intentos": 3},
        "reglas": reglas or (REGLAS_COBRANZA if campana.tipo == "cobranza" else REGLAS_VENTA),
        "presupuesto_usd_mensual": Decimal("200.00"),
        "max_costo_conversacion_usd": Decimal("0.8000"),
        "max_turnos_conversacion": 30,
        "actualizado_por": usuario_id,
        "actualizado_en": ahora,
        "creado_en": ahora,
    }
    valores.update(kw)
    cfg = ConfiguracionIACampana(**valores)
    db.add(cfg)
    db.commit()
    return cfg


def _registro(db, campana, doc, nombre, numero, saldo_total, saldo_mora, obligacion):
    cliente = Cliente(tipo_documento="CC", numero_documento=doc, nombre=nombre)
    db.add(cliente)
    db.flush()
    db.add(Telefono(cliente_id=cliente.id, numero_e164=numero, tipo_linea="movil", prioridad=1))
    cc = CampanaCliente(
        campana_id=campana.id,
        cliente_id=cliente.id,
        numero_obligacion=obligacion,
        saldo_total=Decimal(saldo_total),
        saldo_mora=Decimal(saldo_mora),
        dias_mora=45,
        fecha_vencimiento=date(2026, 9, 15),
    )
    db.add(cc)
    db.commit()
    return cc


def escenario_ia(esc, crear_usuario, db, tipo="cobranza", **kw_config):
    """Campaña con IA activa, un agente asignado, María (registro) y Pedro (para fugas)."""
    agente = crear_usuario("agente")
    campana = esc.campana(tipo=tipo, whatsapp_habilitado=True)
    db.add(CampanaAgente(campana_id=campana.id, usuario_id=agente.id))
    db.commit()
    cfg = crear_config(db, campana, esc.creador_id, **kw_config)
    cc = _registro(
        db, campana, DOC_MARIA, "María Pérez", NUMERO, "1500000.00", "300000.00", "OB-001"
    )
    pedro = _registro(
        db, campana, DOC_PEDRO, "Pedro Gómez", NUMERO_PEDRO, "777777.00", "777777.00", "OB-002"
    )
    oferta = None
    if tipo == "venta":
        oferta = OfertaCampana(
            campana_id=campana.id,
            codigo="SEG-HOGAR",
            nombre="Seguro hogar",
            precio=Decimal("89900.00"),
            descuento_max_pct=Decimal("10.00"),
            max_unidades=2,
            condiciones="Vigencia anual.",
            creado_en=datetime(2026, 10, 1, tzinfo=UTC),
            actualizado_en=datetime(2026, 10, 1, tzinfo=UTC),
        )
        db.add(oferta)
        db.commit()
    plantilla(db, finalidad=tipo)
    return SimpleNamespace(
        agente=agente, campana=campana, cfg=cfg, cc=cc, pedro=pedro, oferta=oferta, numero=NUMERO
    )


def usar_llm(guion, retardo: float = 0.0) -> ClienteLLMFalso:
    llm = ClienteLLMFalso(guion, retardo=retardo)
    establecer_cliente_llm(llm)
    return llm


def herramienta(nombre: str, **entrada):
    return {"herramientas": [{"name": nombre, "input": entrada}]}


def escribir(client, firmar_twilio, correr, reloj, texto, numero=NUMERO, avanzar=30, turno=True):
    """Mensaje entrante del cliente + trabajos (procesar y, tras el *debounce*, el turno)."""
    entrante(client, firmar_twilio, numero, texto)
    correr(reloj())
    if turno:
        reloj.avanzar(seconds=avanzar)
        correr(reloj())
        reloj.avanzar(seconds=avanzar)
        correr(reloj())  # envíos creados durante el turno


def mensajes_de(db, conv_id, autor=None):
    from app.modulos.conversaciones.modelos import Mensaje

    consulta = select(Mensaje).where(Mensaje.conversacion_id == conv_id)
    if autor:
        consulta = consulta.where(Mensaje.autor == autor)
    return list(db.scalars(consulta.order_by(Mensaje.id)))


def adelantar(reloj, **kw):
    reloj.fijar(reloj() + timedelta(**kw))
