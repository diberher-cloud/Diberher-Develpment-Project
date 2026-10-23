import pytest

from app.modulos.importacion.lector_csv import ErrorLector, leer_csv

REQ = ("tipo_documento", "numero_documento", "nombre", "telefono_1")
CABECERA = "tipo_documento,numero_documento,nombre,telefono_1"


def _csv(texto: str, codec: str = "utf-8") -> bytes:
    return texto.encode(codec)


@pytest.mark.parametrize("codec", ["utf-8", "utf-8-sig", "cp1252"])
def test_codificaciones(codec):
    datos = _csv(f"{CABECERA}\nCC,123456,José Peña,3001234567\n", codec)
    archivo = leer_csv(datos, 100, REQ)
    assert archivo.filas[0].valores["nombre"] == "José Peña"


def test_delimitadores_y_cabeceras_con_tildes():
    datos = _csv("Tipo Documento;Número Documento;Nombre;Teléfono 1\nCC;123456;Ana;3001234567\n")
    archivo = leer_csv(datos, 100, REQ)
    assert archivo.cabeceras == ["tipo_documento", "numero_documento", "nombre", "telefono_1"]
    assert archivo.filas[0].valores["telefono_1"] == "3001234567"


def test_empate_usa_coma():
    archivo = leer_csv(_csv("a;b,c\n1;2,3\n"), 10)
    assert archivo.cabeceras == ["a;b", "c"]


def test_lineas_vacias_y_numeracion():
    datos = _csv(f"{CABECERA}\n\nCC,111111,A B,3001234567\n,,,\n\nCC,222222,C D,3001234568\n")
    archivo = leer_csv(datos, 100, REQ)
    assert [f.numero for f in archivo.filas] == [3, 6]


def test_campo_con_salto_de_linea_numeracion():
    datos = _csv(f'{CABECERA}\nCC,111111,"A\nB",3001234567\nCC,222222,C D,3001234568\n')
    assert [f.numero for f in leer_csv(datos, 100, REQ).filas] == [2, 4]


def test_columnas_faltantes():
    with pytest.raises(ErrorLector) as exc:
        leer_csv(_csv("tipo_documento,nombre\nCC,A\n"), 10, REQ)
    assert exc.value.codigo == "COLUMNAS_FALTANTES"
    assert {"campo": "telefono_1", "mensaje": "Columna obligatoria ausente."} in exc.value.detalles


@pytest.mark.parametrize("texto", ["", f"{CABECERA}\n", f"{CABECERA}\n\n,,,\n"])
def test_vacio(texto):
    with pytest.raises(ErrorLector) as exc:
        leer_csv(_csv(texto), 10, REQ)
    assert exc.value.codigo == "ARCHIVO_VACIO"


def test_demasiadas_filas():
    filas = "\n".join(f"CC,{1000 + i},N{i},3001234567" for i in range(4))
    with pytest.raises(ErrorLector) as exc:
        leer_csv(_csv(f"{CABECERA}\n{filas}\n"), 3, REQ)
    assert exc.value.codigo == "DEMASIADAS_FILAS"
    assert len(leer_csv(_csv(f"{CABECERA}\n{filas}\n"), 4, REQ).filas) == 4
