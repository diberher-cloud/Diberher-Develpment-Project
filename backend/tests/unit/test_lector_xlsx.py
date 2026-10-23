import io
import zipfile
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from app.modulos.importacion.lector_csv import ErrorLector
from app.modulos.importacion.lector_xlsx import celda_a_texto, leer_xlsx


def libro(filas, segunda_hoja=None) -> bytes:
    wb = Workbook()
    ws = wb.active
    for fila in filas:
        ws.append(fila)
    if segunda_hoja:
        ws2 = wb.create_sheet("otra")
        for fila in segunda_hoja:
            ws2.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_conversion_de_celdas():
    assert celda_a_texto(None) == ""
    assert celda_a_texto("  hola ") == "hola"
    assert celda_a_texto(True) == "true" and celda_a_texto(False) == "false"
    assert celda_a_texto(3001234567) == "3001234567"
    assert celda_a_texto(3001234567.0) == "3001234567"
    assert celda_a_texto(12.5) == "12.5"
    assert celda_a_texto(datetime(2026, 9, 15)) == "2026-09-15"
    assert celda_a_texto(date(2026, 9, 15)) == "2026-09-15"
    assert celda_a_texto(datetime(2026, 9, 15, 10, 30)) == "2026-09-15T10:30:00"
    assert celda_a_texto(float("nan")) == "nan"


def test_lee_cabeceras_normalizadas_y_filas():
    datos = libro(
        [
            ["Tipo Documento", "Número Documento", "Nombre", None, "Teléfono 1"],
            ["CC", 1020304050, "María", "ignorada", 3001234567.0],
            [None, None, None, None, None],
            ["CE", "99", "Juan", None, "3109876543"],
        ]
    )
    a = leer_xlsx(datos, 100, ("tipo_documento", "telefono_1"))
    assert a.cabeceras == ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    assert [f.numero for f in a.filas] == [2, 4]  # la fila vacía se ignora y conserva la numeración
    assert a.filas[0].valores == {
        "tipo_documento": "CC",
        "numero_documento": "1020304050",
        "nombre": "María",
        "telefono_1": "3001234567",
    }


def test_solo_primera_hoja():
    datos = libro([["telefono"], ["3001234567"]], segunda_hoja=[["telefono"], ["1"], ["2"]])
    assert len(leer_xlsx(datos, 100, ("telefono",)).filas) == 1


def test_errores_de_archivo():
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(b"esto no es un excel", 10)
    assert e.value.codigo == "ARCHIVO_INVALIDO"
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(libro([["a"]]), 10)
    assert e.value.codigo == "ARCHIVO_VACIO"
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(libro([["a"], ["1"], ["2"]]), 1)
    assert e.value.codigo == "DEMASIADAS_FILAS"
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(libro([["a"], ["1"]]), 10, ("telefono",))
    assert e.value.codigo == "COLUMNAS_FALTANTES"
    assert e.value.detalles == [{"campo": "telefono", "mensaje": "Columna obligatoria ausente."}]


def test_zip_valido_pero_no_xlsx():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hola.txt", "hola")
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(buf.getvalue(), 10)
    assert e.value.codigo == "ARCHIVO_INVALIDO"


def test_limite_descomprimido():
    datos = libro([["a"], ["1"]])
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(datos, 10, max_descomprimido=100)
    assert e.value.codigo == "ARCHIVO_INVALIDO"
    assert leer_xlsx(datos, 10, max_descomprimido=10_000_000).filas
