"""Agente IA (Fase 2C): configuración por campaña, ofertas, historial, acciones, uso, errores,
instrucciones, arrendamiento de turnos, configuración global y evaluaciones; columnas nuevas en
`promesas_pago` y `ventas`.

Downgrade: se pierden la configuración IA, las ofertas, el historial y la auditoría de acciones de
la IA, y las columnas añadidas a `promesas_pago` (periodicidad, reglas_version) y `ventas`
(oferta_id, descuento_porcentaje, reglas_version). Las tablas de 2B no cambian.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30 19:10:01.781834
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "configuracion_global",
        sa.Column("clave", sa.String(length=40), nullable=False),
        sa.Column("valor", sa.JSON(), nullable=False),
        sa.Column("actualizado_por", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actualizado_por"],
            ["usuarios.id"],
            name=op.f("fk_configuracion_global_actualizado_por_usuarios"),
        ),
        sa.PrimaryKeyConstraint("clave", name=op.f("pk_configuracion_global")),
    )
    op.execute(
        sa.text(
            "INSERT INTO configuracion_global (clave, valor, actualizado_por, actualizado_en) "
            "VALUES ('ia_activa', 'true', NULL, CURRENT_TIMESTAMP)"
        )
    )
    op.create_table(
        "configuracion_ia_campana",
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("modelo", sa.String(length=40), nullable=False),
        sa.Column("esfuerzo", sa.String(length=10), nullable=False),
        sa.Column("prompt_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("tratamiento", sa.String(length=5), server_default="usted", nullable=False),
        sa.Column("instrucciones", sa.Text(), nullable=True),
        sa.Column("verificacion", sa.JSON(), nullable=False),
        sa.Column("reglas", sa.JSON(), nullable=False),
        sa.Column("presupuesto_usd_mensual", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("max_costo_conversacion_usd", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("max_turnos_conversacion", sa.Integer(), server_default="30", nullable=False),
        sa.Column("desactivada_motivo", sa.String(length=12), nullable=True),
        sa.Column("activada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("desactivada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerta_presupuesto_mes", sa.String(length=7), nullable=True),
        sa.Column("actualizado_por", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "desactivada_motivo IS NULL OR desactivada_motivo IN ('manual','presupuesto','errores')",
            name=op.f("ck_configuracion_ia_campana_desactivada_motivo"),
        ),
        sa.CheckConstraint(
            "esfuerzo IN ('low','medium','high','xhigh','max')",
            name=op.f("ck_configuracion_ia_campana_esfuerzo"),
        ),
        sa.CheckConstraint(
            "tratamiento IN ('usted','tu')", name=op.f("ck_configuracion_ia_campana_tratamiento")
        ),
        sa.CheckConstraint(
            "max_costo_conversacion_usd > 0", name=op.f("ck_configuracion_ia_campana_max_costo")
        ),
        sa.CheckConstraint(
            "max_turnos_conversacion BETWEEN 1 AND 200",
            name=op.f("ck_configuracion_ia_campana_max_turnos"),
        ),
        sa.CheckConstraint(
            "presupuesto_usd_mensual >= 0", name=op.f("ck_configuracion_ia_campana_presupuesto")
        ),
        sa.CheckConstraint(
            "prompt_version >= 1", name=op.f("ck_configuracion_ia_campana_prompt_version")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_configuracion_ia_campana_version")),
        sa.ForeignKeyConstraint(
            ["actualizado_por"],
            ["usuarios.id"],
            name=op.f("fk_configuracion_ia_campana_actualizado_por_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_configuracion_ia_campana_campana_id_campanas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("campana_id", name=op.f("pk_configuracion_ia_campana")),
    )
    op.create_table(
        "evaluaciones_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("modo", sa.String(length=8), nullable=False),
        sa.Column("canal", sa.String(length=5), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=True),
        sa.Column("modelo", sa.String(length=40), nullable=True),
        sa.Column("esfuerzo", sa.String(length=10), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("huella", sa.String(length=64), nullable=False),
        sa.Column("patron_casos", sa.String(length=100), nullable=True),
        sa.Column("estado", sa.String(length=12), nullable=False),
        sa.Column("aprobada", sa.Boolean(), nullable=True),
        sa.Column("resumen", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("casos", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("iniciada_por", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("canal IN ('chat','voz')", name=op.f("ck_evaluaciones_ia_canal")),
        sa.CheckConstraint(
            "estado IN ('pendiente','en_curso','completada','fallida')",
            name=op.f("ck_evaluaciones_ia_estado"),
        ),
        sa.CheckConstraint("modo IN ('offline','online')", name=op.f("ck_evaluaciones_ia_modo")),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_evaluaciones_ia_campana_id_campanas"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["iniciada_por"], ["usuarios.id"], name=op.f("fk_evaluaciones_ia_iniciada_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluaciones_ia")),
    )
    with op.batch_alter_table("evaluaciones_ia", schema=None) as batch_op:
        batch_op.create_index(
            "ix_evaluaciones_ia_modo_canal_prompt_version_huella_creado_en",
            ["modo", "canal", "prompt_version", "huella", "creado_en"],
            unique=False,
        )

    op.create_table(
        "ofertas_campana",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=30), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("precio", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "descuento_max_pct",
            sa.Numeric(precision=5, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("max_unidades", sa.Integer(), server_default="1", nullable=False),
        sa.Column("condiciones", sa.String(length=1000), nullable=True),
        sa.Column("activa", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("actualizado_por", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "descuento_max_pct BETWEEN 0 AND 100", name=op.f("ck_ofertas_campana_descuento")
        ),
        sa.CheckConstraint(
            "max_unidades BETWEEN 1 AND 100", name=op.f("ck_ofertas_campana_max_unidades")
        ),
        sa.CheckConstraint("precio > 0", name=op.f("ck_ofertas_campana_precio")),
        sa.ForeignKeyConstraint(
            ["actualizado_por"],
            ["usuarios.id"],
            name=op.f("fk_ofertas_campana_actualizado_por_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"],
            ["campanas.id"],
            name=op.f("fk_ofertas_campana_campana_id_campanas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ofertas_campana")),
        sa.UniqueConstraint("campana_id", "codigo", name=op.f("uq_ofertas_campana_campana_id")),
    )
    with op.batch_alter_table("ofertas_campana", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_ofertas_campana_campana_id"), ["campana_id"], unique=False
        )

    op.create_table(
        "acciones_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("tool_use_id", sa.String(length=64), nullable=False),
        sa.Column("herramienta", sa.String(length=40), nullable=False),
        sa.Column("entrada", sa.JSON(), nullable=False),
        sa.Column("resultado", sa.JSON(), nullable=False),
        sa.Column("es_error", sa.Boolean(), nullable=False),
        sa.Column("codigo_error", sa.String(length=40), nullable=True),
        sa.Column("efecto", sa.String(length=20), nullable=False),
        sa.Column("referencia_tipo", sa.String(length=20), nullable=True),
        sa.Column("referencia_id", sa.Integer(), nullable=True),
        sa.Column("reglas_version", sa.Integer(), nullable=True),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "efecto IN ('ninguno','identidad','tipificacion','promesa','venta','seguimiento','exclusion','autorizacion','derivacion','cierre_pendiente')",
            name=op.f("ck_acciones_ia_efecto"),
        ),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_acciones_ia_exactamente_uno"),
        ),
        sa.CheckConstraint("duracion_ms >= 0", name=op.f("ck_acciones_ia_duracion")),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_acciones_ia_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_acciones_ia_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_acciones_ia_llamada_id_llamadas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_acciones_ia")),
        sa.UniqueConstraint("tool_use_id", name=op.f("uq_acciones_ia_tool_use_id")),
    )
    with op.batch_alter_table("acciones_ia", schema=None) as batch_op:
        batch_op.create_index(
            "ix_acciones_ia_campana_id_creado_en", ["campana_id", "creado_en"], unique=False
        )
        batch_op.create_index(
            "ix_acciones_ia_conversacion_id_id", ["conversacion_id", "id"], unique=False
        )
        batch_op.create_index("ix_acciones_ia_llamada_id_id", ["llamada_id", "id"], unique=False)

    op.create_table(
        "bloqueos_turno_ia",
        sa.Column("clave", sa.String(length=40), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("trabajador", sa.String(length=120), nullable=False),
        sa.Column("adquirido_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_bloqueos_turno_ia_exactamente_uno"),
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_bloqueos_turno_ia_conversacion_id_conversaciones"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"],
            ["llamadas.id"],
            name=op.f("fk_bloqueos_turno_ia_llamada_id_llamadas"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("clave", name=op.f("pk_bloqueos_turno_ia")),
    )
    op.create_table(
        "errores_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=40), nullable=False),
        sa.Column("transitorio", sa.Boolean(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_errores_ia_exactamente_uno"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_errores_ia_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_errores_ia_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_errores_ia_llamada_id_llamadas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_errores_ia")),
    )
    with op.batch_alter_table("errores_ia", schema=None) as batch_op:
        batch_op.create_index(
            "ix_errores_ia_campana_id_creado_en", ["campana_id", "creado_en"], unique=False
        )

    op.create_table(
        "instrucciones_supervisor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("texto", sa.String(length=1000), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aplicada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_instrucciones_supervisor_exactamente_uno"),
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_instrucciones_supervisor_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"],
            ["llamadas.id"],
            name=op.f("fk_instrucciones_supervisor_llamada_id_llamadas"),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name=op.f("fk_instrucciones_supervisor_usuario_id_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instrucciones_supervisor")),
    )
    with op.batch_alter_table("instrucciones_supervisor", schema=None) as batch_op:
        batch_op.create_index(
            "ix_instrucciones_supervisor_conversacion_id_aplicada_en",
            ["conversacion_id", "aplicada_en"],
            unique=False,
        )
        batch_op.create_index(
            "ix_instrucciones_supervisor_llamada_id_aplicada_en",
            ["llamada_id", "aplicada_en"],
            unique=False,
        )

    op.create_table(
        "uso_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("campana_id", sa.Integer(), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False),
        sa.Column("modelo", sa.String(length=40), nullable=False),
        sa.Column("modelo_servido", sa.String(length=40), nullable=False),
        sa.Column("esfuerzo", sa.String(length=10), nullable=False),
        sa.Column("respuesta_id", sa.String(length=80), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("iteracion", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=20), nullable=False),
        sa.Column("stop_categoria", sa.String(length=40), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("costo_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("duracion_ms", sa.Integer(), nullable=False),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canal IN ('voz','whatsapp_mensaje','whatsapp_llamada')", name=op.f("ck_uso_ia_canal")
        ),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_uso_ia_exactamente_uno"),
        ),
        sa.CheckConstraint("costo_usd >= 0", name=op.f("ck_uso_ia_costo")),
        sa.CheckConstraint("input_tokens >= 0", name=op.f("ck_uso_ia_input_tokens")),
        sa.CheckConstraint("iteracion >= 1", name=op.f("ck_uso_ia_iteracion")),
        sa.CheckConstraint("output_tokens >= 0", name=op.f("ck_uso_ia_output_tokens")),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_uso_ia_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_uso_ia_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_uso_ia_llamada_id_llamadas")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uso_ia")),
    )
    with op.batch_alter_table("uso_ia", schema=None) as batch_op:
        batch_op.create_index(
            "ix_uso_ia_campana_id_creado_en", ["campana_id", "creado_en"], unique=False
        )
        batch_op.create_index(
            "ix_uso_ia_conversacion_id_id", ["conversacion_id", "id"], unique=False
        )
        batch_op.create_index("ix_uso_ia_llamada_id_id", ["llamada_id", "id"], unique=False)

    op.create_table(
        "historial_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("llamada_id", sa.Integer(), nullable=True),
        sa.Column("secuencia", sa.Integer(), nullable=False),
        sa.Column("rol", sa.String(length=10), nullable=False),
        sa.Column("tipo", sa.String(length=25), nullable=False),
        sa.Column("contenido", sa.JSON(), nullable=False),
        sa.Column("modelo", sa.String(length=40), nullable=True),
        sa.Column("uso_ia_id", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rol IN ('user','assistant','system')", name=op.f("ck_historial_ia_rol")
        ),
        sa.CheckConstraint(
            "tipo IN ('entradas_cliente','resultados_herramientas','control','intervencion','respuesta','contexto','instruccion','correccion','vuelta_ia')",
            name=op.f("ck_historial_ia_tipo"),
        ),
        sa.CheckConstraint(
            "(conversacion_id IS NULL) <> (llamada_id IS NULL)",
            name=op.f("ck_historial_ia_exactamente_uno"),
        ),
        sa.CheckConstraint("secuencia >= 1", name=op.f("ck_historial_ia_secuencia")),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_historial_ia_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["llamada_id"], ["llamadas.id"], name=op.f("fk_historial_ia_llamada_id_llamadas")
        ),
        sa.ForeignKeyConstraint(
            ["uso_ia_id"], ["uso_ia.id"], name=op.f("fk_historial_ia_uso_ia_id_uso_ia")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historial_ia")),
        sa.UniqueConstraint(
            "conversacion_id", "secuencia", name=op.f("uq_historial_ia_conversacion_id")
        ),
        sa.UniqueConstraint("llamada_id", "secuencia", name=op.f("uq_historial_ia_llamada_id")),
    )
    op.create_table(
        "promesa_cuotas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("promesa_id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("monto", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint("monto > 0", name=op.f("ck_promesa_cuotas_monto")),
        sa.CheckConstraint("numero >= 1", name=op.f("ck_promesa_cuotas_numero")),
        sa.ForeignKeyConstraint(
            ["promesa_id"],
            ["promesas_pago.id"],
            name=op.f("fk_promesa_cuotas_promesa_id_promesas_pago"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promesa_cuotas")),
        sa.UniqueConstraint("promesa_id", "numero", name=op.f("uq_promesa_cuotas_promesa_id")),
    )
    with op.batch_alter_table("promesas_pago", schema=None) as batch_op:
        batch_op.add_column(sa.Column("periodicidad", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("reglas_version", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_promesas_pago_periodicidad"),
            "periodicidad IS NULL OR periodicidad IN ('unica','semanal','quincenal','mensual')",
        )

    with op.batch_alter_table("ventas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("oferta_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "descuento_porcentaje",
                sa.Numeric(precision=5, scale=2),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("reglas_version", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_ventas_oferta_id_ofertas_campana"),
            "ofertas_campana",
            ["oferta_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            op.f("ck_ventas_descuento"), "descuento_porcentaje BETWEEN 0 AND 100"
        )


def downgrade() -> None:
    with op.batch_alter_table("ventas", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_ventas_descuento"), type_="check")
        batch_op.drop_constraint(
            batch_op.f("fk_ventas_oferta_id_ofertas_campana"), type_="foreignkey"
        )
        batch_op.drop_column("reglas_version")
        batch_op.drop_column("descuento_porcentaje")
        batch_op.drop_column("oferta_id")

    with op.batch_alter_table("promesas_pago", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_promesas_pago_periodicidad"), type_="check")
        batch_op.drop_column("reglas_version")
        batch_op.drop_column("periodicidad")

    op.drop_table("promesa_cuotas")
    op.drop_table("historial_ia")
    with op.batch_alter_table("uso_ia", schema=None) as batch_op:
        batch_op.drop_index("ix_uso_ia_llamada_id_id")
        batch_op.drop_index("ix_uso_ia_conversacion_id_id")
        batch_op.drop_index("ix_uso_ia_campana_id_creado_en")

    op.drop_table("uso_ia")
    with op.batch_alter_table("instrucciones_supervisor", schema=None) as batch_op:
        batch_op.drop_index("ix_instrucciones_supervisor_llamada_id_aplicada_en")
        batch_op.drop_index("ix_instrucciones_supervisor_conversacion_id_aplicada_en")

    op.drop_table("instrucciones_supervisor")
    with op.batch_alter_table("errores_ia", schema=None) as batch_op:
        batch_op.drop_index("ix_errores_ia_campana_id_creado_en")

    op.drop_table("errores_ia")
    op.drop_table("bloqueos_turno_ia")
    with op.batch_alter_table("acciones_ia", schema=None) as batch_op:
        batch_op.drop_index("ix_acciones_ia_llamada_id_id")
        batch_op.drop_index("ix_acciones_ia_conversacion_id_id")
        batch_op.drop_index("ix_acciones_ia_campana_id_creado_en")

    op.drop_table("acciones_ia")
    with op.batch_alter_table("ofertas_campana", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ofertas_campana_campana_id"))

    op.drop_table("ofertas_campana")
    with op.batch_alter_table("evaluaciones_ia", schema=None) as batch_op:
        batch_op.drop_index("ix_evaluaciones_ia_modo_canal_prompt_version_huella_creado_en")

    op.drop_table("evaluaciones_ia")
    op.drop_table("configuracion_ia_campana")
    op.drop_table("configuracion_global")
