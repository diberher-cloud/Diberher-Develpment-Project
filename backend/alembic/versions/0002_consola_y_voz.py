"""consola del agente y voz (Fase 2A)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 19:32:11.547493
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _crear_tickets_ws()
    # campana_clientes primero: las tablas nuevas la referencian y batch la recrea en SQLite.
    with op.batch_alter_table("campana_clientes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reservado_por", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reservado_hasta", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("ultimo_resultado", sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column("ultima_gestion_en", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_campana_clientes_campana_id_estado", ["campana_id", "estado"], unique=False
        )
        batch_op.create_index("ix_campana_clientes_reservado_por", ["reservado_por"], unique=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_campana_clientes_reservado_por_usuarios"),
            "usuarios",
            ["reservado_por"],
            ["id"],
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_campana_clientes_ultimo_resultado"),
            "ultimo_resultado IS NULL OR ultimo_resultado IN ('contactado','no_contesta',"
            "'numero_errado','promesa_pago','venta','rechazo','volver_a_llamar')",
        )

    op.create_table(
        "historial_estados_agente",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(length=15), nullable=False),
        sa.Column("motivo_pausa", sa.String(length=20), nullable=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('desconectado','disponible','pausa','en_llamada','tipificando')",
            name=op.f("ck_historial_estados_agente_estado"),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_historial_estados_agente_usuario_id_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historial_estados_agente")),
    )
    with op.batch_alter_table("historial_estados_agente", schema=None) as batch_op:
        batch_op.create_index(
            "ix_historial_estados_agente_usuario_id_inicio", ["usuario_id", "inicio"], unique=False
        )

    op.create_table(
        "campana_agentes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_campana_agentes_campana_id_campanas"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_campana_agentes_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campana_agentes")),
        sa.UniqueConstraint("campana_id", "usuario_id", name=op.f("uq_campana_agentes_campana_id")),
    )
    with op.batch_alter_table("campana_agentes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_campana_agentes_usuario_id"), ["usuario_id"], unique=False
        )

    op.create_table(
        "intentos_contacto",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=True),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=True),
        sa.Column("tipo_campana", sa.String(length=20), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("iniciado_por", sa.String(length=10), nullable=False),
        sa.Column("telefono_id", sa.Integer(), nullable=True),
        sa.Column("momento", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contacto_directo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("resultado", sa.String(length=20), nullable=True),
        sa.Column("politica_version", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canal IN ('voz','whatsapp_mensaje','whatsapp_llamada')",
            name=op.f("ck_intentos_contacto_canal"),
        ),
        sa.CheckConstraint(
            "iniciado_por IN ('empresa','cliente')", name=op.f("ck_intentos_contacto_iniciado_por")
        ),
        sa.CheckConstraint(
            "resultado IS NULL OR resultado IN ('contactado','no_contesta','numero_errado','promesa_pago','venta','rechazo','volver_a_llamar')",
            name=op.f("ck_intentos_contacto_resultado"),
        ),
        sa.CheckConstraint(
            "tipo_campana IN ('venta','cobranza')", name=op.f("ck_intentos_contacto_tipo_campana")
        ),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_intentos_contacto_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_intentos_contacto_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["cliente_id"], ["clientes.id"], name=op.f("fk_intentos_contacto_cliente_id_clientes")
        ),
        sa.ForeignKeyConstraint(
            ["telefono_id"],
            ["telefonos.id"],
            name=op.f("fk_intentos_contacto_telefono_id_telefonos"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intentos_contacto")),
    )
    with op.batch_alter_table("intentos_contacto", schema=None) as batch_op:
        batch_op.create_index(
            "ix_intentos_contacto_cliente_id_momento", ["cliente_id", "momento"], unique=False
        )

    op.create_table(
        "llamadas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=False),
        sa.Column("telefono_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("canal", sa.String(length=20), server_default="voz", nullable=False),
        sa.Column("direccion", sa.String(length=10), server_default="saliente", nullable=False),
        sa.Column("call_sid", sa.String(length=64), nullable=False),
        sa.Column("call_sid_cliente", sa.String(length=64), nullable=True),
        sa.Column("estado", sa.String(length=15), nullable=False),
        sa.Column("motivos_bloqueo", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("intento_contacto_id", sa.Integer(), nullable=True),
        sa.Column("iniciada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contestada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duracion_segundos", sa.Integer(), nullable=True),
        sa.CheckConstraint("canal IN ('voz','whatsapp_llamada')", name=op.f("ck_llamadas_canal")),
        sa.CheckConstraint(
            "direccion IN ('saliente','entrante')", name=op.f("ck_llamadas_direccion")
        ),
        sa.CheckConstraint(
            "estado IN ('iniciando','sonando','en_curso','completada','ocupado','no_contesta','fallida','cancelada','bloqueada')",
            name=op.f("ck_llamadas_estado"),
        ),
        sa.CheckConstraint(
            "duracion_segundos IS NULL OR duracion_segundos >= 0", name=op.f("ck_llamadas_duracion")
        ),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_llamadas_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["intento_contacto_id"],
            ["intentos_contacto.id"],
            name=op.f("fk_llamadas_intento_contacto_id_intentos_contacto"),
        ),
        sa.ForeignKeyConstraint(
            ["telefono_id"], ["telefonos.id"], name=op.f("fk_llamadas_telefono_id_telefonos")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_llamadas_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llamadas")),
        sa.UniqueConstraint("call_sid", name=op.f("uq_llamadas_call_sid")),
        sa.UniqueConstraint("call_sid_cliente", name=op.f("uq_llamadas_call_sid_cliente")),
    )
    with op.batch_alter_table("llamadas", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_llamadas_campana_cliente_id"), ["campana_cliente_id"], unique=False
        )
        batch_op.create_index(
            "ix_llamadas_usuario_id_estado", ["usuario_id", "estado"], unique=False
        )

    op.create_table(
        "estados_agente",
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(length=15), nullable=False),
        sa.Column("desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo_pausa", sa.String(length=20), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('desconectado','disponible','pausa','en_llamada','tipificando')",
            name=op.f("ck_estados_agente_estado"),
        ),
        sa.CheckConstraint(
            "motivo_pausa IS NULL OR motivo_pausa IN ('descanso','almuerzo','capacitacion','reunion','otro')",
            name=op.f("ck_estados_agente_motivo_pausa"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_estados_agente_llamada_id_llamadas")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_estados_agente_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("usuario_id", name=op.f("pk_estados_agente")),
    )
    op.create_table(
        "eventos_llamada",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llamada_id", sa.Integer(), nullable=False),
        sa.Column("call_sid", sa.String(length=64), nullable=False),
        sa.Column("estado_proveedor", sa.String(length=20), nullable=False),
        sa.Column("secuencia", sa.Integer(), server_default="0", nullable=False),
        sa.Column("datos", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["llamada_id"],
            ["llamadas.id"],
            name=op.f("fk_eventos_llamada_llamada_id_llamadas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eventos_llamada")),
        sa.UniqueConstraint(
            "call_sid", "estado_proveedor", "secuencia", name=op.f("uq_eventos_llamada_call_sid")
        ),
    )
    with op.batch_alter_table("eventos_llamada", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_eventos_llamada_llamada_id"), ["llamada_id"], unique=False
        )

    op.create_table(
        "grabaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llamada_id", sa.Integer(), nullable=False),
        sa.Column("recording_sid", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("duracion_segundos", sa.Integer(), nullable=True),
        sa.Column("canales", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_grabaciones_llamada_id_llamadas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grabaciones")),
        sa.UniqueConstraint("recording_sid", name=op.f("uq_grabaciones_recording_sid")),
    )
    with op.batch_alter_table("grabaciones", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_grabaciones_llamada_id"), ["llamada_id"], unique=False)

    op.create_table(
        "tipificaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("origen", sa.String(length=10), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("resultado", sa.String(length=20), nullable=False),
        sa.Column("contacto_directo", sa.Boolean(), nullable=False),
        sa.Column("observacion", sa.String(length=1000), nullable=True),
        sa.Column("volver_a_llamar_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canal IN ('voz','whatsapp_mensaje','whatsapp_llamada')",
            name=op.f("ck_tipificaciones_canal"),
        ),
        sa.CheckConstraint(
            "origen <> 'agente' OR usuario_id IS NOT NULL",
            name=op.f("ck_tipificaciones_agente_requiere_usuario"),
        ),
        sa.CheckConstraint(
            "origen IN ('agente','agente_ia','sistema')", name=op.f("ck_tipificaciones_origen")
        ),
        sa.CheckConstraint(
            "resultado IN ('contactado','no_contesta','numero_errado','promesa_pago','venta','rechazo','volver_a_llamar')",
            name=op.f("ck_tipificaciones_resultado"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_tipificaciones_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_tipificaciones_llamada_id_llamadas")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_tipificaciones_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tipificaciones")),
        sa.UniqueConstraint("llamada_id", name=op.f("uq_tipificaciones_llamada_id")),
    )
    with op.batch_alter_table("tipificaciones", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tipificaciones_campana_cliente_id"), ["campana_cliente_id"], unique=False
        )

    op.create_table(
        "promesas_pago",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipificacion_id", sa.Integer(), nullable=False),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=False),
        sa.Column("monto", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("fecha_pago", sa.Date(), nullable=False),
        sa.Column("numero_cuotas", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "descuento_porcentaje",
            sa.Numeric(precision=5, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("estado", sa.String(length=12), server_default="vigente", nullable=False),
        sa.Column("origen", sa.String(length=10), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('vigente','cumplida','incumplida','anulada')",
            name=op.f("ck_promesas_pago_estado"),
        ),
        sa.CheckConstraint(
            "descuento_porcentaje BETWEEN 0 AND 100", name=op.f("ck_promesas_pago_descuento")
        ),
        sa.CheckConstraint("monto > 0", name=op.f("ck_promesas_pago_monto")),
        sa.CheckConstraint("numero_cuotas BETWEEN 1 AND 36", name=op.f("ck_promesas_pago_cuotas")),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_promesas_pago_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["tipificacion_id"],
            ["tipificaciones.id"],
            name=op.f("fk_promesas_pago_tipificacion_id_tipificaciones"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promesas_pago")),
        sa.UniqueConstraint("tipificacion_id", name=op.f("uq_promesas_pago_tipificacion_id")),
    )
    with op.batch_alter_table("promesas_pago", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_promesas_pago_campana_cliente_id"), ["campana_cliente_id"], unique=False
        )

    op.create_table(
        "ventas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipificacion_id", sa.Integer(), nullable=False),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=False),
        sa.Column("producto", sa.String(length=120), nullable=False),
        sa.Column("valor", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("unidades", sa.Integer(), server_default="1", nullable=False),
        sa.Column("origen", sa.String(length=10), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("unidades >= 1", name=op.f("ck_ventas_unidades")),
        sa.CheckConstraint("valor > 0", name=op.f("ck_ventas_valor")),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_ventas_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["tipificacion_id"],
            ["tipificaciones.id"],
            name=op.f("fk_ventas_tipificacion_id_tipificaciones"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas")),
        sa.UniqueConstraint("tipificacion_id", name=op.f("uq_ventas_tipificacion_id")),
    )
    with op.batch_alter_table("ventas", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ventas_campana_cliente_id"), ["campana_cliente_id"], unique=False
        )


def _crear_tickets_ws() -> None:
    op.create_table(
        "tickets_ws",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_hash", sa.String(length=64), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sesion_expira_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_tickets_ws_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets_ws")),
        sa.UniqueConstraint("ticket_hash", name=op.f("uq_tickets_ws_ticket_hash")),
    )


def downgrade() -> None:
    op.drop_table("tickets_ws")
    with op.batch_alter_table("ventas", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ventas_campana_cliente_id"))

    op.drop_table("ventas")
    with op.batch_alter_table("promesas_pago", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_promesas_pago_campana_cliente_id"))

    op.drop_table("promesas_pago")
    with op.batch_alter_table("tipificaciones", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tipificaciones_campana_cliente_id"))

    op.drop_table("tipificaciones")
    with op.batch_alter_table("grabaciones", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_grabaciones_llamada_id"))

    op.drop_table("grabaciones")
    with op.batch_alter_table("eventos_llamada", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eventos_llamada_llamada_id"))

    op.drop_table("eventos_llamada")
    op.drop_table("estados_agente")
    with op.batch_alter_table("llamadas", schema=None) as batch_op:
        batch_op.drop_index("ix_llamadas_usuario_id_estado")
        batch_op.drop_index(batch_op.f("ix_llamadas_campana_cliente_id"))

    op.drop_table("llamadas")
    with op.batch_alter_table("intentos_contacto", schema=None) as batch_op:
        batch_op.drop_index("ix_intentos_contacto_cliente_id_momento")

    op.drop_table("intentos_contacto")
    with op.batch_alter_table("campana_agentes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_campana_agentes_usuario_id"))

    op.drop_table("campana_agentes")
    with op.batch_alter_table("historial_estados_agente", schema=None) as batch_op:
        batch_op.drop_index("ix_historial_estados_agente_usuario_id_inicio")

    op.drop_table("historial_estados_agente")
    with op.batch_alter_table("campana_clientes", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_campana_clientes_ultimo_resultado"), type_="check")
        batch_op.drop_constraint(
            batch_op.f("fk_campana_clientes_reservado_por_usuarios"), type_="foreignkey"
        )
        batch_op.drop_index("ix_campana_clientes_reservado_por")
        batch_op.drop_index("ix_campana_clientes_campana_id_estado")
        batch_op.drop_column("ultima_gestion_en")
        batch_op.drop_column("ultimo_resultado")
        batch_op.drop_column("reservado_hasta")
        batch_op.drop_column("reservado_por")
