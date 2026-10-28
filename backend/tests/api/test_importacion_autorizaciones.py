"""Importación de clientes con las columnas de opt-in de WhatsApp (§4.10)."""

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.modulos.auditoria.modelos import Auditoria
from app.modulos.clientes.modelos import CampanaCliente
from app.modulos.whatsapp.modelos import AutorizacionCanal

CAB = (
    "tipo_documento,numero_documento,nombre,telefono_1,telefono_2,"
    "autoriza_whatsapp,fecha_autorizacion_whatsapp"
)
FILAS = [
    ["CC", "1001", "Ana Uno", "3001111111", "6012345678", "si", "2026-10-01"],  # móvil + fijo
    ["CC", "1002", "Beto Dos", "3002222222", "3003333333", "SÍ", "2026-09-15"],  # dos móviles
    ["CC", "1003", "Cami Tres", "3004444444", "", "si", ""],  # sin fecha
    ["CC", "1004", "Dani Cuatro", "3005555555", "", "talvez", "2026-10-01"],  # valor inválido
    ["CC", "1005", "Eli Cinco", "3006666666", "", "si", "2999-01-01"],  # fecha futura
    ["CC", "1006", "Fer Seis", "3007777777", "", "", ""],  # sin valor
    ["CC", "1007", "Gus Siete", "3008888888", "", "no", ""],  # revoca
]
URL = "/api/v1/campanas/{}/importaciones"


def csv_bytes(filas=FILAS):
    return (CAB + "\n" + "\n".join(",".join(f) for f in filas) + "\n").encode()


def xlsx_bytes(filas=FILAS):
    wb = Workbook()
    ws = wb.active
    ws.append(CAB.split(","))
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def subir(client, h, nombre, contenido, tipo="cobranza", camp="Camp WA"):
    cid = client.post("/api/v1/campanas", json={"nombre": camp, "tipo": tipo}, headers=h).json()[
        "id"
    ]
    r = client.post(
        URL.format(cid),
        files={"archivo": (nombre, contenido, "application/octet-stream")},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return cid, r.json()


def previa(db, numero, finalidad="cobranza"):
    from datetime import UTC, datetime

    ahora = datetime(2026, 9, 1, tzinfo=UTC)
    db.add(
        AutorizacionCanal(
            numero_e164=numero,
            canal="whatsapp",
            finalidad=finalidad,
            origen="importacion",
            evidencia="x",
            otorgada_en=ahora,
            clave_vigente=f"{numero}|whatsapp|{finalidad}",
            creado_en=ahora,
        )
    )
    db.commit()


def resumen(db):
    db.expire_all()
    return {
        (a.numero_e164, a.finalidad, a.origen, a.clave_vigente is not None, a.motivo_revocacion)
        for a in db.scalars(select(AutorizacionCanal))
    }


ESPERADO = {
    ("+573001111111", "cobranza", "importacion", True, None),
    ("+573002222222", "cobranza", "importacion", True, None),
    ("+573003333333", "cobranza", "importacion", True, None),
    ("+573008888888", "cobranza", "importacion", False, "importacion"),
}


@pytest.mark.parametrize("formato", ["csv", "xlsx"])
def test_autorizaciones_por_movil_advertencias_y_revocacion(client, h_admin, db, formato):
    previa(db, "+573008888888")
    contenido = csv_bytes() if formato == "csv" else xlsx_bytes()
    cid, r = subir(client, h_admin, f"c.{formato}", contenido)
    assert r["filas_importadas"] == 7
    assert resumen(db) == ESPERADO  # el fijo se ignora; el "no" revoca la previa
    avisos = [
        (e["fila"], e["campo"], e["codigo"], e["severidad"])
        for e in r["errores"]
        if "AUTORIZACION" in e["codigo"]
    ]
    assert avisos == [
        (4, "fecha_autorizacion_whatsapp", "AUTORIZACION_WHATSAPP_INVALIDA", "advertencia"),
        (5, "autoriza_whatsapp", "AUTORIZACION_WHATSAPP_INVALIDA", "advertencia"),
        (6, "fecha_autorizacion_whatsapp", "AUTORIZACION_WHATSAPP_INVALIDA", "advertencia"),
    ]
    a = db.scalar(select(AutorizacionCanal).where(AutorizacionCanal.numero_e164 == "+573001111111"))
    assert a.evidencia == f"importacion:{r['id']} fila 2" and a.importacion_id == r["id"]
    assert a.otorgada_en.isoformat() == "2026-10-01T05:00:00+00:00"  # 00:00 hora de Colombia
    aud = db.scalar(select(Auditoria).where(Auditoria.accion == "importacion.autorizaciones"))
    assert aud.detalle == {"importacion_id": r["id"], "creadas": 3, "revocadas": 1, "ignoradas": 3}
    # Las columnas de opt-in no se guardan como datos adicionales del registro.
    for cc in db.scalars(select(CampanaCliente).where(CampanaCliente.campana_id == cid)):
        assert cc.datos_adicionales == {}


def test_la_finalidad_es_el_tipo_de_la_campana(client, h_admin, db):
    subir(
        client,
        h_admin,
        "v.csv",
        csv_bytes([FILAS[0]]).replace(b"cobranza", b"venta"),
        tipo="venta",
        camp="Venta WA",
    )
    assert {x[1] for x in resumen(db)} == {"venta"}


def test_no_duplica_vigentes_y_no_revoca_otra_finalidad(client, h_admin, db):
    previa(db, "+573001111111")  # ya vigente: no se duplica
    previa(db, "+573008888888", finalidad="venta")  # el "no" de cobranza no toca la de venta
    subir(client, h_admin, "c.csv", csv_bytes())
    filas = resumen(db)
    assert ("+573008888888", "venta", "importacion", True, None) in filas
    assert len([x for x in filas if x[0] == "+573001111111"]) == 1


def test_las_filas_no_importadas_no_autorizan(client, h_admin, db):
    duplicada = [FILAS[0], FILAS[0]]
    subir(client, h_admin, "d.csv", csv_bytes(duplicada))
    assert len(resumen(db)) == 1


def test_sin_las_columnas_no_hay_auditoria_de_autorizaciones(client, h_admin, db):
    contenido = b"tipo_documento,numero_documento,nombre,telefono_1\nCC,2001,Zeta,3001111111\n"
    subir(client, h_admin, "s.csv", contenido)
    assert resumen(db) == set()
    assert (
        db.scalar(select(Auditoria).where(Auditoria.accion == "importacion.autorizaciones")) is None
    )
