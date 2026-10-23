"""Simulación de llamadas para desarrollo sin credenciales (proveedor falso, no producción).

Ejecuta los MISMOS servicios que el TwiML saliente y los webhooks de Twilio.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencias import requiere_rol
from app.errores import ErrorApp
from app.modulos.telefonia import servicio
from app.modulos.telefonia.esquemas import (
    EventoSimulacion,
    MotivoLlamada,
    ResultadoSimulacion,
    SimularLlamada,
)
from app.modulos.telefonia.modelos import Llamada
from app.modulos.usuarios.modelos import Usuario
from app.paginacion import IdRuta
from app.reloj import Reloj, get_reloj

router = APIRouter(prefix="/telefonia/simulacion", tags=["telefonía (simulación)"])
Agente = Annotated[Usuario, Depends(requiere_rol("agente"))]
Db = Annotated[Session, Depends(get_db)]
RelojDep = Annotated[Reloj, Depends(get_reloj)]


@router.post("/llamadas", response_model=ResultadoSimulacion)
def simular_llamada(
    datos: SimularLlamada, usuario: Agente, db: Db, reloj: RelojDep
) -> ResultadoSimulacion:
    resultado = servicio.procesar_saliente(
        db,
        call_sid=f"CAsim{uuid.uuid4().hex}",
        desde=f"client:agente_{usuario.id}",
        account_sid=None,
        campana_cliente_id=str(datos.campana_cliente_id),
        telefono_id=str(datos.telefono_id),
        ahora=reloj(),
        verificar_cuenta=False,
    )
    return ResultadoSimulacion(
        llamada_id=resultado.llamada_id,
        permitida=resultado.permitida,
        motivos=[MotivoLlamada(**m) for m in resultado.motivos],
    )


@router.post("/llamadas/{llamada_id}/eventos", status_code=204)
def simular_evento(
    llamada_id: IdRuta, datos: EventoSimulacion, usuario: Agente, db: Db, reloj: RelojDep
) -> Response:
    llamada = db.get(Llamada, llamada_id)
    if llamada is None or llamada.usuario_id != usuario.id:
        raise ErrorApp(404, "NO_ENCONTRADO", "Llamada no encontrada.")
    servicio.simular_evento(
        db, llamada, datos.evento, datos.resultado, datos.duracion_segundos, reloj()
    )
    return Response(status_code=204)
