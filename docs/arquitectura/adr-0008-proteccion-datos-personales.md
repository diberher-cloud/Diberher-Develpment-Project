# ADR-0008: Protección de datos personales (Ley 1581/2012, Ley 1266/2008, RNE)

- Estado: aceptado
- Fecha: 2026-10-23

## Contexto
La plataforma trata datos personales (nombre, documento, teléfonos, email) y, en cobranza, información
financiera (saldos, mora). La Ley 1581 exige finalidad, autorización, seguridad, acceso restringido y
atención de derechos del titular; la Ley 1266 (mod. Ley 2157/2021) regula la información financiera y su
reporte a centrales de riesgo; el RNE de la CRC impide llamadas comerciales/publicitarias a números inscritos.

## Decisión
1. **Finalidad por tipo de campaña** (`venta` | `cobranza`): las exclusiones tienen `aplica_a`
   (`venta`, `cobranza`, `todas`). El RNE aplica a `venta` (comercial/publicitario). Una solicitud del
   titular de no ser contactado se registra con `motivo=solicitud_titular` y el `aplica_a` que indique el
   área legal.
2. **Minimización**: solo se importan columnas conocidas + `datos_adicionales` (texto, con límite de
   claves y tamaño). No se importan datos sensibles (salud, etc.).
3. **Control de acceso**: los agentes solo verán clientes de campañas a las que están asignados (fase 2);
   en fase 1 los agentes no acceden a listados de clientes.
4. **Auditoría** (`auditoria`): login, importaciones, cambios de políticas/festivos/exclusiones, gestión de
   usuarios; fase 2: acceso a ficha y a grabaciones. Sin datos personales en el detalle salvo ids.
5. **Grabaciones** con aviso al inicio de la llamada y acceso solo por backend autenticado (fase 2).
6. **Logs** sin documentos ni teléfonos completos (enmascarar: `+57300****567`).
7. **La plataforma no reporta a centrales de riesgo**; si en el futuro lo hiciera, debe implementar la
   comunicación previa al titular de la Ley 1266 (fuera de alcance).
8. **Retención** configurable y borrado/anonimización de bases de campañas finalizadas (fase 5; política
   a definir con el cliente).
9. Cifrado en tránsito (TLS) y en reposo a nivel de disco/servicio gestionado en producción.

## Alternativas consideradas
- Cifrado a nivel de columna para documento/teléfono: complica búsquedas y dedupe; se reconsiderará
  según la evaluación de riesgos del cliente.

## Consecuencias
- + Trazabilidad ante requerimientos de la SIC.
- − Los procedimientos de atención a titulares (consulta, rectificación, supresión) requieren pantallas
  propias (fase 4-5).
