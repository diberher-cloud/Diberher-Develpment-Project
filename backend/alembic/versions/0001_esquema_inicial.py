"""esquema inicial (tablas + semillas de políticas de cumplimiento)

Revision ID: 0001
Revises:
Create Date: 2026-10-23 16:16:56.659903
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEMANA = [{"inicio": "07:00", "fin": "19:00"}]
_POLITICA_POR_DEFECTO = {
    "zona_horaria": "America/Bogota",
    "franjas": {
        "lunes": _SEMANA,
        "martes": _SEMANA,
        "miercoles": _SEMANA,
        "jueves": _SEMANA,
        "viernes": _SEMANA,
        "sabado": [{"inicio": "08:00", "fin": "15:00"}],
        "domingo": [],
    },
    "permitir_festivos": False,
    "frecuencia": {
        "max_contactos_dia": 1,
        "max_canales_semana": 1,
        "semana": "calendario",
        "solo_tras_contacto_directo": True,
    },
}


def _sembrar_politicas() -> None:
    tabla = sa.table(
        "politicas_cumplimiento",
        sa.column("tipo_campana", sa.String),
        sa.column("version", sa.Integer),
        sa.column("configuracion", sa.JSON),
        sa.column("activa", sa.Boolean),
        sa.column("creado_por", sa.Integer),
        sa.column("creado_en", sa.DateTime(timezone=True)),
    )
    ahora = datetime.now(UTC)
    op.bulk_insert(
        tabla,
        [
            {
                "tipo_campana": tipo,
                "version": 1,
                "configuracion": _POLITICA_POR_DEFECTO,
                "activa": True,
                "creado_por": None,
                "creado_en": ahora,
            }
            for tipo in ("venta", "cobranza")
        ],
    )


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipo_documento", sa.String(length=5), nullable=False),
        sa.Column("numero_documento", sa.String(length=20), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("ciudad", sa.String(length=100), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "tipo_documento IN ('CC','CE','NIT','PA','TI','PPT')",
            name=op.f("ck_clientes_tipo_documento"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clientes")),
        sa.UniqueConstraint(
            "tipo_documento", "numero_documento", name=op.f("uq_clientes_tipo_documento")
        ),
    )
    op.create_table(
        "festivos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("origen", sa.String(length=12), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("origen IN ('calculado','manual')", name=op.f("ck_festivos_origen")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_festivos")),
        sa.UniqueConstraint("fecha", name=op.f("uq_festivos_fecha")),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rol IN ('administrador','supervisor','agente')", name=op.f("ck_usuarios_rol")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
        sa.UniqueConstraint("email", name=op.f("uq_usuarios_email")),
    )
    op.create_table(
        "auditoria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("accion", sa.String(length=60), nullable=False),
        sa.Column("entidad", sa.String(length=40), nullable=True),
        sa.Column("entidad_id", sa.String(length=40), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_auditoria_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auditoria")),
    )
    op.create_table(
        "campanas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(length=20), server_default="borrador", nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("guion", sa.Text(), nullable=True),
        sa.Column("max_intentos", sa.Integer(), server_default="3", nullable=False),
        sa.Column("intervalo_reintento_minutos", sa.Integer(), server_default="60", nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('borrador','activa','pausada','finalizada')",
            name=op.f("ck_campanas_estado"),
        ),
        sa.CheckConstraint("tipo IN ('venta','cobranza')", name=op.f("ck_campanas_tipo")),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio",
            name=op.f("ck_campanas_fechas"),
        ),
        sa.CheckConstraint(
            "intervalo_reintento_minutos BETWEEN 5 AND 10080", name=op.f("ck_campanas_intervalo")
        ),
        sa.CheckConstraint("max_intentos BETWEEN 1 AND 10", name=op.f("ck_campanas_max_intentos")),
        sa.ForeignKeyConstraint(
            ["creado_por"], ["usuarios.id"], name=op.f("fk_campanas_creado_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campanas")),
        sa.UniqueConstraint("nombre", name=op.f("uq_campanas_nombre")),
    )
    op.create_table(
        "exclusiones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero_e164", sa.String(length=16), nullable=False),
        sa.Column("motivo", sa.String(length=30), nullable=False),
        sa.Column("aplica_a", sa.String(length=10), nullable=False),
        sa.Column("observacion", sa.String(length=300), nullable=True),
        sa.Column("creado_por", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "aplica_a IN ('venta','cobranza','todas')", name=op.f("ck_exclusiones_aplica_a")
        ),
        sa.CheckConstraint(
            "motivo IN ('rne','solicitud_titular','numero_errado','manual')",
            name=op.f("ck_exclusiones_motivo"),
        ),
        sa.ForeignKeyConstraint(
            ["creado_por"], ["usuarios.id"], name=op.f("fk_exclusiones_creado_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exclusiones")),
        sa.UniqueConstraint("numero_e164", "aplica_a", name=op.f("uq_exclusiones_numero_e164")),
    )
    with op.batch_alter_table("exclusiones", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_exclusiones_numero_e164"), ["numero_e164"], unique=False
        )

    op.create_table(
        "politicas_cumplimiento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipo_campana", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configuracion", sa.JSON(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "tipo_campana IN ('venta','cobranza')",
            name=op.f("ck_politicas_cumplimiento_tipo_campana"),
        ),
        sa.ForeignKeyConstraint(
            ["creado_por"],
            ["usuarios.id"],
            name=op.f("fk_politicas_cumplimiento_creado_por_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_politicas_cumplimiento")),
        sa.UniqueConstraint(
            "tipo_campana", "version", name=op.f("uq_politicas_cumplimiento_tipo_campana")
        ),
    )
    op.create_table(
        "telefonos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("numero_e164", sa.String(length=16), nullable=False),
        sa.Column("tipo_linea", sa.String(length=10), nullable=False),
        sa.Column("prioridad", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tipo_linea IN ('movil','fijo')", name=op.f("ck_telefonos_tipo_linea")),
        sa.ForeignKeyConstraint(
            ["cliente_id"],
            ["clientes.id"],
            name=op.f("fk_telefonos_cliente_id_clientes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telefonos")),
        sa.UniqueConstraint("cliente_id", "numero_e164", name=op.f("uq_telefonos_cliente_id")),
    )
    with op.batch_alter_table("telefonos", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_telefonos_numero_e164"), ["numero_e164"], unique=False)

    op.create_table(
        "importaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("total_filas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_importadas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_duplicadas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_invalidas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filas_excluidas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('completada','fallida')", name=op.f("ck_importaciones_estado")
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_importaciones_campana_id_campanas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creado_por"], ["usuarios.id"], name=op.f("fk_importaciones_creado_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_importaciones")),
    )
    op.create_table(
        "campana_clientes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("importacion_id", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(length=20), server_default="pendiente", nullable=False),
        sa.Column("numero_obligacion", sa.String(length=50), nullable=True),
        sa.Column("saldo_total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("saldo_mora", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("dias_mora", sa.Integer(), nullable=True),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("producto", sa.String(length=120), nullable=True),
        sa.Column("oferta", sa.Text(), nullable=True),
        sa.Column("datos_adicionales", sa.JSON(), nullable=False),
        sa.Column("intentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("proximo_intento_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('pendiente','en_gestion','gestionado','descartado')",
            name=op.f("ck_campana_clientes_estado"),
        ),
        sa.CheckConstraint(
            "dias_mora IS NULL OR dias_mora >= 0", name=op.f("ck_campana_clientes_dias_mora")
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_campana_clientes_campana_id_campanas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_id"], ["clientes.id"], name=op.f("fk_campana_clientes_cliente_id_clientes")
        ),
        sa.ForeignKeyConstraint(
            ["importacion_id"],
            ["importaciones.id"],
            name=op.f("fk_campana_clientes_importacion_id_importaciones"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campana_clientes")),
        sa.UniqueConstraint(
            "campana_id", "cliente_id", name=op.f("uq_campana_clientes_campana_id")
        ),
    )
    with op.batch_alter_table("campana_clientes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_campana_clientes_campana_id"), ["campana_id"], unique=False
        )

    op.create_table(
        "importacion_errores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("importacion_id", sa.Integer(), nullable=False),
        sa.Column("fila", sa.Integer(), nullable=False),
        sa.Column("campo", sa.String(length=50), nullable=True),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("mensaje", sa.String(length=300), nullable=False),
        sa.Column("severidad", sa.String(length=12), nullable=False),
        sa.CheckConstraint(
            "severidad IN ('error','advertencia')", name=op.f("ck_importacion_errores_severidad")
        ),
        sa.ForeignKeyConstraint(
            ["importacion_id"],
            ["importaciones.id"],
            name=op.f("fk_importacion_errores_importacion_id_importaciones"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_importacion_errores")),
    )
    with op.batch_alter_table("importacion_errores", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_importacion_errores_importacion_id"), ["importacion_id"], unique=False
        )
    _sembrar_politicas()


def downgrade() -> None:
    with op.batch_alter_table("importacion_errores", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_importacion_errores_importacion_id"))

    op.drop_table("importacion_errores")
    with op.batch_alter_table("campana_clientes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_campana_clientes_campana_id"))

    op.drop_table("campana_clientes")
    op.drop_table("importaciones")
    with op.batch_alter_table("telefonos", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_telefonos_numero_e164"))

    op.drop_table("telefonos")
    op.drop_table("politicas_cumplimiento")
    with op.batch_alter_table("exclusiones", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_exclusiones_numero_e164"))

    op.drop_table("exclusiones")
    op.drop_table("campanas")
    op.drop_table("auditoria")
    op.drop_table("usuarios")
    op.drop_table("festivos")
    op.drop_table("clientes")
