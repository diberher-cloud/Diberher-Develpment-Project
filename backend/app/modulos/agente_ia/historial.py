"""Lectura y escritura append-only de `historial_ia` (lo que vio el modelo).

Nunca se actualiza ni se borra una fila. Quien escribe tiene la conversación bloqueada
(`FOR UPDATE`), así la secuencia no se pisa.
"""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modulos.agente_ia.contexto import RefInteraccion
from app.modulos.agente_ia.mensajes import FilaHistorial
from app.modulos.agente_ia.modelos import AccionIA, HistorialIA

MENSAJE_INTERRUMPIDO = (
    "La acción no se ejecutó porque la conversación se interrumpió. "
    "Si sigue siendo necesaria, vuelve a solicitarla."
)
RELLENO_VACIO = [{"type": "text", "text": "(sin contenido)"}]


def _filtro(ref: RefInteraccion):
    col = HistorialIA.conversacion_id if ref.tipo == "conversacion" else HistorialIA.llamada_id
    return col == ref.id


def agregar(
    db: Session,
    ref: RefInteraccion,
    rol: str,
    tipo: str,
    contenido: Any,
    ahora: datetime,
    *,
    modelo: str | None = None,
    uso_ia_id: int | None = None,
) -> HistorialIA:
    siguiente = (db.scalar(select(func.max(HistorialIA.secuencia)).where(_filtro(ref))) or 0) + 1
    if rol == "assistant" and not contenido:
        # Un `assistant` vacío no se puede reenviar en una petición posterior.
        contenido = RELLENO_VACIO
    fila = HistorialIA(
        conversacion_id=ref.id if ref.tipo == "conversacion" else None,
        llamada_id=ref.id if ref.tipo == "llamada" else None,
        secuencia=siguiente,
        rol=rol,
        tipo=tipo,
        contenido=contenido,
        modelo=modelo,
        uso_ia_id=uso_ia_id,
        creado_en=ahora,
    )
    db.add(fila)
    db.flush()
    return fila


def filas(db: Session, ref: RefInteraccion) -> list[HistorialIA]:
    return list(db.scalars(select(HistorialIA).where(_filtro(ref)).order_by(HistorialIA.secuencia)))


def leer(db: Session, ref: RefInteraccion) -> list[FilaHistorial]:
    return [FilaHistorial(f.secuencia, f.rol, f.tipo, f.contenido) for f in filas(db, ref)]


def espera_respuesta(db: Session, ref: RefInteraccion) -> bool:
    """¿Hay filas tras el último `assistant` (o ninguna `assistant` y sí filas)? Es decir, el
    modelo debe responder a algo ya incorporado al historial."""
    ultima = db.scalar(
        select(HistorialIA.rol).where(_filtro(ref)).order_by(HistorialIA.secuencia.desc()).limit(1)
    )
    return ultima is not None and ultima != "assistant"


def ultima_fecha_contexto(db: Session, ref: RefInteraccion) -> str | None:
    """Fecha local (AAAA-MM-DD) del último mensaje de contexto guardado."""
    for f in reversed(filas(db, ref)):
        if f.tipo == "contexto" and isinstance(f.contenido, dict):
            return f.contenido.get("fecha_local")
    return None


def tool_use_pendientes(db: Session, ref: RefInteraccion) -> list[str]:
    """Ids de `tool_use` del último `assistant` sin `tool_result` en las filas posteriores."""
    todas = filas(db, ref)
    indice = max((i for i, f in enumerate(todas) if f.rol == "assistant"), default=None)
    if indice is None:
        return []
    ids = [
        b["id"]
        for b in todas[indice].contenido
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    resueltos = {
        b.get("tool_use_id")
        for f in todas[indice + 1 :]
        if f.rol == "user"
        for b in f.contenido
        if isinstance(b, dict) and b.get("type") == "tool_result"
    }
    return [i for i in ids if i not in resueltos]


def bloque_resultado(tool_use_id: str, resultado: dict[str, Any], es_error: bool) -> dict[str, Any]:
    bloque: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(resultado, ensure_ascii=False, separators=(",", ":")),
    }
    if es_error:
        bloque["is_error"] = True
    return bloque


def reparar_pendientes(db: Session, ref: RefInteraccion, ahora: datetime) -> int:
    """Completa los `tool_use` sin `tool_result` (caída tras ejecutar alguna herramienta o turno
    interrumpido): el resultado guardado en `acciones_ia` o un error `INTERRUMPIDO`. NUNCA ejecuta
    una herramienta pendiente. Devuelve cuántos completó."""
    pendientes = tool_use_pendientes(db, ref)
    if not pendientes:
        return 0
    col = AccionIA.conversacion_id if ref.tipo == "conversacion" else AccionIA.llamada_id
    guardadas = {
        a.tool_use_id: a
        for a in db.scalars(
            select(AccionIA).where(col == ref.id, AccionIA.tool_use_id.in_(pendientes))
        )
    }
    bloques = []
    for tid in pendientes:
        a = guardadas.get(tid)
        if a is not None:
            bloques.append(bloque_resultado(tid, a.resultado, a.es_error))
        else:
            bloques.append(
                bloque_resultado(
                    tid, {"codigo": "INTERRUMPIDO", "mensaje": MENSAJE_INTERRUMPIDO}, True
                )
            )
    agregar(db, ref, "user", "resultados_herramientas", bloques, ahora)
    return len(bloques)
