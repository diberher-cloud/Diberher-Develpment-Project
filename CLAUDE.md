# Diberher Development Project

## Equipo de agentes

Este repositorio trabaja con un equipo de subagentes definidos en `.claude/agents/`:

| Agente | Rol | Modelo | Puede escribir |
|---|---|---|---|
| `arquitecto` | Diseño, contratos, plan de tareas, ADR | opus | solo `docs/arquitectura/` |
| `backend` | API, lógica de negocio, datos | sonnet | código de servidor y sus tests |
| `frontend` | UI, componentes, integración con la API | sonnet | código de cliente y sus tests |
| `qa` | Diseño y ejecución de tests | sonnet | solo tests y fixtures |
| `revisor` | Revisión de bugs, seguridad y calidad | opus | nada (solo lectura) |
| `documentacion` | README, docs, CHANGELOG | haiku | documentación |

La sesión principal es el **orquestador**: para funcionalidades completas usa `/equipo <tarea>`
(`.claude/skills/equipo/SKILL.md`), que encadena arquitecto → backend/frontend → qa → revisor → documentacion.

## Convenciones
- Idioma de documentación y mensajes de commit: español.
- Decisiones de arquitectura en `docs/arquitectura/adr-NNNN-<titulo>.md`.
- Cambios registrados en `CHANGELOG.md` (sección `[Unreleased]`).
- Ningún cambio de código se da por terminado sin pasar por `qa` y `revisor`.
