# ADR-0010: Proveedor de WhatsApp — Twilio (mensajería y WhatsApp Business Calling)

- Estado: aceptado (implementación en subfases 2B, 2D y 2E)
- Fecha: 2026-10-23

## Contexto
La Fase 2 incorpora WhatsApp en tres usos:
1. **Mensajería** inbound y outbound: plantillas aprobadas por Meta para iniciar conversaciones,
   conversación libre dentro de la ventana de atención de 24 h, opt-in/opt-out.
2. **Llamadas de voz por WhatsApp** (WhatsApp Business Calling), salientes y entrantes, atendidas por
   agentes humanos desde el mismo softphone del navegador que ya usa Twilio Voice (ADR-0003).
3. Los chats los atiende un agente de IA (ADR-0014/0015); el proveedor solo transporta mensajes.

Hay que elegir entre usar Twilio como proveedor (BSP) de WhatsApp o integrar directamente la
**WhatsApp Cloud API de Meta**. Investigación (búsquedas web, octubre de 2026; fuentes al final):

| Aspecto | Twilio (BSP) | Meta Cloud API directo |
|---|---|---|
| Mensajería y plantillas | Programmable Messaging + Content API (`ContentSid` `HX…`); estado de aprobación consultable y, desde jul-2026, notificado por Event Streams | Graph API (`/messages`, `/message_templates`) |
| Webhooks | Form-urlencoded, firmados con `X-Twilio-Signature` (HMAC-SHA1 con el Auth Token), el **mismo mecanismo que ya validamos para voz** | JSON, firmados con `X-Hub-Signature-256` (HMAC-SHA256 con el App Secret) + verificación `hub.challenge` |
| Llamadas WhatsApp | **GA desde el 15-jul-2025 en Programmable Voice**. Salientes con `<Dial><WhatsApp>` (TwiML) y caller ID `whatsapp:+57…`; entrantes llegan a la TwiML App del sender. Se puentea con `<Client>` al softphone del agente **sin infraestructura nueva** | La empresa debe operar su propio stack WebRTC: intercambio SDP (offer/answer), ICE/DTLS, STUN/TURN, pre-accept en 30-60 s, y puentear el audio con el navegador del agente |
| Disponibilidad de llamadas en Colombia | Salientes disponibles en todos los países de Cloud API excepto EE. UU., Canadá, Egipto, Nigeria, Turquía y Vietnam → **Colombia incluida**; entrantes en todos los países de Cloud API | Igual (la restricción es de Meta) |
| Requisitos de llamadas salientes | Permiso explícito del usuario (plantilla/mensaje interactivo de solicitud de permiso de llamada, enviado dentro de una conversación); límite de mensajería de Meta ≥ 2 000 conversaciones iniciadas por la empresa/24 h (en la práctica, **verificación del negocio en Meta**) | Igual |
| Precio | Tarifa de Meta sin margen **+ US$0,005 por mensaje** (entrante y saliente) de Twilio; llamadas por minuto según tarifa Twilio/Meta | Solo tarifa de Meta |
| Esfuerzo | Bajo: mismo SDK (`twilio`), mismas credenciales, misma validación de firma, mismo softphone | Alto en llamadas (servidor de medios WebRTC); medio en mensajería |

Tarifas de Meta para Colombia (fuentes secundarias, confirmar en la tabla oficial): marketing
≈ US$0,0125 por mensaje entregado; utility y authentication ≈ US$0,0008. Desde el **1-oct-2026** Meta
cobra también los mensajes de servicio y las plantillas utility dentro de la ventana de 24 h (las
fuentes indican 1 000 mensajes de servicio gratuitos al mes por número). Desde abril de 2026 Meta
factura en COP. Los límites de mensajería son por **portafolio de negocio** (desde el 7-oct-2025),
con ascenso automático de nivel según calidad y uso.

Política de Meta relevante: desde el 15-ene-2026 los términos de WhatsApp Business prohíben
distribuir **asistentes de IA de propósito general** por la API; los asistentes de IA de una empresa
para atención/servicio de sus propios clientes siguen permitidos. Nuestro agente IA es de este
segundo tipo (cobranza y venta de la propia empresa, herramientas acotadas).

## Decisión
1. **Twilio** es el proveedor de WhatsApp (mensajería y llamadas), igual que de voz PSTN.
2. **Puerto/adaptador** en `app/integraciones/whatsapp/`:
   ```python
   class ProveedorWhatsApp(Protocol):
       nombre: str                                   # "twilio" | "falso"
       def enviar_texto(self, *, origen: str, destino: str, texto: str,
                        url_estado: str) -> EnvioResultado: ...        # solo dentro de la ventana
       def enviar_plantilla(self, *, origen: str, destino: str, plantilla_ref: str,
                            variables: dict[str, str], url_estado: str) -> EnvioResultado: ...
       def listar_plantillas(self) -> list[PlantillaRemota]: ...       # Content API + aprobación
       def validar_firma(self, url: str, params: Mapping[str, str], firma: str) -> bool: ...
       def parsear_entrante(self, params: Mapping[str, str]) -> MensajeEntrante: ...
       def parsear_estado(self, params: Mapping[str, str]) -> EstadoMensaje: ...
   ```
   Implementaciones: `ProveedorWhatsAppTwilio` (SDK `twilio`) y `ProveedorWhatsAppFalso` (memoria; tests
   y desarrollo sin credenciales). Selección por `WHATSAPP_PROVEEDOR=twilio|falso`. Los tipos
   (`MensajeEntrante`, `EstadoMensaje`, …) son **neutros**: no exponen nombres de campos de Twilio al
   dominio, para que una futura `ProveedorWhatsAppMeta` sea un adaptador más.
3. **Llamadas WhatsApp** (2E) se implementan en el módulo `telefonia` existente: el TwiML saliente
   responde `<Dial callerId="whatsapp:+57…"><WhatsApp>whatsapp:+57…</WhatsApp></Dial>` cuando el
   canal pedido es `whatsapp_llamada`; las entrantes llegan a un Voice URL propio. `ProveedorTelefonia`
   no cambia de interfaz.
4. La **validación de firma** de Twilio se implementa una sola vez como función pura
   (`app/integraciones/twilio_firma.py`) y la usan voz y WhatsApp (ADR-0013).
5. Se registra el sender de WhatsApp con un número colombiano (+57) bajo el portafolio de negocio
   verificado del cliente; un solo sender en la Fase 2 (`WHATSAPP_NUMERO_EMPRESA`).

## Alternativas consideradas
- **Meta Cloud API directo**: más barato (sin los US$0,005/mensaje) y acceso más temprano a novedades
  de Meta; descartado por ahora porque las llamadas exigirían operar un servidor de medios WebRTC y
  puentearlo con el navegador del agente (componente nuevo, difícil de probar sin credenciales), y
  porque duplica credenciales, firma y operación. Revisable por coste cuando el volumen lo justifique:
  la interfaz `ProveedorWhatsApp` lo permite sin tocar el dominio (las llamadas sí exigirían un
  adaptador de medios).
- **Otro BSP (360dialog, Gupshup, Infobip…)**: precios competitivos, pero añade un segundo proveedor
  sin resolver las llamadas mejor que Twilio.
- **Twilio Flex / Conversations**: acelera la bandeja de agentes, pero acopla producto y coste
  (mismo motivo que ADR-0003).

## Consecuencias
- + Un solo proveedor, un solo mecanismo de firma, un solo softphone para PSTN y WhatsApp.
- + Todo es verificable con `ProveedorWhatsAppFalso` (sin credenciales).
- − Coste adicional de US$0,005 por mensaje (entrante y saliente) frente a Meta directo.
- − Dependemos de que Twilio exponga a tiempo las novedades de Meta (p. ej. nuevos tipos de mensaje de
  permiso de llamada). Las funciones de Business Calling se verifican contra la documentación vigente
  al empezar la subfase 2E.
- − Requisitos externos: verificación del negocio en Meta, sender aprobado, plantillas aprobadas y
  límite de mensajería ≥ 2 000 para llamadas salientes (ver fase-2.md §8).

## Fuentes
- Twilio: [WhatsApp Business Calling (docs)](https://www.twilio.com/docs/voice/whatsapp-business-calling),
  [TwiML `<WhatsApp>`](https://www.twilio.com/docs/voice/twiml/whatsapp),
  [changelog GA 15-jul-2025](https://www.twilio.com/en-us/changelog/whatsapp_business_calling_available),
  [guía Business Calling](https://www.twilio.com/en-us/blog/guide-to-whatsapp-business-calling-voice),
  [aviso de precios oct-2026](https://support.twilio.com/hc/en-us/articles/53100480177819-Notice-Changes-to-WhatsApp-s-Pricing-October-2026),
  [aprobación de plantillas por Event Streams](https://www.twilio.com/en-us/changelog/real-time-whatsapp-template-approval-and-category-updates-via-ev).
- Meta: [precios](https://developers.facebook.com/docs/whatsapp/pricing),
  [límites de mensajería](https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits).
- Secundarias: [respond.io — cambio de precios 2026](https://respond.io/blog/whatsapp-pricing-change-2026.md),
  [Dapta — precios por país](https://dapta.ai/es/blog-posts/precios-whatsapp-business-api/),
  [respond.io — política de chatbots 2026](https://respond.io/blog/whatsapp-chatbot-policy-2026),
  [Customer.io — tarifa Twilio](https://docs.customer.io/accounts/billing/whatsapp-billing/),
  [webrtc.ventures — Calling API con WebRTC](https://webrtc.ventures/2025/11/how-to-integrate-the-whatsapp-business-calling-api-with-webrtc-to-enable-customer-voice-calls/).
