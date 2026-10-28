from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.errores import ErrorApp
from app.modulos.campanas.modelos import Campana
from app.modulos.clientes.esquemas import CampanaClienteSalida, ClienteSalida, TelefonoSalida
from app.modulos.clientes.modelos import CampanaCliente, Cliente, Telefono
from app.modulos.exclusiones.modelos import Exclusion
from app.modulos.importacion.telefonos import ErrorTelefono, normalizar_telefono
from app.paginacion import ParamsPaginacion, paginar


def listar_clientes_campana(
    db: Session, campana_id: int, params: ParamsPaginacion, q: str | None, estado: str | None
) -> tuple[list[CampanaClienteSalida], int]:
    campana = db.get(Campana, campana_id)
    if campana is None:
        raise ErrorApp(404, "NO_ENCONTRADO", "Campaña no encontrada.")

    consulta = (
        select(CampanaCliente, Cliente)
        .join(Cliente, Cliente.id == CampanaCliente.cliente_id)
        .where(CampanaCliente.campana_id == campana_id)
    )
    if estado:
        consulta = consulta.where(CampanaCliente.estado == estado)
    if q and q.strip():
        termino = q.strip()
        patron = (
            "%"
            + termino.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        condiciones = [
            func.lower(Cliente.nombre).like(patron, escape="\\"),
            Cliente.numero_documento == termino,
        ]
        try:
            e164 = normalizar_telefono(termino).numero_e164
            condiciones.append(
                exists().where(Telefono.cliente_id == Cliente.id, Telefono.numero_e164 == e164)
            )
        except ErrorTelefono:
            pass
        consulta = consulta.where(or_(*condiciones))
    filas, total = paginar(db, consulta.order_by(CampanaCliente.id), params, escalares=False)

    ids_cliente = [cli.id for _, cli in filas]
    telefonos: dict[int, list[Telefono]] = {}
    if ids_cliente:
        for tel in db.scalars(
            select(Telefono)
            .where(Telefono.cliente_id.in_(ids_cliente))
            .order_by(Telefono.prioridad, Telefono.id)
        ):
            telefonos.setdefault(tel.cliente_id, []).append(tel)
    numeros = {t.numero_e164 for lista in telefonos.values() for t in lista}
    excluidos: set[str] = set()
    if numeros:
        excluidos = set(
            db.scalars(
                select(Exclusion.numero_e164).where(
                    Exclusion.numero_e164.in_(numeros),
                    Exclusion.aplica_a.in_((campana.tipo, "todas")),
                    Exclusion.canal.in_(("todos", "voz")),
                )
            )
        )

    items = []
    for cc, cli in filas:
        items.append(
            CampanaClienteSalida(
                id=cc.id,
                estado=cc.estado,  # type: ignore[arg-type]
                intentos=cc.intentos,
                cliente=ClienteSalida(
                    id=cli.id,
                    tipo_documento=cli.tipo_documento,
                    numero_documento=cli.numero_documento,
                    nombre=cli.nombre,
                    email=cli.email,
                    ciudad=cli.ciudad,
                ),
                telefonos=[
                    TelefonoSalida(
                        id=t.id,
                        numero_e164=t.numero_e164,
                        tipo_linea=t.tipo_linea,  # type: ignore[arg-type]
                        prioridad=t.prioridad,
                        excluido=t.numero_e164 in excluidos,
                    )
                    for t in telefonos.get(cli.id, [])
                ],
                numero_obligacion=cc.numero_obligacion,
                saldo_total=cc.saldo_total,
                saldo_mora=cc.saldo_mora,
                dias_mora=cc.dias_mora,
                fecha_vencimiento=cc.fecha_vencimiento,
                producto=cc.producto,
                oferta=cc.oferta,
                datos_adicionales=cc.datos_adicionales or {},
                importacion_id=cc.importacion_id,
                creado_en=cc.creado_en,
            )
        )
    return items, total
