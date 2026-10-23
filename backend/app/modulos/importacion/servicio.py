"""Importación síncrona de clientes desde CSV (§4.6). Una sola transacción."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errores import ErrorApp
from app.modulos.auditoria import servicio as auditoria
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion import normalizacion as nz
from app.modulos.importacion.esquemas import ImportacionDetalleSalida
from app.modulos.importacion.lector_csv import ArchivoCsv, ErrorLector, leer_csv
from app.modulos.importacion.lector_xlsx import leer_xlsx
from app.modulos.importacion.modelos import Importacion, ImportacionError
from app.modulos.importacion.telefonos import (
    ErrorTelefono,
    TelefonoNormalizado,
    enmascarar,
    normalizar_telefono,
)
from app.modulos.usuarios.modelos import Usuario

REQUERIDAS = ("tipo_documento", "numero_documento", "nombre", "telefono_1")
COLUMNAS_BASE = (
    "tipo_documento", "numero_documento", "nombre",
    "telefono_1", "telefono_2", "telefono_3", "email", "ciudad",
)  # fmt: skip
COLUMNAS_TIPO = {
    "cobranza": (
        "numero_obligacion", "saldo_total", "saldo_mora", "dias_mora", "fecha_vencimiento",
    ),
    "venta": ("producto", "oferta"),
}  # fmt: skip
MAX_CLAVES_ADICIONALES = 20
MAX_VALOR_ADICIONAL = 500
MAX_LONGITUD_CLAVE = 50
MAX_ERRORES_RESPUESTA = 100
_LOTE = 500


@dataclass
class Incidencia:
    fila: int
    campo: str | None
    codigo: str
    mensaje: str
    severidad: str  # "error" | "advertencia"


@dataclass
class FilaValida:
    tipo_documento: str
    numero_documento: str
    nombre: str
    email: str | None
    ciudad: str | None
    telefonos: list[tuple[int, TelefonoNormalizado]]  # (prioridad, teléfono)
    numero_obligacion: str | None = None
    saldo_total: Decimal | None = None
    saldo_mora: Decimal | None = None
    dias_mora: int | None = None
    fecha_vencimiento: date | None = None
    producto: str | None = None
    oferta: str | None = None
    datos_adicionales: dict[str, str] = field(default_factory=dict)


@dataclass
class ResultadoFila:
    fila: int
    datos: FilaValida | None
    incidencias: list[Incidencia]


_ROTULOS_TELEFONO = {
    "TELEFONO_INVALIDO": "Teléfono inválido",
    "TELEFONO_NO_COLOMBIANO": "Teléfono no colombiano",
    "TELEFONO_TIPO_NO_PERMITIDO": "Tipo de línea de teléfono no permitido",
}


def columnas_propias(tipo_campana: str) -> tuple[str, ...]:
    return COLUMNAS_BASE + COLUMNAS_TIPO[tipo_campana]


def validar_fila(
    numero: int, valores: dict[str, str], tipo_campana: str, extras: list[str]
) -> ResultadoFila:
    """Validación pura de una fila. No consulta la BD."""
    inc: list[Incidencia] = []

    def error(campo: str | None, codigo: str, mensaje: str) -> None:
        inc.append(Incidencia(numero, campo, codigo, mensaje, "error"))

    def adv(campo: str | None, codigo: str, mensaje: str) -> None:
        inc.append(Incidencia(numero, campo, codigo, mensaje, "advertencia"))

    def texto_opcional(campo: str, maximo: int) -> str | None:
        valor = nz.limpiar_texto(valores.get(campo))
        if not valor:
            return None
        if len(valor) > maximo:
            error(campo, "VALOR_INVALIDO", f"'{campo}' supera {maximo} caracteres.")
            return None
        return valor

    # Documento
    tipo_doc: str | None = None
    num_doc: str | None = None
    try:
        tipo_doc = nz.normalizar_tipo_documento(valores.get("tipo_documento"))
        num_doc = nz.normalizar_documento(tipo_doc, valores.get("numero_documento"))
    except nz.ErrorValor as exc:
        campo = "tipo_documento" if exc.codigo == "TIPO_DOCUMENTO_INVALIDO" else "numero_documento"
        error(campo, exc.codigo, exc.mensaje)

    # Nombre
    nombre = nz.limpiar_texto(valores.get("nombre"))
    if not nombre:
        error("nombre", "CAMPO_REQUERIDO", "El nombre es obligatorio.")
    elif not 2 <= len(nombre) <= 200:
        error("nombre", "VALOR_INVALIDO", "El nombre debe tener entre 2 y 200 caracteres.")

    # Teléfonos
    validos: list[tuple[int, TelefonoNormalizado]] = []
    problemas: list[tuple[str, str, str]] = []
    vistos_tel: set[str] = set()
    for pos in (1, 2, 3):
        campo = f"telefono_{pos}"
        crudo = valores.get(campo, "")
        if pos > 1 and not crudo.strip():
            continue
        try:
            tel = normalizar_telefono(crudo)
        except ErrorTelefono as exc:
            if exc.codigo == "TELEFONO_REQUERIDO":
                problemas.append((campo, exc.codigo, "El teléfono es obligatorio."))
            else:
                rotulo = _ROTULOS_TELEFONO[exc.codigo]
                problemas.append((campo, exc.codigo, f"{rotulo} ({enmascarar(crudo)})."))
            continue
        if tel.numero_e164 not in vistos_tel:
            vistos_tel.add(tel.numero_e164)
            validos.append((pos, tel))
    hay_telefono = bool(validos)
    for campo, codigo, mensaje in problemas:
        (adv if hay_telefono else error)(campo, codigo, mensaje)
    if not hay_telefono:
        error(None, "SIN_TELEFONO_VALIDO", "La fila no tiene ningún teléfono válido.")

    # Email
    email: str | None = None
    if valores.get("email", "").strip():
        try:
            email = nz.validar_email(valores["email"])
        except nz.ErrorValor:
            adv("email", "EMAIL_INVALIDO", "Email inválido; se ignora.")

    ciudad = texto_opcional("ciudad", 100)

    datos = FilaValida(
        tipo_documento=tipo_doc or "",
        numero_documento=num_doc or "",
        nombre=nombre,
        email=email,
        ciudad=ciudad,
        telefonos=validos,
    )

    if tipo_campana == "cobranza":
        datos.numero_obligacion = texto_opcional("numero_obligacion", 50)
        for campo in ("saldo_total", "saldo_mora"):
            if valores.get(campo, "").strip():
                try:
                    setattr(datos, campo, nz.parsear_monto(valores[campo]))
                except nz.ErrorValor as exc:
                    error(campo, exc.codigo, f"Monto inválido en '{campo}'.")
        if valores.get("dias_mora", "").strip():
            try:
                datos.dias_mora = nz.parsear_entero_no_negativo(valores["dias_mora"])
            except nz.ErrorValor as exc:
                error("dias_mora", exc.codigo, exc.mensaje)
        if valores.get("fecha_vencimiento", "").strip():
            try:
                datos.fecha_vencimiento = nz.parsear_fecha(valores["fecha_vencimiento"])
            except nz.ErrorValor as exc:
                error("fecha_vencimiento", exc.codigo, exc.mensaje)
    else:
        datos.producto = texto_opcional("producto", 120)
        datos.oferta = texto_opcional("oferta", 2000)

    for col in extras:
        valor = valores.get(col, "").strip()
        if valor:
            datos.datos_adicionales[col] = valor[:MAX_VALOR_ADICIONAL]

    hay_error = any(i.severidad == "error" for i in inc)
    return ResultadoFila(numero, None if hay_error else datos, inc)


def _lotes(valores: Iterable[Any], tam: int = _LOTE) -> Iterator[list[Any]]:
    lote: list[Any] = []
    for v in valores:
        lote.append(v)
        if len(lote) >= tam:
            yield lote
            lote = []
    if lote:
        yield lote


def a_error_app(exc: ErrorLector) -> ErrorApp:
    return ErrorApp(422, exc.codigo, exc.mensaje, exc.detalles)


def es_xlsx(nombre: str) -> bool:
    return nombre.lower().endswith(".xlsx")


def leer_archivo(
    nombre: str, contenido: bytes, max_filas: int, requeridas: Sequence[str]
) -> ArchivoCsv:
    """Lee `.csv` o `.xlsx` (según la extensión) con la misma salida."""
    if es_xlsx(nombre):
        return leer_xlsx(
            contenido,
            max_filas,
            requeridas,
            get_settings().importacion_max_bytes_descomprimido,
        )
    return leer_csv(contenido, max_filas, requeridas)


def leer_subida(archivo: UploadFile, max_bytes: int) -> tuple[str, bytes]:
    """Valida extensión (.csv o .xlsx) y tamaño; devuelve (nombre, contenido)."""
    nombre = (archivo.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not nombre.lower().endswith((".csv", ".xlsx")):
        raise ErrorApp(422, "FORMATO_ARCHIVO_INVALIDO", "El archivo debe ser .csv o .xlsx.")
    contenido = archivo.file.read(max_bytes + 1)
    if len(contenido) > max_bytes:
        raise ErrorApp(
            413, "ARCHIVO_DEMASIADO_GRANDE", f"El archivo supera el máximo de {max_bytes} bytes."
        )
    return nombre[:255], contenido


def campana_importable(db: Session, campana_id: int) -> Campana:
    campana = db.get(Campana, campana_id)
    if campana is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")
    if campana.estado == "finalizada":
        raise ErrorApp(409, "CAMPANA_FINALIZADA", "La campaña está finalizada.")
    return campana


def _excluidos_entre(db: Session, tipo_campana: str, numeros: Iterable[str]) -> set[str]:
    resultado: set[str] = set()
    for lote in _lotes(sorted(set(numeros))):
        resultado.update(
            db.scalars(
                select(Exclusion.numero_e164).where(
                    Exclusion.numero_e164.in_(lote), Exclusion.aplica_a.in_((tipo_campana, "todas"))
                )
            )
        )
    return resultado


def importar(
    db: Session, campana: Campana, usuario: Usuario, nombre_archivo: str, contenido: bytes
) -> ImportacionDetalleSalida:
    settings = get_settings()
    try:
        archivo: ArchivoCsv = leer_archivo(
            nombre_archivo, contenido, settings.importacion_max_filas, REQUERIDAS
        )
    except ErrorLector as exc:
        raise a_error_app(exc) from exc

    tipo = campana.tipo
    propias = set(columnas_propias(tipo))
    extras = [c for c in archivo.cabeceras if c not in propias]
    incidencias: list[Incidencia] = []
    largas = [c for c in extras if len(c) > MAX_LONGITUD_CLAVE]
    if largas:
        extras = [c for c in extras if len(c) <= MAX_LONGITUD_CLAVE]
        incidencias.append(
            Incidencia(
                1,
                None,
                "COLUMNAS_ADICIONALES_IGNORADAS",
                f"Se ignoraron {len(largas)} columnas adicionales con nombre de más de "
                f"{MAX_LONGITUD_CLAVE} caracteres.",
                "advertencia",
            )
        )
    if len(extras) > MAX_CLAVES_ADICIONALES:
        incidencias.append(
            Incidencia(
                1,
                None,
                "COLUMNAS_ADICIONALES_IGNORADAS",
                f"Se ignoraron {len(extras) - MAX_CLAVES_ADICIONALES} columnas adicionales "
                f"(máximo {MAX_CLAVES_ADICIONALES}).",
                "advertencia",
            )
        )
        extras = extras[:MAX_CLAVES_ADICIONALES]

    resultados = [validar_fila(f.numero, f.valores, tipo, extras) for f in archivo.filas]

    try:
        imp = Importacion(
            campana_id=campana.id,
            nombre_archivo=nombre_archivo,
            estado="completada",
            total_filas=len(resultados),
            creado_por=usuario.id,
        )
        db.add(imp)
        db.flush()

        validas = [r.datos for r in resultados if r.datos is not None]
        claves_campana = {
            (t, n)
            for t, n in db.execute(
                select(Cliente.tipo_documento, Cliente.numero_documento)
                .join(CampanaCliente, CampanaCliente.cliente_id == Cliente.id)
                .where(CampanaCliente.campana_id == campana.id)
            )
        }
        excluidos = _excluidos_entre(
            db, tipo, (t.numero_e164 for d in validas for _, t in d.telefonos)
        )
        existentes: dict[tuple[str, str], Cliente] = {}
        for lote in _lotes({(d.tipo_documento, d.numero_documento) for d in validas}):
            for cli in db.scalars(
                select(Cliente).where(
                    tuple_(Cliente.tipo_documento, Cliente.numero_documento).in_(lote)
                )
            ):
                existentes[(cli.tipo_documento, cli.numero_documento)] = cli
        tels_existentes: dict[int, set[str]] = {}
        for lote in _lotes([c.id for c in existentes.values()]):
            for cid, num in db.execute(
                select(Telefono.cliente_id, Telefono.numero_e164).where(
                    Telefono.cliente_id.in_(lote)
                )
            ):
                tels_existentes.setdefault(cid, set()).add(num)

        vistos: dict[tuple[str, str], int] = {}
        importadas = duplicadas = invalidas = excluidas = 0
        for r in resultados:
            incidencias.extend(r.incidencias)
            d = r.datos
            if d is None:
                invalidas += 1
                continue
            clave = (d.tipo_documento, d.numero_documento)
            masc = enmascarar(d.numero_documento)
            if clave in vistos:
                duplicadas += 1
                incidencias.append(
                    Incidencia(
                        r.fila,
                        "numero_documento",
                        "DUPLICADO_EN_ARCHIVO",
                        f"Documento repetido en el archivo (primera aparición en la fila "
                        f"{vistos[clave]}).",
                        "advertencia",
                    )
                )
                continue
            vistos[clave] = r.fila
            if clave in claves_campana:
                duplicadas += 1
                incidencias.append(
                    Incidencia(
                        r.fila,
                        "numero_documento",
                        "DUPLICADO_EN_CAMPANA",
                        f"El cliente ({masc}) ya está en la campaña; no se actualiza.",
                        "advertencia",
                    )
                )
                continue
            en_exclusion = [(p, t) for p, t in d.telefonos if t.numero_e164 in excluidos]
            if len(en_exclusion) == len(d.telefonos):
                excluidas += 1
                incidencias.append(
                    Incidencia(
                        r.fila,
                        "telefono_1",
                        "TODOS_TELEFONOS_EXCLUIDOS",
                        f"Todos los teléfonos están excluidos para campañas de {tipo}.",
                        "advertencia",
                    )
                )
                continue
            for pos, tel in en_exclusion:
                incidencias.append(
                    Incidencia(
                        r.fila,
                        f"telefono_{pos}",
                        "TELEFONO_EXCLUIDO",
                        f"Teléfono excluido ({enmascarar(tel.numero_e164)}); se importa, "
                        "se verificará de nuevo al marcar.",
                        "advertencia",
                    )
                )
            _guardar(db, campana.id, imp.id, d, existentes, tels_existentes)
            importadas += 1

        imp.filas_importadas = importadas
        imp.filas_duplicadas = duplicadas
        imp.filas_invalidas = invalidas
        imp.filas_excluidas = excluidas
        assert imp.total_filas == importadas + duplicadas + invalidas + excluidas
        db.add_all(
            ImportacionError(
                importacion_id=imp.id,
                fila=i.fila,
                campo=i.campo,
                codigo=i.codigo,
                mensaje=i.mensaje[:300],
                severidad=i.severidad,
            )
            for i in incidencias
        )
        auditoria.registrar(
            db,
            "importacion.crear",
            usuario.id,
            "importacion",
            imp.id,
            {
                "campana_id": campana.id,
                "total_filas": imp.total_filas,
                "importadas": importadas,
                "duplicadas": duplicadas,
                "invalidas": invalidas,
                "excluidas": excluidas,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorApp(
            409,
            "IMPORTACION_CONCURRENTE",
            "Otra operación modificó los mismos datos; reintente la importación.",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return ImportacionDetalleSalida(
        id=imp.id,
        campana_id=imp.campana_id,
        nombre_archivo=imp.nombre_archivo,
        estado="completada",
        total_filas=imp.total_filas,
        filas_importadas=importadas,
        filas_duplicadas=duplicadas,
        filas_invalidas=invalidas,
        filas_excluidas=excluidas,
        creado_por=imp.creado_por,
        creado_en=imp.creado_en,
        errores=[
            {
                "fila": i.fila,
                "campo": i.campo,
                "codigo": i.codigo,
                "mensaje": i.mensaje[:300],
                "severidad": i.severidad,
            }
            for i in incidencias[:MAX_ERRORES_RESPUESTA]
        ],  # type: ignore[arg-type]
        errores_truncados=len(incidencias) > MAX_ERRORES_RESPUESTA,
    )


def _guardar(
    db: Session,
    campana_id: int,
    importacion_id: int,
    d: FilaValida,
    existentes: dict[tuple[str, str], Cliente],
    tels_existentes: dict[int, set[str]],
) -> None:
    clave = (d.tipo_documento, d.numero_documento)
    cliente = existentes.get(clave)
    if cliente is None:
        cliente = Cliente(
            tipo_documento=d.tipo_documento,
            numero_documento=d.numero_documento,
            nombre=d.nombre,
            email=d.email,
            ciudad=d.ciudad,
        )
        for pos, tel in d.telefonos:
            cliente.telefonos.append(
                Telefono(numero_e164=tel.numero_e164, tipo_linea=tel.tipo_linea, prioridad=pos)
            )
        db.add(cliente)
        existentes[clave] = cliente
    else:
        cliente.nombre = d.nombre
        if d.email:
            cliente.email = d.email
        if d.ciudad:
            cliente.ciudad = d.ciudad
        conocidos = tels_existentes.setdefault(cliente.id, set())
        for pos, tel in d.telefonos:
            if tel.numero_e164 not in conocidos:
                conocidos.add(tel.numero_e164)
                db.add(
                    Telefono(
                        cliente_id=cliente.id,
                        numero_e164=tel.numero_e164,
                        tipo_linea=tel.tipo_linea,
                        prioridad=pos,
                    )
                )
    db.add(
        CampanaCliente(
            campana_id=campana_id,
            cliente=cliente,
            importacion_id=importacion_id,
            estado="pendiente",
            numero_obligacion=d.numero_obligacion,
            saldo_total=d.saldo_total,
            saldo_mora=d.saldo_mora,
            dias_mora=d.dias_mora,
            fecha_vencimiento=d.fecha_vencimiento,
            producto=d.producto,
            oferta=d.oferta,
            datos_adicionales=d.datos_adicionales,
        )
    )
