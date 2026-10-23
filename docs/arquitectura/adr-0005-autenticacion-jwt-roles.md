# ADR-0005: Autenticación JWT con roles

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
Tres roles (administrador, supervisor, agente). SPA que llama a una API REST y (fase 3) a un WebSocket.
Hay datos personales y financieros (Ley 1581/1266): un usuario desactivado debe perder acceso de inmediato.

## Decisión
- Login con email + contraseña → JWT **HS256** de acceso, `exp` = `JWT_EXPIRACION_MINUTOS` (por defecto
  480 = un turno). Claims: `sub` (id de usuario como texto), `rol`, `iat`, `exp`.
- Secreto `JWT_SECRETO` por variable de entorno (mínimo 32 caracteres; la app no arranca si falta, salvo
  `ENTORNO=test`).
- En cada petición se **carga el usuario desde BD**: si no existe o `activo=false` → 401. El **rol
  efectivo es el de BD**, no el del token (el claim es informativo para la UI).
- Contraseñas con `bcrypt` (coste 12; en tests se puede bajar por configuración). Mínimo 10 caracteres.
- Autorización por dependencia `requiere_rol("administrador", "supervisor")`.
- Frontend: token en memoria + `sessionStorage` (se pierde al cerrar la pestaña), cabecera
  `Authorization: Bearer`. Ante 401, limpiar sesión y redirigir a `/login`.
- Valores de rol en API y BD: `administrador`, `supervisor`, `agente`.
- El primer administrador se crea por CLI: `python -m app.cli crear-admin --email … --nombre …`
  (contraseña por `ADMIN_PASSWORD` o prompt).

## Alternativas consideradas
- **Refresh tokens / cookies httpOnly**: más seguro frente a XSS; se pospone a fase 2 junto con
  limitación de intentos de login. La carga del usuario por petición ya permite revocar.
- **Sesiones en servidor**: requiere almacén de sesiones; JWT encaja con WebSocket y varios procesos.
- **OIDC/SSO**: fase 5 si el cliente lo pide.

## Consecuencias
- + Revocación inmediata desactivando el usuario.
- − Una consulta extra por petición (barata, por PK).
- − `sessionStorage` es accesible a JavaScript: se mitiga con CSP estricta y sin `dangerouslySetInnerHTML`.
