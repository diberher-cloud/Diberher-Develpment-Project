"""Archivos .xlsx hostiles: XXE, bomba de entidades, bomba zip, hoja dispersa y fórmulas."""

import io
import time
import zipfile

import pytest
from openpyxl import Workbook

from app.modulos.importacion.lector_csv import ErrorLector
from app.modulos.importacion.lector_xlsx import leer_xlsx


def _base(filas) -> bytes:
    wb = Workbook()
    ws = wb.active
    for f in filas:
        ws.append(f)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _reemplazar(datos: bytes, nombre: str, contenido: bytes | str) -> bytes:
    """Devuelve una copia del xlsx con `nombre` sustituido."""
    origen = zipfile.ZipFile(io.BytesIO(datos))
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for info in origen.infolist():
            z.writestr(info.filename, contenido if info.filename == nombre else origen.read(info))
    return salida.getvalue()


HOJA_CON = (
    '<?xml version="1.0" encoding="UTF-8"?>{doctype}'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>telefono</t></is></c></row>'
    '<row r="2"><c r="A2" t="inlineStr"><is><t>{valor}</t></is></c></row></sheetData></worksheet>'
)


def test_xxe_entidad_externa_no_se_expande_ni_lee_archivos():
    doctype = '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    datos = _reemplazar(
        _base([["telefono"], ["1"]]),
        "xl/worksheets/sheet1.xml",
        HOJA_CON.format(doctype=doctype, valor="&xxe;"),
    )
    try:
        a = leer_xlsx(datos, 10, ("telefono",))
    except ErrorLector as exc:
        assert exc.codigo == "ARCHIVO_INVALIDO"
        return
    # Si lo acepta, el contenido de /etc/passwd jamás puede aparecer en los datos.
    assert all("root:" not in v for f in a.filas for v in f.valores.values())


def test_bomba_de_entidades_se_rechaza_rapido():
    entidades = "".join(
        f'<!ENTITY l{i} "{f"&l{i - 1};" * 10}">' if i else '<!ENTITY l0 "lol">' for i in range(0, 9)
    )
    doctype = f"<!DOCTYPE x [{entidades}]>"
    datos = _reemplazar(
        _base([["telefono"], ["1"]]),
        "xl/worksheets/sheet1.xml",
        HOJA_CON.format(doctype=doctype, valor="&l8;"),
    )
    t0 = time.monotonic()
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(datos, 10, ("telefono",))
    assert e.value.codigo == "ARCHIVO_INVALIDO"
    assert time.monotonic() - t0 < 5


def test_bomba_zip_con_tamano_declarado_verdadero_se_rechaza_sin_descomprimir():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/relleno.bin", b"\0" * (50 * 1024 * 1024))
    assert len(buf.getvalue()) < 100_000  # ~50 MiB comprimidos en <100 KB
    t0 = time.monotonic()
    with pytest.raises(ErrorLector) as e:
        leer_xlsx(buf.getvalue(), 10, max_descomprimido=10 * 1024 * 1024)
    assert e.value.codigo == "ARCHIVO_INVALIDO"
    assert time.monotonic() - t0 < 3


def test_hoja_dispersa_con_celda_lejana_no_agota_cpu():
    """Una celda en la fila 1.048.576 no debe provocar minutos de proceso."""
    hoja = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<dimension ref="A1:XFD1048576"/><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>telefono</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>3001234567</t></is></c></row>'
        '<row r="1048576"><c r="XFD1048576" t="inlineStr"><is><t>x</t></is></c></row>'
        "</sheetData></worksheet>"
    )
    datos = _reemplazar(_base([["telefono"], ["1"]]), "xl/worksheets/sheet1.xml", hoja)
    t0 = time.monotonic()
    try:
        leer_xlsx(datos, 10, ("telefono",))
    except ErrorLector:
        pass
    assert time.monotonic() - t0 < 10, "hoja dispersa: lectura demasiado lenta (DoS)"


def test_formulas_y_texto_con_prefijo_peligroso_no_se_evaluan():
    wb = Workbook()
    ws = wb.active
    ws.append(["nombre", "telefono"])
    ws.append(['=HYPERLINK("http://evil","x")', "3001234567"])
    ws.append(["=cmd|' /C calc'!A0", "3001234568"])
    ws.append(["@SUM(1+1)", "3001234569"])
    b = io.BytesIO()
    wb.save(b)
    a = leer_xlsx(b.getvalue(), 10, ("telefono",))
    # Con data_only y sin valor calculado guardado, la fórmula se lee vacía (nunca ejecutada).
    assert a.filas[0].valores["nombre"] in ("", '=HYPERLINK("http://evil","x")')
    assert a.filas[1].valores["nombre"] in ("", "=cmd|' /C calc'!A0")  # texto inerte
    assert a.filas[2].valores["nombre"] == "@SUM(1+1)"


def test_formula_con_valor_cacheado_se_lee_como_valor():
    hoja = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>telefono</t></is></c></row>'
        '<row r="2"><c r="A2"><f>1+1</f><v>3001234567</v></c></row>'
        "</sheetData></worksheet>"
    )
    datos = _reemplazar(_base([["telefono"], ["1"]]), "xl/worksheets/sheet1.xml", hoja)
    assert leer_xlsx(datos, 10, ("telefono",)).filas[0].valores["telefono"] == "3001234567"


def test_xlsx_con_macros_o_contenido_ejecutable_se_lee_solo_como_datos():
    datos = _base([["telefono"], ["3001234567"]])
    buf = io.BytesIO(datos)
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("xl/vbaProject.bin", b"MZ\x90\x00malware")
    a = leer_xlsx(buf.getvalue(), 10, ("telefono",))
    assert a.filas[0].valores["telefono"] == "3001234567"
