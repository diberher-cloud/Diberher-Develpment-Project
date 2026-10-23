"""Invariante de conteos de importación y reglas de dedupe/exclusión (§4.6).

total_filas = filas_importadas + filas_duplicadas + filas_invalidas + filas_excluidas
"""

import random
from pathlib import Path

import pytest

from app.modulos.clientes.modelos import CampanaCliente, Cliente
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.modelos import Importacion

FIXTURES = Path(__file__).parent.parent / "fixtures"
CAB = "tipo_documento,numero_documento,nombre,telefono_1,telefono_2\n"


def _campana(client, h, nombre="Campaña inv", tipo="cobranza"):
    return client.post("/api/v1/campanas", json={"nombre": nombre, "tipo": tipo}, headers=h).json()[
        "id"
    ]


def _subir(client, h, cid, contenido, nombre="d.csv"):
    if isinstance(contenido, str):
        contenido = contenido.encode("utf-8")
    return client.post(
        f"/api/v1/campanas/{cid}/importaciones",
        headers=h,
        files={"archivo": (nombre, contenido, "text/csv")},
    )


def _excluir(db, numero, aplica_a, uid):
    db.add(Exclusion(numero_e164=numero, motivo="manual", aplica_a=aplica_a, creado_por=uid))
    db.commit()


def _conteos(imp):
    return (
        imp["filas_importadas"],
        imp["filas_duplicadas"],
        imp["filas_invalidas"],
        imp["filas_excluidas"],
    )


def _invariante(imp):
    assert sum(_conteos(imp)) == imp["total_filas"], imp


def test_invariante_en_el_fixture_de_cobranza_y_en_el_detalle_persistido(
    client, h_admin, admin, db
):
    _excluir(db, "+573005550000", "cobranza", admin.id)
    cid = _campana(client, h_admin)
    imp = _subir(client, h_admin, cid, (FIXTURES / "cobranza_mixta.csv").read_bytes()).json()
    _invariante(imp)
    assert imp["total_filas"] == 7  # la línea vacía no cuenta
    # lo persistido coincide con lo respondido
    det = client.get(f"/api/v1/importaciones/{imp['id']}", headers=h_admin).json()
    assert _conteos(det) == _conteos(imp) and det["total_filas"] == imp["total_filas"]
    lista = client.get(f"/api/v1/campanas/{cid}/importaciones", headers=h_admin).json()["items"][0]
    assert _conteos(lista) == _conteos(imp)
    # filas_importadas == clientes realmente creados en la campaña
    assert (
        client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["total"]
        == imp["filas_importadas"]
    )
    fila = db.query(Importacion).filter_by(id=imp["id"]).one()
    assert fila.total_filas == 7 and db.query(CampanaCliente).count() == imp["filas_importadas"]


def test_cada_fila_cae_en_exactamente_una_categoria(client, h_admin, admin, db):
    """Una fila de cada categoría + combinaciones borde: la suma siempre cuadra."""
    _excluir(db, "+573005550000", "cobranza", admin.id)
    cid = _campana(client, h_admin)
    # preexistente para DUPLICADO_EN_CAMPANA
    _subir(client, h_admin, cid, CAB + "CC,900001,Previo,3001230001,\n")
    filas = [
        "CC,100001,Importada,3001230002,",  # importada
        "CC,100001,Repetida,3001230003,",  # duplicada en archivo
        "CC,900001,Ya en campaña,3001230004,",  # duplicada en campaña
        "CC,100002,Sin tel,,",  # inválida
        "XX,100003,Tipo malo,3001230005,",  # inválida
        "CC,100004,Excluida,3005550000,",  # excluida
        "CC,100005,Parcial,3005550000,3001230006",  # importada (parcial)
        "CC,100001,Otra repetida,3001230007,",  # duplicada en archivo (otra vez)
        "CC,100006,,3001230008,",  # inválida (nombre vacío)
        "CE,100001,Otro tipo doc,3001230009,",  # importada (distinto tipo de documento)
    ]
    imp = _subir(client, h_admin, cid, CAB + "\n".join(filas) + "\n").json()
    _invariante(imp)
    assert imp["total_filas"] == len(filas)
    assert _conteos(imp) == (3, 3, 3, 1)


def test_fila_invalida_no_entra_a_la_deduplicacion(client, h_admin):
    """Decisión del backend: una fila inválida no 'ocupa' la clave; la válida posterior entra."""
    cid = _campana(client, h_admin)
    filas = [
        "CC,100001,,3001230002,",  # inválida (nombre vacío) con el mismo documento
        "CC,100001,Valida,3001230002,",  # válida: debe importarse
        "CC,100001,Repetida,3001230002,",  # esta sí es duplicada de la fila 3
    ]
    imp = _subir(client, h_admin, cid, CAB + "\n".join(filas) + "\n").json()
    _invariante(imp)
    assert _conteos(imp) == (1, 1, 1, 0)
    dup = next(e for e in imp["errores"] if e["codigo"] == "DUPLICADO_EN_ARCHIVO")
    assert dup["fila"] == 4 and "fila 3" in dup["mensaje"]


def test_fila_invalida_con_clave_de_cliente_ya_en_campana_sigue_siendo_invalida(client, h_admin):
    cid = _campana(client, h_admin)
    _subir(client, h_admin, cid, CAB + "CC,100001,Previo,3001230002,\n")
    imp = _subir(client, h_admin, cid, CAB + "CC,100001,Previo,,\n").json()
    _invariante(imp)
    assert _conteos(imp) == (0, 0, 1, 0)


def test_archivo_solo_con_invalidas_no_crea_clientes_pero_si_importacion(client, h_admin, db):
    cid = _campana(client, h_admin)
    imp = _subir(client, h_admin, cid, CAB + "CC,1,A,abc,\nCC,2,B,123,\n").json()
    _invariante(imp)
    assert _conteos(imp) == (0, 0, 2, 0) and imp["estado"] == "completada"
    assert db.query(Cliente).count() == 0 and db.query(Importacion).count() == 1


def test_documento_con_formato_distinto_es_la_misma_clave(client, h_admin):
    cid = _campana(client, h_admin)
    filas = ["CC,1.020.304.050,A B,3001230002,", "CC,1020304050,A B,3001230003,",
             "CC, 1 020 304 050 ,A B,3001230004,"]  # fmt: skip
    imp = _subir(client, h_admin, cid, CAB + "\n".join(filas) + "\n").json()
    _invariante(imp)
    assert _conteos(imp) == (1, 2, 0, 0)


def test_mismo_documento_distinto_tipo_son_clientes_distintos(client, h_admin, db):
    cid = _campana(client, h_admin)
    imp = _subir(
        client, h_admin, cid, CAB + "CC,555555,Uno,3001230002,\nCE,555555,Dos,3001230003,\n"
    ).json()
    assert _conteos(imp) == (2, 0, 0, 0) and db.query(Cliente).count() == 2


def test_telefono_excluido_solo_para_otro_tipo_de_campana_no_excluye(client, h_admin, admin, db):
    _excluir(db, "+573001230002", "venta", admin.id)
    cid = _campana(client, h_admin, "Cobranza x", "cobranza")
    imp = _subir(client, h_admin, cid, CAB + "CC,100001,Ana,3001230002,\n").json()
    assert _conteos(imp) == (1, 0, 0, 0) and imp["errores"] == []


def test_exclusion_todas_aplica_a_ambos_tipos(client, h_admin, admin, db):
    _excluir(db, "+573001230002", "todas", admin.id)
    for tipo in ("venta", "cobranza"):
        cid = _campana(client, h_admin, f"Camp {tipo}", tipo)
        imp = _subir(client, h_admin, cid, CAB + "CC,100001,Ana,3001230002,\n").json()
        assert _conteos(imp) == (0, 0, 0, 1)
        assert imp["errores"][0]["codigo"] == "TODOS_TELEFONOS_EXCLUIDOS"


def test_exclusion_creada_por_api_se_respeta_en_la_importacion(client, h_admin):
    client.post(
        "/api/v1/exclusiones",
        json={"telefono": "300 123 0002", "motivo": "rne"},  # aplica_a por defecto: venta
        headers=h_admin,
    )
    cv = _campana(client, h_admin, "Venta rne", "venta")
    cc = _campana(client, h_admin, "Cobranza rne", "cobranza")
    csv = CAB + "CC,100001,Ana,3001230002,\n"
    assert _conteos(_subir(client, h_admin, cv, csv).json()) == (0, 0, 0, 1)
    assert _conteos(_subir(client, h_admin, cc, csv).json()) == (1, 0, 0, 0)


def test_telefono_excluido_en_primera_fila_y_misma_clave_despues(client, h_admin, admin, db):
    """Una fila excluida ocupa la clave: la repetición posterior cuenta como duplicada."""
    _excluir(db, "+573005550000", "cobranza", admin.id)
    cid = _campana(client, h_admin)
    imp = _subir(
        client, h_admin, cid, CAB + "CC,100001,A B,3005550000,\nCC,100001,A B,3001230002,\n"
    ).json()
    _invariante(imp)
    assert _conteos(imp) == (0, 1, 0, 1)


@pytest.mark.parametrize("semilla", range(8))
def test_invariante_con_archivos_aleatorios(client, h_admin, admin, db, semilla):
    """Mezcla aleatoria (reproducible) de filas buenas, repetidas, inválidas y excluidas."""
    rnd = random.Random(semilla)
    _excluir(db, "+573005550000", "cobranza", admin.id)
    _excluir(db, "+573005550001", "todas", admin.id)
    cid = _campana(client, h_admin)
    _subir(client, h_admin, cid, CAB + "CC,7000,Previo,3001239999,\n")  # ya en campaña

    def fila():
        doc = rnd.choice(["7000", "7001", "7002", "7003", "7004", "7005", "8000", "8001"])
        tipo = rnd.choice(["CC", "CC", "CC", "CE", "XX"])
        nombre = rnd.choice(["Ana Gómez", "Luis Pérez", "", "A"])
        t1 = rnd.choice(["3001230001", "3005550000", "3005550001", "abc", "", "6012345678"])
        t2 = rnd.choice(["", "", "3109998877", "3005550000", "xyz"])
        return f"{tipo},{doc},{nombre},{t1},{t2}"

    n = rnd.randint(1, 60)
    filas = [fila() for _ in range(n)]
    # intercala líneas vacías, que no deben contar
    contenido = CAB + "\n".join(f + ("\n" if rnd.random() < 0.2 else "") for f in filas) + "\n"
    imp = _subir(client, h_admin, cid, contenido).json()
    _invariante(imp)
    assert imp["total_filas"] == n
    # las filas importadas son exactamente las que quedaron en la campaña (más la previa)
    total = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["total"]
    assert total == imp["filas_importadas"] + 1
    # los números de fila de los errores están dentro del archivo
    lineas = contenido.count("\n")
    assert all(1 <= e["fila"] <= lineas for e in imp["errores"])
    # toda fila no importada deja al menos una incidencia
    filas_con_incidencia = {e["fila"] for e in imp["errores"]}
    assert len(filas_con_incidencia) >= n - imp["filas_importadas"]


def test_numero_de_fila_es_la_linea_fisica_con_lineas_vacias_y_crlf(client, h_admin):
    cid = _campana(client, h_admin)
    contenido = (
        "tipo_documento,numero_documento,nombre,telefono_1\r\n"
        "CC,100001,Ana Uno,3001230002\r\n"
        "\r\n"
        "CC,100002,Bea Dos,abc\r\n"
        "\r\n"
        "CC,100001,Ana Dup,3001230003\r\n"
    )
    imp = _subir(client, h_admin, cid, contenido).json()
    _invariante(imp)
    filas = {(e["fila"], e["codigo"]) for e in imp["errores"]}
    assert (4, "TELEFONO_INVALIDO") in filas and (4, "SIN_TELEFONO_VALIDO") in filas
    assert (6, "DUPLICADO_EN_ARCHIVO") in filas
    dup = next(e for e in imp["errores"] if e["codigo"] == "DUPLICADO_EN_ARCHIVO")
    assert "fila 2" in dup["mensaje"]


def test_punto_y_coma_cp1252_end_to_end(client, h_admin):
    cid = _campana(client, h_admin)
    contenido = (
        "Tipo Documento;Número Documento;Nombre;Teléfono 1\n"
        "CC;1.020.304.050;José Ángel Peña;300 123 4567\n"
    ).encode("cp1252")
    imp = _subir(client, h_admin, cid, contenido).json()
    assert _conteos(imp) == (1, 0, 0, 0)
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert item["cliente"]["nombre"] == "José Ángel Peña"


def test_utf8_bom_end_to_end(client, h_admin):
    cid = _campana(client, h_admin)
    contenido = (
        "tipo_documento,numero_documento,nombre,telefono_1\nCC,100001,Ñandú Ruiz,3001230002\n"
    )
    imp = _subir(client, h_admin, cid, contenido.encode("utf-8-sig")).json()
    assert _conteos(imp) == (1, 0, 0, 0)


def test_email_invalido_es_advertencia_y_la_fila_se_importa(client, h_admin):
    cid = _campana(client, h_admin)
    csv = CAB.rstrip() + ",email\nCC,100001,Ana Uno,3001230002,,no-es-email\n"
    imp = _subir(client, h_admin, cid, csv).json()
    assert _conteos(imp) == (1, 0, 0, 0)
    assert [(e["codigo"], e["severidad"]) for e in imp["errores"]] == [
        ("EMAIL_INVALIDO", "advertencia")
    ]
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert item["cliente"]["email"] is None


def test_telefono_2_invalido_es_advertencia_y_se_ignora(client, h_admin):
    cid = _campana(client, h_admin)
    imp = _subir(client, h_admin, cid, CAB + "CC,100001,Ana Uno,3001230002,12345\n").json()
    assert _conteos(imp) == (1, 0, 0, 0)
    assert [(e["campo"], e["severidad"]) for e in imp["errores"]] == [("telefono_2", "advertencia")]
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert len(item["telefonos"]) == 1


def test_mismo_telefono_en_dos_columnas_se_guarda_una_vez(client, h_admin):
    cid = _campana(client, h_admin)
    imp = _subir(client, h_admin, cid, CAB + "CC,100001,Ana Uno,3001230002,300 123 0002\n").json()
    assert _conteos(imp) == (1, 0, 0, 0)
    item = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"][0]
    assert [t["numero_e164"] for t in item["telefonos"]] == ["+573001230002"]


@pytest.mark.parametrize(
    ("campos", "codigo"),
    [
        ("saldo_total=1,234.56", "MONTO_INVALIDO"),
        ("saldo_mora=-5", "MONTO_INVALIDO"),
        ("saldo_total=abc", "MONTO_INVALIDO"),
        ("dias_mora=-1", "ENTERO_INVALIDO"),
        ("dias_mora=4.5", "ENTERO_INVALIDO"),
        ("fecha_vencimiento=31/02/2026", "FECHA_INVALIDA"),
        ("fecha_vencimiento=2026-13-01", "FECHA_INVALIDA"),
    ],
)
def test_campos_de_cobranza_invalidos_invalidan_la_fila(client, h_admin, campos, codigo):
    cid = _campana(client, h_admin)
    col, val = campos.split("=")
    imp = _subir(
        client, h_admin, cid, CAB.rstrip() + f',{col}\nCC,100001,Ana Uno,3001230002,,"{val}"\n'
    ).json()
    _invariante(imp)
    assert _conteos(imp) == (0, 0, 1, 0)
    assert codigo in {e["codigo"] for e in imp["errores"] if e["severidad"] == "error"}


def test_montos_validos_se_guardan_con_dos_decimales(client, h_admin):
    cid = _campana(client, h_admin)
    csv = (
        CAB.rstrip() + ",saldo_total,saldo_mora,dias_mora,fecha_vencimiento\n"
        'CC,100001,Ana Uno,3001230002,,"1.234.567,89",$ 1.500.000,0,15/09/2026\n'
        'CC,100002,Bea Dos,3001230003,,1500.5,"1500,5",7,2026-09-15\n'
    )
    imp = _subir(client, h_admin, cid, csv).json()
    assert _conteos(imp) == (2, 0, 0, 0), imp["errores"]
    items = client.get(f"/api/v1/campanas/{cid}/clientes", headers=h_admin).json()["items"]
    assert (items[0]["saldo_total"], items[0]["saldo_mora"]) == ("1234567.89", "1500000.00")
    assert (items[1]["saldo_total"], items[1]["saldo_mora"]) == ("1500.50", "1500.50")
    assert items[0]["dias_mora"] == 0 and items[0]["fecha_vencimiento"] == "2026-09-15"


def test_cobranza_a_venta_y_viceversa_van_a_datos_adicionales(client, h_admin):
    cv = _campana(client, h_admin, "Venta cols", "venta")
    cc = _campana(client, h_admin, "Cobranza cols", "cobranza")
    base = CAB.rstrip()
    imp_v = _subir(
        client, h_admin, cv,
        base + ",numero_obligacion,saldo_mora,dias_mora\nCC,100001,Ana Uno,3001230002,,OB-1,50,9\n",
    ).json()  # fmt: skip
    imp_c = _subir(
        client, h_admin, cc, base + ",producto,oferta\nCC,100001,Ana Uno,3001230002,,Plan,2x1\n"
    ).json()
    assert _conteos(imp_v) == (1, 0, 0, 0) and _conteos(imp_c) == (1, 0, 0, 0)
    v = client.get(f"/api/v1/campanas/{cv}/clientes", headers=h_admin).json()["items"][0]
    assert v["numero_obligacion"] is None and v["saldo_mora"] is None and v["dias_mora"] is None
    assert v["datos_adicionales"] == {
        "numero_obligacion": "OB-1",
        "saldo_mora": "50",
        "dias_mora": "9",
    }
    c = client.get(f"/api/v1/campanas/{cc}/clientes", headers=h_admin).json()["items"][0]
    assert c["producto"] is None and c["oferta"] is None
    assert c["datos_adicionales"] == {"producto": "Plan", "oferta": "2x1"}


def test_importacion_a_campana_inexistente_o_sin_archivo_no_deja_rastro(client, h_admin, db):
    assert _subir(client, h_admin, 424242, CAB + "CC,1,A,3001230002,\n").status_code == 404
    assert db.query(Importacion).count() == 0 and db.query(Cliente).count() == 0


def test_extension_csv_en_mayusculas_y_otras_extensiones(client, h_admin):
    cid = _campana(client, h_admin)
    ok = _subir(client, h_admin, cid, CAB + "CC,100001,Ana Uno,3001230002,\n", "DATOS.CSV")
    assert ok.status_code == 201
    for nombre in ("datos.xls", "datos.csv.txt", "datos", "datos.csvx"):
        r = _subir(client, h_admin, cid, CAB + "CC,100002,Ana Uno,3001230003,\n", nombre)
        assert r.status_code == 422 and r.json()["error"]["codigo"] == "FORMATO_ARCHIVO_INVALIDO", (
            nombre
        )


def test_limite_exacto_de_tamano_y_de_filas(client, h_admin, monkeypatch):
    from app.config import get_settings

    cid = _campana(client, h_admin)
    contenido = (CAB + "CC,100001,Ana Uno,3001230002,\n").encode()
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", len(contenido))
    assert _subir(client, h_admin, cid, contenido).status_code == 201  # == límite: pasa
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", len(contenido) - 1)
    r = _subir(client, h_admin, cid, contenido.replace(b"100001", b"100002"))
    assert r.status_code == 413
    monkeypatch.setattr(get_settings(), "importacion_max_bytes", 10_000)
    monkeypatch.setattr(get_settings(), "importacion_max_filas", 3)
    tres = CAB + "".join(f"CC,20000{i},Ana Uno,300123000{i},\n" for i in range(3))
    assert _subir(client, h_admin, cid, tres).status_code == 201  # 3 filas == límite
    cuatro = CAB + "".join(f"CC,30000{i},Ana Uno,300124000{i},\n" for i in range(4))
    assert _subir(client, h_admin, cid, cuatro).json()["error"]["codigo"] == "DEMASIADAS_FILAS"
