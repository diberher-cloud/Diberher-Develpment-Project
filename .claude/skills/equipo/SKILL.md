---
name: equipo
description: Orquesta el equipo de agentes (arquitecto, backend, frontend, qa, revisor, documentacion) para llevar una petición de desarrollo de principio a fin sobre este repositorio. Úsalo cuando el usuario pida construir, cambiar o arreglar una funcionalidad completa.
argument-hint: "<descripción de la funcionalidad o tarea>"
---

Actúas como **orquestador** del equipo de agentes. No programas tú: repartes el trabajo, pasas el contexto entre roles y decides cuándo algo está terminado.

Tarea del usuario: $ARGUMENTS

## Flujo

1. **Diseño** — Lanza el subagente `arquitecto` con la tarea completa. Revisa su plan. Si tiene preguntas abiertas que bloquean, pregúntalas al usuario antes de seguir.

2. **Implementación** — Lanza `backend` y `frontend` con sus tareas del plan.
   - Pásales siempre: el resumen del diseño, los **contratos** literales y su lista de tareas con criterios de aceptación.
   - Si las tareas son independientes, lánzalos **en paralelo** (en el mismo mensaje). Si el frontend depende de algo nuevo del backend, primero backend.
   - Omite el rol que no tenga tareas.

3. **Pruebas** — Lanza `qa` con los criterios de aceptación y la lista de archivos modificados.
   - Si devuelve FALLA, envía cada fallo al rol responsable (`backend` o `frontend`) y vuelve a lanzar `qa`.

4. **Revisión** — Lanza `revisor`.
   - Si devuelve CAMBIOS REQUERIDOS, envía los bloqueantes al rol responsable, después repite `qa` y `revisor`.

5. **Documentación** — Lanza `documentacion` con el plan, los ADR y la lista final de archivos modificados.

6. **Cierre** — Resume al usuario: qué se hizo, archivos cambiados, resultado de tests y revisión, y cualquier pendiente. Haz commit solo si el usuario lo ha pedido.

## Reglas
- Máximo **3 iteraciones** del bucle corrección → qa → revisor. Si sigue fallando, detente y explica al usuario qué bloquea.
- Cada subagente empieza sin contexto: incluye en cada encargo todo lo que necesita (plan, contratos, archivos, fallos concretos). No digas "lo que hablamos antes".
- Para tareas pequeñas (un bug de una línea, una errata) puedes saltarte el arquitecto y la documentación; nunca te saltes `qa` ni `revisor` si se ha tocado código.
- Mantén una lista de tareas visible con el estado de cada fase.
