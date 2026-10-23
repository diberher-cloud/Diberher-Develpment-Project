# ADR-0001: Monolito modular FastAPI + SPA React + PostgreSQL

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
Proyecto nuevo, equipo pequeño (agentes de IA + orquestador), MVP con 4 módulos (campañas/bases,
consola del agente, marcador, supervisión). Stack impuesto: Python/FastAPI, React+TypeScript+Vite,
PostgreSQL, Docker Compose para desarrollo. El volumen esperado de un contact center mediano (decenas a
pocos cientos de agentes) no exige escalado independiente por módulo.

## Decisión
- Un único backend FastAPI (`backend/app`) organizado en **módulos de dominio** (`app/modulos/<modulo>/`)
  con dependencias en una sola dirección: `router → servicio → modelos`; la lógica pura (cumplimiento,
  normalización) no importa nada de FastAPI ni de SQLAlchemy.
- Un frontend SPA (`frontend/`) que consume la API REST versionada `/api/v1`.
- PostgreSQL como única pieza de infraestructura: datos, cola del marcador (fase 3) y bus de eventos
  (`LISTEN/NOTIFY`, ADR-0004).
- El marcador (fase 3) es **el mismo código** ejecutado como otro proceso (`python -m app.marcador`).
- Monorepo: `backend/`, `frontend/`, `docker-compose.yml`, `docs/`.

## Alternativas consideradas
- **Microservicios** (campañas, telefonía, marcador): más despliegues, contratos internos y
  observabilidad distribuida sin beneficio real a este tamaño.
- **Celery + Redis** para tareas: añade dos piezas; la cola en PostgreSQL basta para el ritmo de un
  marcador progresivo (decenas de llamadas por segundo como máximo).
- **Next.js / SSR**: no aporta (aplicación interna autenticada, sin SEO).

## Consecuencias
- + Una sola base de código, transacciones locales, despliegue simple.
- + Los límites entre módulos permiten extraer servicios más adelante si hiciera falta.
- − Hay que vigilar que los módulos no se acoplen (importar solo `servicio` de otros módulos, nunca sus modelos internos de forma directa salvo relaciones ORM declaradas).
- − Si el predictivo (fase 5) exige alta concurrencia, podría requerir Redis o un servicio dedicado.
