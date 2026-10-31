"""Migración 0004 (agente IA) en SQLite: datos de 2B intactos, CHECK y semilla."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from alembic.config import Config
from app.db import crear_engine

RAIZ = Path(__file__).parent.parent.parent


def _cfg(ruta) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{ruta}")
    return cfg


@pytest.fixture()
def bd(tmp_path):
    ruta = tmp_path / "m.db"
    cfg = _cfg(ruta)
    command.upgrade(cfg, "0003")
    d = "2026-01-01"
    con = sqlite3.connect(ruta)
    con.executescript(
        f"""
        insert into usuarios(email,nombre,rol,password_hash,activo,creado_en,actualizado_en) values('a@a.co','A','administrador','x',1,'{d}','{d}');
        insert into campanas(nombre,tipo,estado,max_intentos,intervalo_reintento_minutos,creado_por,creado_en,actualizado_en) values('c','cobranza','activa',3,60,1,'{d}','{d}');
        insert into clientes(tipo_documento,numero_documento,nombre,creado_en,actualizado_en) values('CC','1','N','{d}','{d}');
        insert into campana_clientes(campana_id,cliente_id,estado,datos_adicionales,intentos,creado_en) values(1,1,'pendiente','{{}}',0,'{d}');
        insert into conversaciones(clave_abierta,numero_cliente_e164,numero_empresa_e164,estado,atendida_por,iniciada_por,ultimo_mensaje_en,abierta_en,mensajes_sin_leer,identidad_verificada,identidad_intentos,turnos_ia,costo_usd_acumulado) values('k','+573001234567','+573000000001','abierta','sin_asignar','cliente','{d}','{d}',0,0,0,0,0);
        """
    )
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    return ruta, cfg


def _ejecutar(ruta, sql):
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.execute(sql)
        con.commit()
    finally:
        con.close()


def test_semilla_y_datos_de_2b_intactos(bd):
    ruta, cfg = bd
    con = sqlite3.connect(ruta)
    assert con.execute("select clave, valor from configuracion_global").fetchall() == [
        ("ia_activa", "true")
    ]
    assert con.execute("select count(*) from conversaciones").fetchone() == (1,)
    assert con.execute("select count(*) from campana_clientes").fetchone() == (1,)
    con.close()
    command.downgrade(cfg, "0003")
    command.upgrade(cfg, "head")
    con = sqlite3.connect(ruta)
    assert con.execute("select count(*) from conversaciones").fetchone() == (1,)
    con.close()


D = "'2026-01-01'"
CHECKS = {
    "uso_exactamente_uno_ambos_nulos": f"insert into errores_ia(campana_id,codigo,transitorio,creado_en) values(1,'X',0,{D})",
    "uso_exactamente_uno_ambos_llenos": f"insert into errores_ia(conversacion_id,llamada_id,campana_id,codigo,transitorio,creado_en) values(1,1,1,'X',0,{D})",
    "historial_rol": f"insert into historial_ia(conversacion_id,secuencia,rol,tipo,contenido,creado_en) values(1,1,'otro','control','[]',{D})",
    "historial_tipo": f"insert into historial_ia(conversacion_id,secuencia,rol,tipo,contenido,creado_en) values(1,1,'user','raro','[]',{D})",
    "accion_efecto": f"insert into acciones_ia(conversacion_id,campana_id,tool_use_id,herramienta,entrada,resultado,es_error,efecto,duracion_ms,creado_en) values(1,1,'t','h','{{}}','{{}}',0,'raro',1,{D})",
    "config_esfuerzo": f"insert into configuracion_ia_campana(campana_id,modelo,esfuerzo,verificacion,reglas,presupuesto_usd_mensual,max_costo_conversacion_usd,actualizado_en,creado_en) values(1,'m','extremo','{{}}','{{}}',1,1,{D},{D})",
    "bloqueo_exactamente_uno": f"insert into bloqueos_turno_ia(clave,trabajador,adquirido_en,expira_en) values('k','w',{D},{D})",
    "evaluacion_modo": f"insert into evaluaciones_ia(modo,canal,prompt_version,huella,estado,resumen,casos,creado_en) values('x','chat',1,'h','pendiente','{{}}','[]',{D})",
}


@pytest.mark.parametrize("nombre", sorted(CHECKS))
def test_checks_rechazan_valores_invalidos(bd, nombre):
    ruta, _ = bd
    with pytest.raises(sqlite3.IntegrityError):
        _ejecutar(ruta, CHECKS[nombre])


def test_checks_de_promesas_y_ventas_y_modelo_orm(bd):
    ruta, _ = bd
    with pytest.raises(sqlite3.IntegrityError):
        _ejecutar(
            ruta,
            f"insert into tipificaciones(campana_cliente_id,canal,origen,resultado,contacto_directo,creado_en) values(1,'voz','sistema','venta',1,{D})",
        )
        _ejecutar(
            ruta,
            f"insert into ventas(tipificacion_id,campana_cliente_id,producto,valor,unidades,origen,descuento_porcentaje,creado_en) values(1,1,'p',10,1,'sistema',101,{D})",
        )
    _ejecutar(
        ruta,
        f"insert into tipificaciones(campana_cliente_id,canal,origen,resultado,contacto_directo,creado_en) values(1,'voz','sistema','promesa_pago',1,{D})",
    )
    with pytest.raises(sqlite3.IntegrityError):
        _ejecutar(
            ruta,
            f"insert into promesas_pago(tipificacion_id,campana_cliente_id,monto,fecha_pago,numero_cuotas,descuento_porcentaje,estado,origen,periodicidad,creado_en) values(1,1,10,{D},1,0,'vigente','sistema','diaria',{D})",
        )
    engine = crear_engine(f"sqlite:///{ruta}")
    with engine.connect() as c:
        assert c.execute(text("select count(*) from promesas_pago")).scalar() == 0
    engine.dispose()
    assert IntegrityError
