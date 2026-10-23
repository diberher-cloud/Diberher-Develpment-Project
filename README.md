# Diberher Development Project

Repositorio preparado para desarrollar con un **equipo de agentes de IA** en Claude Code.

## Cómo funciona

```
                 ┌──────────────────────────┐
  usuario ──────▶│ Orquestador (/equipo)    │
                 └────────────┬─────────────┘
                              ▼
                        arquitecto  ── plan + contratos + ADR
                              ▼
                  backend  ‖  frontend  (en paralelo)
                              ▼
                             qa ◀──────┐  fallos → backend/frontend
                              ▼        │
                           revisor ────┘  cambios requeridos
                              ▼
                        documentacion
```

Cada rol es un subagente en `.claude/agents/<nombre>.md` con:
- `description`: cuándo usarlo (el orquestador lo lee para decidir a quién delegar),
- `tools`: herramientas permitidas (p. ej. el revisor no tiene `Edit`/`Write`),
- `model`: `opus` para razonamiento (arquitecto, revisor), `sonnet` para implementar, `haiku` para documentación,
- el cuerpo del archivo: su prompt de sistema con responsabilidades, límites y formato de salida.

## Uso

```bash
# Funcionalidad completa con todo el equipo
/equipo Añadir registro de usuarios con email y contraseña

# Llamar a un rol concreto
> Usa el subagente revisor para revisar mis cambios
> @qa escribe tests para src/auth/

# Ver o editar agentes
/agents
```

## Personalizar
- Cambia el modelo de un rol editando `model:` (`opus`, `sonnet`, `haiku` o `inherit`).
- Restringe o amplía herramientas en `tools:`; si omites el campo, el agente hereda todas.
- Añade roles nuevos (p. ej. `devops`, `seguridad`) creando otro `.md` en `.claude/agents/` y mencionándolo en el flujo de `.claude/skills/equipo/SKILL.md`.
