"""WhatsApp base y bandeja de chat para agentes humanos (Fase 2B)

El downgrade BORRA las exclusiones con `canal` distinto de `todos` o sin `creado_por` (opt-outs
de WhatsApp y de sistema): no caben en el esquema de 0002 (UNIQUE sin canal, `creado_por` NOT NULL).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26 16:40:56.778746
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "latidos_worker",
        sa.Column("trabajador", sa.String(length=80), nullable=False),
        sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_latido", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("trabajador", name=op.f("pk_latidos_worker")),
    )
    op.create_table(
        "trabajos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=60), nullable=False),
        sa.Column("clave_unica", sa.String(length=120), nullable=True),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("estado", sa.String(length=12), nullable=False),
        sa.Column("intentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_intentos", sa.Integer(), server_default="5", nullable=False),
        sa.Column("disponible_desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bloqueado_por", sa.String(length=80), nullable=True),
        sa.Column("ultimo_error", sa.String(length=300), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente','en_proceso','completado','fallido','cancelado')",
            name=op.f("ck_trabajos_estado"),
        ),
        sa.CheckConstraint("max_intentos BETWEEN 1 AND 20", name=op.f("ck_trabajos_max_intentos")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trabajos")),
        sa.UniqueConstraint("clave_unica", name=op.f("uq_trabajos_clave_unica")),
    )
    with op.batch_alter_table("trabajos", schema=None) as batch_op:
        batch_op.create_index(
            "ix_trabajos_estado_disponible_desde", ["estado", "disponible_desde"], unique=False
        )

    op.create_table(
        "plantillas_whatsapp",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_sid", sa.String(length=64), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("idioma", sa.String(length=10), nullable=False),
        sa.Column("categoria", sa.String(length=15), nullable=False),
        sa.Column("estado_aprobacion", sa.String(length=15), nullable=False),
        sa.Column("motivo_rechazo", sa.String(length=300), nullable=True),
        sa.Column("cuerpo", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("botones", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("tiene_boton_baja", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("mapeo_variables", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("finalidad", sa.String(length=10), nullable=True),
        sa.Column("activa", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sincronizada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_por", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "activa = false OR (estado_aprobacion = 'aprobada' AND finalidad IS NOT NULL)",
            name=op.f("ck_plantillas_whatsapp_activa_requiere_aprobada"),
        ),
        sa.CheckConstraint(
            "categoria IN ('marketing','utility','authentication','desconocida')",
            name=op.f("ck_plantillas_whatsapp_categoria"),
        ),
        sa.CheckConstraint(
            "estado_aprobacion IN ('aprobada','pendiente','rechazada','pausada','deshabilitada','eliminada','desconocido')",
            name=op.f("ck_plantillas_whatsapp_estado_aprobacion"),
        ),
        sa.CheckConstraint(
            "finalidad IS NULL OR finalidad IN ('venta','cobranza','todas')",
            name=op.f("ck_plantillas_whatsapp_finalidad"),
        ),
        sa.ForeignKeyConstraint(
            ["actualizado_por"],
            ["usuarios.id"],
            name=op.f("fk_plantillas_whatsapp_actualizado_por_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plantillas_whatsapp")),
        sa.UniqueConstraint("content_sid", name=op.f("uq_plantillas_whatsapp_content_sid")),
    )
    op.create_table(
        "conversaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clave_abierta", sa.String(length=40), nullable=True),
        sa.Column("numero_cliente_e164", sa.String(length=16), nullable=False),
        sa.Column("numero_empresa_e164", sa.String(length=16), nullable=False),
        sa.Column("nombre_perfil", sa.String(length=100), nullable=True),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("campana_id", sa.Integer(), nullable=True),
        sa.Column("campana_cliente_id", sa.Integer(), nullable=True),
        sa.Column("telefono_id", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(length=10), nullable=False),
        sa.Column("atendida_por", sa.String(length=12), nullable=False),
        sa.Column("usuario_asignado_id", sa.Integer(), nullable=True),
        sa.Column("asignada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("iniciada_por", sa.String(length=10), nullable=False),
        sa.Column("intento_contacto_id", sa.Integer(), nullable=True),
        sa.Column("ventana_expira_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_mensaje_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_entrante_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mensajes_sin_leer", sa.Integer(), server_default="0", nullable=False),
        sa.Column("aviso_espera_enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aviso_fuera_franja_enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abierta_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_cierre", sa.String(length=15), nullable=True),
        sa.Column("cerrada_por", sa.Integer(), nullable=True),
        sa.Column("identidad_verificada", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("identidad_intentos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("turnos_ia", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "costo_usd_acumulado",
            sa.Numeric(precision=12, scale=6),
            server_default="0",
            nullable=False,
        ),
        sa.Column("modelo_ia", sa.String(length=40), nullable=True),
        sa.Column("esfuerzo_ia", sa.String(length=10), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("aviso_ia_enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(atendida_por='humano' AND usuario_asignado_id IS NOT NULL) OR (atendida_por<>'humano' AND usuario_asignado_id IS NULL)",
            name=op.f("ck_conversaciones_dueno_coherente"),
        ),
        sa.CheckConstraint(
            "(estado='abierta' AND clave_abierta IS NOT NULL AND cerrada_en IS NULL) OR (estado='cerrada' AND clave_abierta IS NULL AND cerrada_en IS NOT NULL)",
            name=op.f("ck_conversaciones_ciclo_de_vida"),
        ),
        sa.CheckConstraint(
            "atendida_por IN ('sin_asignar','humano','ia')",
            name=op.f("ck_conversaciones_atendida_por"),
        ),
        sa.CheckConstraint(
            "estado IN ('abierta','cerrada')", name=op.f("ck_conversaciones_estado")
        ),
        sa.CheckConstraint(
            "iniciada_por IN ('empresa','cliente')", name=op.f("ck_conversaciones_iniciada_por")
        ),
        sa.CheckConstraint(
            "motivo_cierre IS NULL OR motivo_cierre IN ('agente','supervisor','inactividad','opt_out','sistema')",
            name=op.f("ck_conversaciones_motivo_cierre"),
        ),
        sa.CheckConstraint(
            "campana_cliente_id IS NULL OR (campana_id IS NOT NULL AND cliente_id IS NOT NULL)",
            name=op.f("ck_conversaciones_registro_coherente"),
        ),
        sa.CheckConstraint(
            "mensajes_sin_leer >= 0", name=op.f("ck_conversaciones_mensajes_sin_leer")
        ),
        sa.ForeignKeyConstraint(
            ["campana_cliente_id"],
            ["campana_clientes.id"],
            name=op.f("fk_conversaciones_campana_cliente_id_campana_clientes"),
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_conversaciones_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["cerrada_por"], ["usuarios.id"], name=op.f("fk_conversaciones_cerrada_por_usuarios")
        ),
        sa.ForeignKeyConstraint(
            ["cliente_id"], ["clientes.id"], name=op.f("fk_conversaciones_cliente_id_clientes")
        ),
        sa.ForeignKeyConstraint(
            ["intento_contacto_id"],
            ["intentos_contacto.id"],
            name=op.f("fk_conversaciones_intento_contacto_id_intentos_contacto"),
        ),
        sa.ForeignKeyConstraint(
            ["telefono_id"], ["telefonos.id"], name=op.f("fk_conversaciones_telefono_id_telefonos")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_asignado_id"],
            ["usuarios.id"],
            name=op.f("fk_conversaciones_usuario_asignado_id_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversaciones")),
        sa.UniqueConstraint("clave_abierta", name=op.f("uq_conversaciones_clave_abierta")),
    )
    with op.batch_alter_table("conversaciones", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_conversaciones_campana_cliente_id"), ["campana_cliente_id"], unique=False
        )
        batch_op.create_index(
            "ix_conversaciones_campana_id_estado", ["campana_id", "estado"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conversaciones_cliente_id"), ["cliente_id"], unique=False
        )
        batch_op.create_index(
            "ix_conversaciones_estado_atendida_por", ["estado", "atendida_por"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conversaciones_numero_cliente_e164"),
            ["numero_cliente_e164"],
            unique=False,
        )
        batch_op.create_index(
            "ix_conversaciones_usuario_asignado_id_estado",
            ["usuario_asignado_id", "estado"],
            unique=False,
        )

    op.create_table(
        "autorizaciones_canal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero_e164", sa.String(length=16), nullable=False),
        sa.Column("canal", sa.String(length=10), nullable=False),
        sa.Column("finalidad", sa.String(length=10), nullable=False),
        sa.Column("origen", sa.String(length=12), nullable=False),
        sa.Column("evidencia", sa.String(length=500), nullable=False),
        sa.Column("otorgada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registrada_por", sa.Integer(), nullable=True),
        sa.Column("importacion_id", sa.Integer(), nullable=True),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("clave_vigente", sa.String(length=40), nullable=True),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocada_por", sa.Integer(), nullable=True),
        sa.Column("motivo_revocacion", sa.String(length=12), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("canal IN ('whatsapp')", name=op.f("ck_autorizaciones_canal_canal")),
        sa.CheckConstraint(
            "finalidad IN ('venta','cobranza','todas')",
            name=op.f("ck_autorizaciones_canal_finalidad"),
        ),
        sa.CheckConstraint(
            "motivo_revocacion IS NULL OR motivo_revocacion IN ('opt_out','manual','importacion')",
            name=op.f("ck_autorizaciones_canal_motivo_revocacion"),
        ),
        sa.CheckConstraint(
            "origen IN ('importacion','cliente','agente','agente_ia')",
            name=op.f("ck_autorizaciones_canal_origen"),
        ),
        sa.CheckConstraint(
            "origen NOT IN ('agente','cliente') OR registrada_por IS NOT NULL",
            name=op.f("ck_autorizaciones_canal_origen_requiere_usuario"),
        ),
        sa.CheckConstraint(
            "(revocada_en IS NULL AND clave_vigente IS NOT NULL) OR (revocada_en IS NOT NULL AND clave_vigente IS NULL)",
            name=op.f("ck_autorizaciones_canal_vigencia"),
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_autorizaciones_canal_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["importacion_id"],
            ["importaciones.id"],
            name=op.f("fk_autorizaciones_canal_importacion_id_importaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["registrada_por"],
            ["usuarios.id"],
            name=op.f("fk_autorizaciones_canal_registrada_por_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["revocada_por"],
            ["usuarios.id"],
            name=op.f("fk_autorizaciones_canal_revocada_por_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autorizaciones_canal")),
        sa.UniqueConstraint("clave_vigente", name=op.f("uq_autorizaciones_canal_clave_vigente")),
    )
    with op.batch_alter_table("autorizaciones_canal", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_autorizaciones_canal_numero_e164"), ["numero_e164"], unique=False
        )

    op.create_table(
        "cola_atencion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=False),
        sa.Column("campana_id", sa.Integer(), nullable=True),
        sa.Column("motivo", sa.String(length=25), nullable=False),
        sa.Column("resumen", sa.String(length=500), nullable=True),
        sa.Column("prioridad", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(length=10), nullable=False),
        sa.Column("clave_activa", sa.String(length=20), nullable=True),
        sa.Column("asignada_a", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asignada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cerrada_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "estado IN ('pendiente','asignada','cerrada')", name=op.f("ck_cola_atencion_estado")
        ),
        sa.CheckConstraint(
            "motivo IN ('entrante','sin_campana','liberada','agente_desconectado','supervisor','solicitud_cliente','queja','ia_no_resuelve','identidad_bloqueada','ia_rechazo','ia_max_tokens','ia_iteraciones','ia_stop_inesperado','ia_monto_no_respaldado','ia_error','presupuesto_excedido','ia_desactivada')",
            name=op.f("ck_cola_atencion_motivo"),
        ),
        sa.CheckConstraint("prioridad BETWEEN 1 AND 3", name=op.f("ck_cola_atencion_prioridad")),
        sa.ForeignKeyConstraint(
            ["asignada_a"], ["usuarios.id"], name=op.f("fk_cola_atencion_asignada_a_usuarios")
        ),
        sa.ForeignKeyConstraint(
            ["campana_id"], ["campanas.id"], name=op.f("fk_cola_atencion_campana_id_campanas")
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_cola_atencion_conversacion_id_conversaciones"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cola_atencion")),
        sa.UniqueConstraint("clave_activa", name=op.f("uq_cola_atencion_clave_activa")),
    )
    with op.batch_alter_table("cola_atencion", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_cola_atencion_conversacion_id"), ["conversacion_id"], unique=False
        )
        batch_op.create_index(
            "ix_cola_atencion_estado_prioridad_creado_en",
            ["estado", "prioridad", "creado_en"],
            unique=False,
        )

    op.create_table(
        "mensajes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversacion_id", sa.Integer(), nullable=True),
        sa.Column("numero_cliente_e164", sa.String(length=16), nullable=False),
        sa.Column("direccion", sa.String(length=10), nullable=False),
        sa.Column("autor", sa.String(length=10), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(length=15), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=True),
        sa.Column("plantilla_id", sa.Integer(), nullable=True),
        sa.Column("variables", sa.JSON(), nullable=True),
        sa.Column("media", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("boton_payload", sa.String(length=256), nullable=True),
        sa.Column("boton_texto", sa.String(length=256), nullable=True),
        sa.Column("respuesta_a_proveedor_id", sa.String(length=64), nullable=True),
        sa.Column("proveedor_id", sa.String(length=64), nullable=True),
        sa.Column("idempotencia_clave", sa.String(length=64), nullable=True),
        sa.Column("estado", sa.String(length=10), nullable=False),
        sa.Column("error_codigo", sa.String(length=30), nullable=True),
        sa.Column("programado_para", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entregado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leido_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("procesado_ia_en", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(direccion='entrante' AND autor='cliente' AND estado='recibido') OR (direccion='saliente' AND autor<>'cliente' AND estado<>'recibido')",
            name=op.f("ck_mensajes_direccion_coherente"),
        ),
        sa.CheckConstraint(
            "autor <> 'agente' OR usuario_id IS NOT NULL",
            name=op.f("ck_mensajes_agente_requiere_usuario"),
        ),
        sa.CheckConstraint(
            "autor IN ('cliente','agente','ia','sistema')", name=op.f("ck_mensajes_autor")
        ),
        sa.CheckConstraint(
            "direccion = 'entrante' OR conversacion_id IS NOT NULL",
            name=op.f("ck_mensajes_saliente_con_conversacion"),
        ),
        sa.CheckConstraint(
            "direccion IN ('entrante','saliente')", name=op.f("ck_mensajes_direccion")
        ),
        sa.CheckConstraint(
            "estado IN ('recibido','pendiente','retenido','enviando','enviado','entregado','leido','fallido','cancelado')",
            name=op.f("ck_mensajes_estado"),
        ),
        sa.CheckConstraint(
            "tipo IN ('texto','plantilla','media','boton','no_soportado')",
            name=op.f("ck_mensajes_tipo"),
        ),
        sa.ForeignKeyConstraint(
            ["conversacion_id"],
            ["conversaciones.id"],
            name=op.f("fk_mensajes_conversacion_id_conversaciones"),
        ),
        sa.ForeignKeyConstraint(
            ["plantilla_id"],
            ["plantillas_whatsapp.id"],
            name=op.f("fk_mensajes_plantilla_id_plantillas_whatsapp"),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_mensajes_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mensajes")),
        sa.UniqueConstraint("idempotencia_clave", name=op.f("uq_mensajes_idempotencia_clave")),
        sa.UniqueConstraint("proveedor_id", name=op.f("uq_mensajes_proveedor_id")),
    )
    with op.batch_alter_table("mensajes", schema=None) as batch_op:
        batch_op.create_index(
            "ix_mensajes_conversacion_id_id", ["conversacion_id", "id"], unique=False
        )

    op.create_table(
        "eventos_mensaje",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proveedor_id", sa.String(length=64), nullable=False),
        sa.Column("mensaje_id", sa.Integer(), nullable=True),
        sa.Column("estado_proveedor", sa.String(length=20), nullable=False),
        sa.Column("error_codigo", sa.String(length=30), nullable=True),
        sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mensaje_id"],
            ["mensajes.id"],
            name=op.f("fk_eventos_mensaje_mensaje_id_mensajes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eventos_mensaje")),
        sa.UniqueConstraint(
            "proveedor_id", "estado_proveedor", name=op.f("uq_eventos_mensaje_proveedor_id")
        ),
    )
    with op.batch_alter_table("eventos_mensaje", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_eventos_mensaje_mensaje_id"), ["mensaje_id"], unique=False
        )

    with op.batch_alter_table("campanas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "whatsapp_habilitado", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch_op.add_column(sa.Column("plantilla_inicial_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_campanas_plantilla_inicial_id_plantillas_whatsapp"),
            "plantillas_whatsapp",
            ["plantilla_inicial_id"],
            ["id"],
        )

    with op.batch_alter_table("exclusiones", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("canal", sa.String(length=10), server_default="todos", nullable=False)
        )
        batch_op.add_column(
            sa.Column("origen", sa.String(length=10), server_default="usuario", nullable=False)
        )
        batch_op.add_column(sa.Column("conversacion_id", sa.Integer(), nullable=True))
        batch_op.alter_column("creado_por", existing_type=sa.INTEGER(), nullable=True)
        batch_op.create_check_constraint(
            batch_op.f("ck_exclusiones_canal"), "canal IN ('todos','voz','whatsapp')"
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_exclusiones_origen"), "origen IN ('usuario','sistema','agente_ia')"
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_exclusiones_usuario_requiere_creador"),
            "origen <> 'usuario' OR creado_por IS NOT NULL",
        )
        batch_op.drop_constraint(batch_op.f("uq_exclusiones_numero_e164"), type_="unique")
        batch_op.create_unique_constraint(
            batch_op.f("uq_exclusiones_numero_e164"), ["numero_e164", "aplica_a", "canal"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_exclusiones_conversacion_id_conversaciones"),
            "conversaciones",
            ["conversacion_id"],
            ["id"],
        )

    with op.batch_alter_table("tipificaciones", schema=None) as batch_op:
        batch_op.add_column(sa.Column("conversacion_id", sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            batch_op.f("uq_tipificaciones_conversacion_id"), ["conversacion_id"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_tipificaciones_conversacion_id_conversaciones"),
            "conversaciones",
            ["conversacion_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_tipificaciones_llamada_o_conversacion"),
            "llamada_id IS NULL OR conversacion_id IS NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("tipificaciones", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_tipificaciones_llamada_o_conversacion"), type_="check"
        )
        batch_op.drop_constraint(
            batch_op.f("fk_tipificaciones_conversacion_id_conversaciones"), type_="foreignkey"
        )
        batch_op.drop_constraint(batch_op.f("uq_tipificaciones_conversacion_id"), type_="unique")
        batch_op.drop_column("conversacion_id")

    # Pierde los opt-outs de WhatsApp y los creados por el sistema (ver docstring).
    op.execute("DELETE FROM exclusiones WHERE canal <> 'todos' OR creado_por IS NULL")
    with op.batch_alter_table("exclusiones", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_exclusiones_usuario_requiere_creador"), type_="check"
        )
        batch_op.drop_constraint(batch_op.f("ck_exclusiones_origen"), type_="check")
        batch_op.drop_constraint(batch_op.f("ck_exclusiones_canal"), type_="check")
        batch_op.drop_constraint(
            batch_op.f("fk_exclusiones_conversacion_id_conversaciones"), type_="foreignkey"
        )
        batch_op.drop_constraint(batch_op.f("uq_exclusiones_numero_e164"), type_="unique")
        batch_op.create_unique_constraint(
            batch_op.f("uq_exclusiones_numero_e164"), ["numero_e164", "aplica_a"]
        )
        batch_op.alter_column("creado_por", existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column("conversacion_id")
        batch_op.drop_column("origen")
        batch_op.drop_column("canal")

    with op.batch_alter_table("campanas", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_campanas_plantilla_inicial_id_plantillas_whatsapp"), type_="foreignkey"
        )
        batch_op.drop_column("plantilla_inicial_id")
        batch_op.drop_column("whatsapp_habilitado")

    with op.batch_alter_table("eventos_mensaje", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eventos_mensaje_mensaje_id"))

    op.drop_table("eventos_mensaje")
    with op.batch_alter_table("mensajes", schema=None) as batch_op:
        batch_op.drop_index("ix_mensajes_conversacion_id_id")

    op.drop_table("mensajes")
    with op.batch_alter_table("cola_atencion", schema=None) as batch_op:
        batch_op.drop_index("ix_cola_atencion_estado_prioridad_creado_en")
        batch_op.drop_index(batch_op.f("ix_cola_atencion_conversacion_id"))

    op.drop_table("cola_atencion")
    with op.batch_alter_table("autorizaciones_canal", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_autorizaciones_canal_numero_e164"))

    op.drop_table("autorizaciones_canal")
    with op.batch_alter_table("conversaciones", schema=None) as batch_op:
        batch_op.drop_index("ix_conversaciones_usuario_asignado_id_estado")
        batch_op.drop_index(batch_op.f("ix_conversaciones_numero_cliente_e164"))
        batch_op.drop_index("ix_conversaciones_estado_atendida_por")
        batch_op.drop_index(batch_op.f("ix_conversaciones_cliente_id"))
        batch_op.drop_index("ix_conversaciones_campana_id_estado")
        batch_op.drop_index(batch_op.f("ix_conversaciones_campana_cliente_id"))

    op.drop_table("conversaciones")
    op.drop_table("plantillas_whatsapp")
    with op.batch_alter_table("trabajos", schema=None) as batch_op:
        batch_op.drop_index("ix_trabajos_estado_disponible_desde")

    op.drop_table("trabajos")
    op.drop_table("latidos_worker")
