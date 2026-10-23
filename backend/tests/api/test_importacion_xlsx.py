import io

import pytest
from openpyxl import Workbook

from app.config import get_settings
from app.modulos.clientes.modelos import Cliente
from app.modulos.exclusiones.modelos import Exclusion

CAB_COB = [
    "Tipo Documento", "Número Documento", "Nombre", "Teléfono 1", "Teléfono 2", "Email", "Ciudad",
    "Número Obligación", "Saldo Total", "Saldo Mora", "Días Mora", "Fecha Vencimiento", "Segmento",
]  # fmt: skip


def xlsx(filas, nombre="datos.xlsx", hojas_extra=None) -> tuple[str, bytes]:
    wb = Workbook()
    ws = wb.active
    for fila in filas:
        ws.append(fila)
    for extra in hojas_extra or []:
        w2 = wb.create_sheet()
        for fila in extra:
            w2.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return nombre, buf.getvalue()


def nueva_campana(client, h, tipo="cobranza", nombre="Cartera"):
    return client.post("/api/v1/campanas", json={"nombre": nombre, "tipo": tipo}, headers=h).json()[
        "id"
    ]


def subir(client, h, cid, nombre, contenido):
    return client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        files={"archivo": (nombre, contenido, "application/octet-stream")},
        headers=h,
    )


def contadores(r):
    j = r.json()
    return {
        k: j[k]
        for k in (
            "total_filas",
            "filas_importadas",
            "filas_duplicadas",
            "filas_invalidas",
            "filas_excluidas",
        )
    }


def test_x1_mismo_resultado_que_el_csv_de_fase_1(client, h_admin, db):
    import csv
    from pathlib import Path

    ruta = Path(__file__).parent.parent / "fixtures" / "cobranza_mixta.csv"
    texto = ruta.read_text(encoding="utf-8")
    filas = list(csv.reader(io.StringIO(texto), delimiter=";"))
    c_csv = nueva_campana(client, h_admin, nombre="Por CSV")
    r_csv = subir(client, h_admin, c_csv, "cobranza_mixta.csv", ruta.read_bytes())
    # Se borran los clientes para que el segundo import no los vea como existentes en otra campaña.
    c_xlsx = nueva_campana(client, h_admin, nombre="Por XLSX")
    nombre, datos = xlsx(filas, "cobranza_mixta.xlsx")
    r_xlsx = subir(client, h_admin, c_xlsx, nombre, datos)
    assert r_csv.status_code == r_xlsx.status_code == 201, r_xlsx.text
    assert contadores(r_csv) == contadores(r_xlsx)

    def forma(r):
        return sorted(
            (e["fila"], e["campo"] or "", e["codigo"], e["severidad"]) for e in r.json()["errores"]
        )

    assert forma(r_csv) == forma(r_xlsx)


def test_x2_telefono_numerico_int_y_float(client, h_admin, db):
    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1", "telefono_2"]
    nombre, datos = xlsx(
        [
            cab,
            ["CC", 1000001, "Ana Uno", 3001234567, 3109876543.0],
            ["CC", "1000002", "Beto Dos", "3001230002", None],
        ]
    )
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.status_code == 201, r.text
    assert r.json()["filas_importadas"] == 2 and r.json()["filas_invalidas"] == 0
    assert (
        db.query(Cliente).filter_by(numero_documento="1000001").one().telefonos[0].numero_e164
        == "+573001234567"
    )


def test_x3_fecha_como_datetime(client, h_admin, db):
    from datetime import datetime

    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1", "fecha_vencimiento"]
    nombre, datos = xlsx([cab, ["CC", "1000003", "Ana Tres", "3001230003", datetime(2026, 9, 15)]])
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.json()["filas_importadas"] == 1
    items = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"]
    assert items[0]["fecha_vencimiento"] == "2026-09-15"


def test_x4_filas_vacias_intermedias_conservan_numeracion(client, h_admin):
    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    nombre, datos = xlsx(
        [
            cab,
            ["CC", "1000004", "Ana Cuatro", "3001230004"],
            [None] * 4,
            [],
            ["CC", "1000005", "X", "abc"],
        ]
    )
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.json()["total_filas"] == 2
    assert {e["fila"] for e in r.json()["errores"] if e["severidad"] == "error"} == {5}


def test_x5_segunda_hoja_se_ignora(client, h_admin):
    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    nombre, datos = xlsx(
        [cab, ["CC", "1000006", "Ana Seis", "3001230006"]],
        hojas_extra=[[cab, ["CC", "1000007", "Otra Hoja", "3001230007"]]],
    )
    assert subir(client, h_admin, cid, nombre, datos).json()["filas_importadas"] == 1


def test_x6_xls_y_xlsm_se_rechazan(client, h_admin):
    cid = nueva_campana(client, h_admin)
    _, datos = xlsx([["a"], ["b"]])
    for nombre in ("datos.xls", "datos.xlsm", "datos.ods"):
        r = subir(client, h_admin, cid, nombre, datos)
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "FORMATO_ARCHIVO_INVALIDO"
        assert r.json()["error"]["mensaje"] == "El archivo debe ser .csv o .xlsx."


def test_x7_bytes_aleatorios_con_extension_xlsx(client, h_admin):
    cid = nueva_campana(client, h_admin)
    r = subir(client, h_admin, cid, "datos.xlsx", b"\x00\x01esto no es un excel" * 50)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "ARCHIVO_INVALIDO"


def test_x8_zip_descomprimido_excede_el_limite(client, h_admin, monkeypatch):
    cid = nueva_campana(client, h_admin)
    monkeypatch.setattr(get_settings(), "importacion_max_bytes_descomprimido", 1000)
    nombre, datos = xlsx(
        [["tipo_documento", "numero_documento", "nombre", "telefono_1"]]
        + [["CC", str(i), "N" * 40, "3001230000"] for i in range(200)]
    )
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "ARCHIVO_INVALIDO"


def test_extension_en_mayusculas(client, h_admin):
    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    nombre, datos = xlsx([cab, ["CC", "1000008", "Ana Ocho", "3001230008"]], "DATOS.XLSX")
    assert subir(client, h_admin, cid, nombre, datos).status_code == 201


def test_columnas_faltantes_y_archivo_vacio(client, h_admin):
    cid = nueva_campana(client, h_admin)
    nombre, datos = xlsx([["tipo_documento", "nombre"], ["CC", "A"]])
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "COLUMNAS_FALTANTES"
    nombre, datos = xlsx([["tipo_documento", "numero_documento", "nombre", "telefono_1"]])
    assert subir(client, h_admin, cid, nombre, datos).json()["error"]["codigo"] == "ARCHIVO_VACIO"


def test_limite_de_filas(client, h_admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "importacion_max_filas", 1)
    cid = nueva_campana(client, h_admin)
    cab = ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    nombre, datos = xlsx(
        [cab, ["CC", "1", "Ana Uno", "3001230001"], ["CC", "2", "Beto Dos", "3001230002"]]
    )
    r = subir(client, h_admin, cid, nombre, datos)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "DEMASIADAS_FILAS"


# ---- Exclusiones -----------------------------------------------------------------------------
def importar_exclusiones(client, h, nombre, datos, **form):
    return client.post(
        "/api/v1/exclusiones/importar",
        files={"archivo": (nombre, datos, "application/octet-stream")},
        data={"motivo": "rne", **form},
        headers=h,
    )


def test_exclusiones_desde_xlsx(client, h_admin, db):
    nombre, datos = xlsx(
        [["Teléfono"], [3001234567], ["3109876543"], ["+57 601 234 5678"], ["abc"], [3001234567.0]]
    )
    r = importar_exclusiones(client, h_admin, nombre, datos)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["total_filas"], j["creadas"], j["duplicadas"], j["invalidas"]) == (5, 3, 1, 1)
    assert db.query(Exclusion).count() == 3
    assert j["errores"][0]["fila"] == 5


def test_exclusiones_xlsx_igual_que_csv(client, h_admin, db):
    csv_ = "telefono\n3001234567\n3109876543\nabc\n"
    r1 = importar_exclusiones(
        client, h_admin, "e.csv", csv_.encode(), motivo="rne", aplica_a="venta"
    )
    nombre, datos = xlsx([["telefono"], ["3001234567"], ["3109876543"], ["abc"]])
    r2 = importar_exclusiones(client, h_admin, nombre, datos, motivo="rne", aplica_a="cobranza")
    for k in ("total_filas", "creadas", "duplicadas", "invalidas"):
        assert r1.json()[k] == r2.json()[k]


def test_exclusiones_xlsx_invalido(client, h_admin):
    r = importar_exclusiones(client, h_admin, "e.xlsx", b"nada")
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "ARCHIVO_INVALIDO"
    r = importar_exclusiones(client, h_admin, "e.xls", b"nada")
    assert r.json()["error"]["codigo"] == "FORMATO_ARCHIVO_INVALIDO"


@pytest.mark.parametrize("rol", ["agente"])
def test_agente_no_importa(client, crear_usuario, cabeceras, rol):
    h = cabeceras(crear_usuario(rol))
    nombre, datos = xlsx([["telefono"], ["3001234567"]])
    assert importar_exclusiones(client, h, nombre, datos).status_code == 403
