"""Fábricas de datos para los tests de la Fase 2A (campaña, registro, agente)."""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modulos.campanas.modelos import Campana, CampanaAgente
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.consola.modelos import EstadoAgente
from app.seguridad import crear_token

_n = {"v": 0}


def _siguiente() -> int:
    _n["v"] += 1
    return _n["v"]


class Escenario:
    def __init__(self, db: Session, creador_id: int) -> None:
        self.db = db
        self.creador_id = creador_id

    def campana(
        self, tipo: str = "cobranza", estado: str = "activa", guion: str | None = None, **kw
    ) -> Campana:
        n = _siguiente()
        c = Campana(
            nombre=f"Campaña {n}",
            tipo=tipo,
            estado=estado,
            guion=guion,
            creado_por=self.creador_id,
            **kw,
        )
        self.db.add(c)
        self.db.commit()
        return c

    def registro(
        self,
        campana: Campana,
        numeros: tuple[str, ...] = ("+573001234567",),
        nombre: str = "María Pérez",
        saldo_total: str | None = "1500000.00",
        **kw,
    ) -> CampanaCliente:
        n = _siguiente()
        cliente = Cliente(tipo_documento="CC", numero_documento=f"1000{n:06d}", nombre=nombre)
        self.db.add(cliente)
        self.db.flush()
        for i, numero in enumerate(numeros, start=1):
            self.db.add(
                Telefono(
                    cliente_id=cliente.id,
                    numero_e164=numero,
                    tipo_linea="movil" if numero.startswith("+573") else "fijo",
                    prioridad=i,
                )
            )
        cc = CampanaCliente(
            campana_id=campana.id,
            cliente_id=cliente.id,
            saldo_total=Decimal(saldo_total) if saldo_total else None,
            saldo_mora=Decimal("250000.50"),
            dias_mora=45,
            **kw,
        )
        self.db.add(cc)
        self.db.commit()
        return cc

    def asignar(self, campana: Campana, agente) -> None:
        self.db.add(CampanaAgente(campana_id=campana.id, usuario_id=agente.id))
        self.db.commit()

    def estado(self, agente, estado: str, ahora: datetime, **kw) -> None:
        fila = self.db.get(EstadoAgente, agente.id)
        if fila is None:
            self.db.add(
                EstadoAgente(
                    usuario_id=agente.id, estado=estado, desde=ahora, actualizado_en=ahora, **kw
                )
            )
        else:
            fila.estado = estado
        self.db.commit()

    def reservar(self, cc: CampanaCliente, agente, ahora: datetime, minutos: int = 15) -> None:
        cc.estado = "en_gestion"
        cc.reservado_por = agente.id
        cc.reservado_hasta = ahora + timedelta(minutes=minutos)
        self.db.commit()


def telefono_de(db: Session, cc: CampanaCliente, posicion: int = 0) -> Telefono:
    return (
        db.query(Telefono)
        .filter_by(cliente_id=cc.cliente_id)
        .order_by(Telefono.prioridad)[posicion]
    )


def cab(usuario) -> dict[str, str]:
    token, _ = crear_token(usuario.id, usuario.rol)
    return {"Authorization": f"Bearer {token}"}
