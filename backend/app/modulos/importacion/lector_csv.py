"""Lectura pura de CSV: decodificación, delimitador, cabeceras normalizadas y filas."""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modulos.importacion.normalizacion import normalizar_cabecera


class ErrorLector(Exception):
    def __init__(
        self, codigo: str, mensaje: str, detalles: list[dict[str, str]] | None = None
    ) -> None:
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles or []


@dataclass(frozen=True)
class FilaCsv:
    numero: int  # línea física del archivo donde empieza el registro (cabecera = 1)
    valores: dict[str, str]


@dataclass
class ArchivoCsv:
    cabeceras: list[str]
    filas: list[FilaCsv] = field(default_factory=list)


def decodificar(datos: bytes) -> str:
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return datos.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise ErrorLector(
            "FORMATO_ARCHIVO_INVALIDO", "No se pudo decodificar el archivo (UTF-8 o cp1252)."
        ) from exc


def detectar_delimitador(linea: str) -> str:
    return ";" if linea.count(";") > linea.count(",") else ","


def leer_csv(datos: bytes, max_filas: int, requeridas: Sequence[str] = ()) -> ArchivoCsv:
    texto = decodificar(datos)
    if "\x00" in texto:
        raise ErrorLector("FORMATO_ARCHIVO_INVALIDO", "El archivo no es un CSV de texto válido.")
    primera = next((linea for linea in texto.splitlines() if linea.strip()), "")
    delimitador = detectar_delimitador(primera)
    lector = csv.reader(io.StringIO(texto, newline=""), delimiter=delimitador, quotechar='"')

    archivo: ArchivoCsv | None = None
    indices: dict[str, int] = {}
    try:
        while True:
            inicio = lector.line_num + 1
            try:
                registro = next(lector)
            except StopIteration:
                break
            if not any(c.strip() for c in registro):
                continue  # línea completamente vacía
            if archivo is None:
                cabeceras = [normalizar_cabecera(c) for c in registro]
                for i, nombre in enumerate(cabeceras):
                    if nombre and nombre not in indices:
                        indices[nombre] = i
                faltantes = [c for c in requeridas if c not in indices]
                if faltantes:
                    raise ErrorLector(
                        "COLUMNAS_FALTANTES",
                        "Faltan columnas obligatorias.",
                        [
                            {"campo": c, "mensaje": "Columna obligatoria ausente."}
                            for c in faltantes
                        ],
                    )
                archivo = ArchivoCsv(cabeceras=list(indices))
                continue
            if len(archivo.filas) >= max_filas:
                raise ErrorLector(
                    "DEMASIADAS_FILAS", f"El archivo supera el máximo de {max_filas} filas."
                )
            valores = {
                nombre: (registro[i] if i < len(registro) else "").strip()
                for nombre, i in indices.items()
            }
            archivo.filas.append(FilaCsv(numero=inicio, valores=valores))
    except csv.Error as exc:
        raise ErrorLector("FORMATO_ARCHIVO_INVALIDO", "El archivo CSV está mal formado.") from exc

    if archivo is None:
        raise ErrorLector("ARCHIVO_VACIO", "El archivo no contiene filas de datos.")
    if not archivo.filas:
        raise ErrorLector("ARCHIVO_VACIO", "El archivo no contiene filas de datos.")
    return archivo
