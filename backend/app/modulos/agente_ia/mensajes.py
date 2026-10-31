"""Construcción PURA de la petición al modelo (fase-2c.md §4.3): escape de textos del cliente,
formato de entradas, mensajes de contexto y reconstrucción de `messages` desde `historial_ia`.

Reglas de los mensajes `role: "system"` intermedios (documentación del SDK): deben seguir a un
mensaje `user` y ser el último elemento o ir seguidos de un `assistant`; no pueden ser
`messages[0]` y solo llevan texto. Por eso cada SEGMENTO del historial (filas entre dos
`assistant`) se emite normalizado: un único `user` (los `tool_result` primero) y un único `system`
detrás. Un segmento emite lo mismo estando abierto o cerrado, así el prefijo cacheado no cambia.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modulos.agente_ia.canal import EntradaCliente

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
CONTROL_RESPUESTA_BLOQUEADA = '<control_servidor tipo="respuesta_bloqueada"/>'


@dataclass(frozen=True)
class FilaHistorial:
    secuencia: int
    rol: str  # user | assistant | system
    tipo: str
    contenido: Any  # lista de bloques (user/assistant) o {"texto": ...} (system)


def escapar(texto: str) -> str:
    """`&`, `<`, `>` (en ese orden): el cliente no puede cerrar etiquetas ni falsificar bloques
    del servidor."""
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _local(momento: datetime, zona: str) -> datetime:
    return momento.astimezone(ZoneInfo(zona))


def fecha_local_iso(momento: datetime, zona: str) -> str:
    return _local(momento, zona).strftime("%Y-%m-%dT%H:%M")


def formatear_fecha_hora(momento: datetime, zona: str) -> str:
    """`viernes 23/10/2026 10:15 (America/Bogota)`."""
    local = _local(momento, zona)
    return f"{DIAS[local.weekday()]} {local:%d/%m/%Y %H:%M} ({zona})"


def formatear_entradas(
    entradas: Sequence[EntradaCliente], zona: str, omitidas: int = 0
) -> list[dict[str, str]]:
    """Un bloque `text` por mensaje del cliente (ADR-0014 §4). Los medios nunca llevan URL ni
    binario: solo una etiqueta `soportado="false"`."""
    bloques: list[dict[str, str]] = []
    if omitidas:
        bloques.append({"type": "text", "text": f'<mensajes_omitidos cantidad="{omitidas}"/>'})
    for e in entradas:
        base = f'<mensaje_cliente id="{e.id}" fecha_local="{fecha_local_iso(e.momento, zona)}"'
        texto = escapar(e.texto) if e.texto else ""
        if e.tipo == "texto":
            bloque = f"{base}>{texto}</mensaje_cliente>"
        elif e.tipo == "boton":
            bloque = f'{base} tipo="boton">{texto}</mensaje_cliente>'
        else:
            tipo = e.categoria_media if e.tipo == "media" and e.categoria_media else "no_soportado"
            marca = f'{base} tipo="{tipo}" soportado="false"'
            bloque = f"{marca}>Pie: {texto}</mensaje_cliente>" if texto else f"{marca}/>"
        bloques.append({"type": "text", "text": bloque})
    return bloques


# ---- Mensajes de sistema -----------------------------------------------------------------------
def contexto_sistema(
    *,
    tipo_campana: str,
    tratamiento: str,
    nombre_pila: str | None,
    ahora: datetime,
    zona: str,
    iniciada_por: str,
    identidad_verificada: bool,
    instrucciones: str | None,
) -> str:
    """Contexto inicial (tras el primer `user`). Nunca: documento, teléfono, email, saldos,
    ofertas ni el `nombre_perfil` de WhatsApp (lo controla el cliente)."""
    quien = "el cliente" if iniciada_por == "cliente" else "la empresa"
    return "\n".join(
        [
            "Contexto de la conversación (lo fija el servidor):",
            f"- Tipo de campaña: {tipo_campana}.",
            f"- Trato: {tratamiento}.",
            f"- Nombre de pila registrado del titular: {nombre_pila or 'desconocido'}.",
            f"- Fecha y hora local: {formatear_fecha_hora(ahora, zona)}.",
            f"- Conversación iniciada por: {quien}.",
            f"- Identidad verificada: {'sí' if identidad_verificada else 'no'}.",
            f"- Instrucciones de la campaña: {instrucciones or 'ninguna'}.",
        ]
    )


def cambio_de_fecha(ahora: datetime, zona: str) -> str:
    return f"Fecha y hora local: {formatear_fecha_hora(ahora, zona)}."


def instruccion_supervisor(texto: str) -> str:
    return f"Instrucción del supervisor: {texto}"


def correccion(motivo: str) -> str:
    return (
        f"Tu última respuesta no se envió al cliente: {motivo}. "
        "Escríbela de nuevo cumpliendo las reglas."
    )


MENSAJE_VUELTA_IA = (
    "La conversación vuelve a ti tras la intervención de un asesor. El bloque "
    "<intervencion_humana> del último mensaje resume lo hablado; las cifras que dio el asesor "
    "no son resultados de herramientas: consúltalas antes de usarlas."
)


def bloque_intervencion(
    mensajes: Sequence[tuple[str, int, datetime, str]], zona: str
) -> list[dict[str, str]]:
    """`<intervencion_humana>` con los mensajes desde el último que vio el modelo. Cada tupla es
    (clase, id, momento, texto) con clase `cliente` | `asesor` | `sistema`; escapados."""
    lineas = ["<intervencion_humana>"]
    for clase, ident, momento, texto in mensajes:
        fecha = fecha_local_iso(momento, zona)
        if clase == "cliente":
            lineas.append(
                f'<mensaje_cliente id="{ident}" fecha_local="{fecha}">{escapar(texto)}'
                "</mensaje_cliente>"
            )
        elif clase == "asesor":
            lineas.append(
                f'<mensaje_asesor fecha_local="{fecha}">{escapar(texto)}</mensaje_asesor>'
            )
        else:
            lineas.append(
                f'<mensaje_sistema fecha_local="{fecha}">{escapar(texto)}</mensaje_sistema>'
            )
    lineas.append("</intervencion_humana>")
    return [{"type": "text", "text": "\n".join(lineas)}]


# ---- Reconstrucción de la petición -------------------------------------------------------------
class PeticionInvalida(Exception):
    pass


def _segmentos(filas: Sequence[FilaHistorial]) -> list[list[FilaHistorial]]:
    """Filas agrupadas en segmentos: cada uno acaba en su `assistant` (el último puede no)."""
    segmentos: list[list[FilaHistorial]] = []
    actual: list[FilaHistorial] = []
    for f in filas:
        actual.append(f)
        if f.rol == "assistant":
            segmentos.append(actual)
            actual = []
    if actual:
        segmentos.append(actual)
    return segmentos


def _bloques(contenido: Any) -> list[dict[str, Any]]:
    return list(contenido) if isinstance(contenido, list) else [contenido]


def _segmento_a_mensajes(segmento: list[FilaHistorial], sin_system: bool) -> list[dict[str, Any]]:
    asistente = segmento[-1] if segmento[-1].rol == "assistant" else None
    previas = segmento[:-1] if asistente is not None else segmento
    resultados: list[dict[str, Any]] = []
    otros: list[dict[str, Any]] = []
    avisos: list[str] = []
    for f in previas:
        if f.rol == "system":
            avisos.append(str(f.contenido["texto"]))
            continue
        for b in _bloques(f.contenido):
            (resultados if b.get("type") == "tool_result" else otros).append(b)
    usuario = resultados + otros
    mensajes: list[dict[str, Any]] = []
    if avisos and (sin_system or not usuario):
        # Modelo sin `system` intermedio (o `system` sin `user` previo): va como texto del user.
        usuario = usuario + [
            {"type": "text", "text": f"<aviso_servidor>{a}</aviso_servidor>"} for a in avisos
        ]
        avisos = []
    if usuario:
        mensajes.append({"role": "user", "content": usuario})
    if avisos:
        mensajes.append({"role": "system", "content": "\n\n".join(avisos)})
    if asistente is not None:
        mensajes.append({"role": "assistant", "content": _bloques(asistente.contenido)})
    return mensajes


def construir_peticion(
    filas: Sequence[FilaHistorial], modelo: str, modelos_sin_system: frozenset[str]
) -> list[dict[str, Any]]:
    """`messages` a partir del historial append-only. Invariantes (se comprueban): empieza por
    `user`, nunca acaba en `assistant` y cada `tool_use` tiene su `tool_result` a continuación."""
    sin_system = modelo in modelos_sin_system
    mensajes: list[dict[str, Any]] = []
    for segmento in _segmentos(filas):
        mensajes.extend(_segmento_a_mensajes(segmento, sin_system))
    validar_peticion(mensajes)
    return mensajes


def validar_peticion(mensajes: Sequence[dict[str, Any]]) -> None:
    if not mensajes or mensajes[0]["role"] != "user":
        raise PeticionInvalida("El primer mensaje debe ser user.")
    ultimo = mensajes[-1]
    if ultimo["role"] == "assistant" and not (
        ultimo["content"] and ultimo["content"][-1].get("type") == "server_tool_use"
    ):
        # Solo una pausa de herramienta de servidor (`pause_turn`) se reanuda con un assistant
        # final; cualquier otro caso sería *prefill*.
        raise PeticionInvalida("La petición no puede acabar en assistant (prefill).")
    for i, m in enumerate(mensajes):
        if m["role"] == "system":
            if mensajes[i - 1]["role"] != "user":
                raise PeticionInvalida("system debe ir tras un user.")
            if i + 1 < len(mensajes) and mensajes[i + 1]["role"] != "assistant":
                raise PeticionInvalida("system debe ir seguido de assistant o ser el último.")
        if m["role"] == "assistant":
            usos = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
            if usos:
                siguiente = mensajes[i + 1] if i + 1 < len(mensajes) else None
                if siguiente is None or siguiente["role"] != "user":
                    raise PeticionInvalida("tool_use sin tool_result.")
                resueltos = {
                    b["tool_use_id"] for b in siguiente["content"] if b.get("type") == "tool_result"
                }
                if usos - resueltos:
                    raise PeticionInvalida("tool_use sin tool_result.")
