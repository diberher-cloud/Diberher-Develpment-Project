"""Proveedor de WhatsApp sobre Twilio: SDK `twilio` (mensajes y Content API) y `httpx` para los
medios entrantes (Basic Auth con la API Key, límite de bytes, sin reenviar credenciales a otros
orígenes)."""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.integraciones import twilio_firma
from app.integraciones.whatsapp import parseo
from app.integraciones.whatsapp.proveedor import (
    BotonPlantilla,
    EnvioResultado,
    ErrorProveedorWhatsApp,
    EstadoMensaje,
    MensajeEntrante,
    PlantillaRemota,
)

_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
_REDIRECCIONES = (301, 302, 303, 307, 308)
MAX_SALTOS = 2
_TIPOS_CON_CUERPO = ("twilio/text", "twilio/quick-reply", "twilio/call-to-action", "twilio/card")
_APROBACION = {
    "approved": "aprobada",
    "pending": "pendiente",
    "received": "pendiente",
    "in_review": "pendiente",
    "rejected": "rechazada",
    "paused": "pausada",
    "disabled": "deshabilitada",
}
_CATEGORIAS = ("marketing", "utility", "authentication")


def _orden_variable(clave: str) -> tuple[int, int, str]:
    return (0, int(clave), clave) if clave.isdigit() else (1, 0, clave)


class ProveedorWhatsAppTwilio:
    nombre: Literal["twilio", "falso"] = "twilio"

    def __init__(
        self,
        settings: Settings,
        cliente_rest: Callable[[], Any] | None = None,
        transporte_http: httpx.BaseTransport | None = None,
    ) -> None:
        self._s = settings
        self._cliente_rest = cliente_rest
        self._transporte_http = transporte_http
        self._cliente: Any = None

    # ---- cliente -----------------------------------------------------------------------
    def _cliente_twilio(self) -> Any:
        if self._cliente_rest is not None:
            return self._cliente_rest()
        if self._cliente is None:
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            self._cliente = Client(
                self._s.twilio_api_key_sid,
                self._s.twilio_api_key_secret,
                self._s.twilio_account_sid,
                http_client=TwilioHttpClient(timeout=15),
            )
        return self._cliente

    # ---- envío -------------------------------------------------------------------------
    def _crear(self, **kwargs: Any) -> EnvioResultado:
        import requests
        from twilio.base.exceptions import TwilioRestException

        try:
            mensaje = self._cliente_twilio().messages.create(**kwargs)
        except TwilioRestException as exc:
            transitorio = exc.status in (429, 503)
            raise ErrorProveedorWhatsApp(str(exc.code or exc.status), transitorio) from None
        except requests.ConnectTimeout:
            raise ErrorProveedorWhatsApp("CONEXION", transitorio=True) from None
        except requests.ConnectionError as exc:
            if _fallo_antes_de_conectar(exc):  # DNS / conexión rechazada: el cuerpo no salió
                raise ErrorProveedorWhatsApp("CONEXION", transitorio=True) from None
            raise ErrorProveedorWhatsApp("ENVIO_INCIERTO", transitorio=False) from None
        except Exception:
            # Pudo haberse enviado (p. ej. lectura caída): no se reintenta para no duplicar.
            raise ErrorProveedorWhatsApp("ENVIO_INCIERTO", transitorio=False) from None
        return EnvioResultado(str(mensaje.sid), str(mensaje.status or "queued"))

    def enviar_texto(
        self, *, origen: str, destino: str, texto: str, url_estado: str
    ) -> EnvioResultado:
        return self._crear(
            from_=parseo.PREFIJO + origen,
            to=parseo.PREFIJO + destino,
            body=texto,
            status_callback=url_estado,
        )

    def enviar_plantilla(
        self,
        *,
        origen: str,
        destino: str,
        plantilla_ref: str,
        variables: dict[str, str],
        url_estado: str,
    ) -> EnvioResultado:
        return self._crear(
            from_=parseo.PREFIJO + origen,
            to=parseo.PREFIJO + destino,
            content_sid=plantilla_ref,
            content_variables=json.dumps(variables, ensure_ascii=False),
            status_callback=url_estado,
        )

    # ---- plantillas --------------------------------------------------------------------
    def listar_plantillas(self) -> list[PlantillaRemota]:
        import requests
        from twilio.base.exceptions import TwilioRestException

        try:
            filas = list(self._cliente_twilio().content.v1.content_and_approvals.list())
        except TwilioRestException as exc:
            raise ErrorProveedorWhatsApp(
                "PROVEEDOR_NO_DISPONIBLE", transitorio=exc.status in (429, 503) or exc.status >= 500
            ) from None
        except requests.RequestException:
            raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", transitorio=True) from None
        resultado = []
        for fila in filas:
            plantilla = self._plantilla(fila)
            if plantilla is not None:
                resultado.append(plantilla)
        return resultado

    @staticmethod
    def _plantilla(fila: Any) -> PlantillaRemota | None:
        sid = getattr(fila, "sid", None)
        if not sid:
            return None
        tipos: dict[str, Any] = getattr(fila, "types", None) or {}
        cuerpo = ""
        botones: list[BotonPlantilla] = []
        for nombre in _TIPOS_CON_CUERPO:
            contenido = tipos.get(nombre)
            if isinstance(contenido, dict) and contenido.get("body"):
                cuerpo = str(contenido["body"])
                for accion in contenido.get("actions") or []:
                    botones.append(_boton(accion))
                break
        aprobacion = (getattr(fila, "approval_requests", None) or {}).get("whatsapp") or {}
        estado = _APROBACION.get(str(aprobacion.get("status", "")).lower(), "desconocido")
        categoria = str(aprobacion.get("category", "")).lower()
        variables = sorted((getattr(fila, "variables", None) or {}).keys(), key=_orden_variable)
        motivo = aprobacion.get("rejection_reason") or None
        return PlantillaRemota(
            ref=str(sid),
            nombre=str(getattr(fila, "friendly_name", None) or sid)[:200],
            idioma=str(getattr(fila, "language", None) or "es")[:10],
            categoria=categoria if categoria in _CATEGORIAS else "desconocida",
            estado_aprobacion=estado,
            motivo_rechazo=str(motivo)[:300] if motivo else None,
            cuerpo=cuerpo,
            variables=tuple(str(v) for v in variables),
            botones=tuple(botones),
        )

    # ---- webhooks ----------------------------------------------------------------------
    def validar_firma(
        self, url: str, params: Mapping[str, str | Sequence[str]], firma: str | None
    ) -> bool:
        return twilio_firma.validar_firma(url, params, firma, self._s.twilio_auth_token)

    def parsear_entrante(self, params: Mapping[str, str]) -> MensajeEntrante | None:
        return parseo.parsear_entrante(params)

    def parsear_estado(self, params: Mapping[str, str]) -> EstadoMensaje | None:
        return parseo.parsear_estado(params)

    # ---- medios ------------------------------------------------------------------------
    def url_media_valida(self, url: str) -> bool:
        """Anti-SSRF: https, host `api.twilio.com` sin puerto ni credenciales y ruta EXACTA
        `/2010-04-01/Accounts/<SID propio>/Messages/MM…[/Media/ME…]` (sin `.`/`..`, sin
        codificaciones, sin query ni fragmento, sin caracteres de control)."""
        sid = self._s.twilio_account_sid
        if not sid or not url.startswith("https://api.twilio.com/") or _CONTROL.search(url):
            return False
        try:
            partes = urlsplit(url)
            puerto = partes.port
        except ValueError:
            return False
        if partes.netloc != "api.twilio.com" or puerto is not None:
            return False
        if partes.query or partes.fragment:
            return False
        patron = (
            rf"/2010-04-01/Accounts/{re.escape(sid)}/Messages/MM[A-Za-z0-9]+"
            r"(?:/Media/ME[A-Za-z0-9]+)?"
        )
        return re.fullmatch(patron, partes.path) is not None

    def _redireccion_permitida(self, destino: str) -> bool:
        """Solo https hacia hosts de la lista de medios (`WHATSAPP_HOSTS_MEDIOS`) o la propia
        ruta válida de `api.twilio.com`; sin credenciales, puertos ni caracteres de control."""
        if _CONTROL.search(destino) or not destino.startswith("https://"):
            return False
        try:
            partes = urlsplit(destino)
            puerto = partes.port
        except ValueError:
            return False
        if puerto is not None or "@" in partes.netloc or partes.hostname is None:
            return False
        if partes.hostname == "api.twilio.com":
            return self.url_media_valida(destino)
        return partes.hostname.lower() in self._s.hosts_medios

    def descargar_media(self, url: str, max_bytes: int) -> tuple[str, bytes]:
        if not self.url_media_valida(url):
            raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False)
        credenciales: tuple[str, str] | None = (
            self._s.twilio_api_key_sid,
            self._s.twilio_api_key_secret,
        )
        actual = url
        inicio = time.monotonic()
        try:
            # Sin redirecciones automáticas: cada salto se valida a mano (máx. `MAX_SALTOS`) y
            # las credenciales solo viajan a la ruta válida de api.twilio.com.
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
                transport=self._transporte_http,
            ) as cliente:
                for salto in range(MAX_SALTOS + 1):
                    with cliente.stream("GET", actual, auth=credenciales) as respuesta:
                        if respuesta.status_code in _REDIRECCIONES:
                            destino = urljoin(actual, respuesta.headers.get("location", ""))
                            if salto == MAX_SALTOS or not self._redireccion_permitida(destino):
                                raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", False)
                            actual = destino
                            if not self.url_media_valida(destino):
                                credenciales = None
                            continue
                        return self._leer(respuesta, max_bytes, inicio)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol):
            raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False) from None
        except httpx.HTTPError:
            raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", transitorio=True) from None
        raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False)

    def _leer(self, respuesta: httpx.Response, max_bytes: int, inicio: float) -> tuple[str, bytes]:
        if respuesta.status_code in (404, 410):
            raise ErrorProveedorWhatsApp("MEDIA_NO_DISPONIBLE", transitorio=False)
        if respuesta.status_code == 429 or respuesta.status_code >= 500:
            raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", transitorio=True)
        if respuesta.status_code != 200:
            raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", transitorio=False)
        declarado = respuesta.headers.get("content-length", "")
        if declarado.isdigit() and int(declarado) > max_bytes:
            raise ErrorProveedorWhatsApp("MEDIA_DEMASIADO_GRANDE", transitorio=False)
        limite = self._s.whatsapp_media_duracion_segundos
        trozos: list[bytes] = []
        total = 0
        for trozo in respuesta.iter_bytes():
            trozos.append(trozo)
            total += len(trozo)
            if total > max_bytes:
                raise ErrorProveedorWhatsApp("MEDIA_DEMASIADO_GRANDE", transitorio=False)
            if time.monotonic() - inicio > limite:  # descarga demasiado lenta (slow-loris)
                raise ErrorProveedorWhatsApp("PROVEEDOR_NO_DISPONIBLE", transitorio=True)
        tipo = parseo.tipo_contenido_limpio(respuesta.headers.get("content-type"))
        return tipo, b"".join(trozos)  # una sola copia


def _fallo_antes_de_conectar(exc: BaseException) -> bool:
    """True solo si la causa es un fallo de CONEXIÓN (DNS o rechazo) previo al envío; ante la
    duda (cortes de lectura, resets, protocolo) es False y se trata como envío incierto."""
    from urllib3.exceptions import MaxRetryError, NewConnectionError

    causa = exc.args[0] if exc.args else None
    if isinstance(causa, MaxRetryError):
        causa = causa.reason
    return isinstance(causa, NewConnectionError)  # NameResolutionError es subclase


def _boton(accion: Any) -> BotonPlantilla:
    if not isinstance(accion, dict):
        return BotonPlantilla("otro", "", None)
    texto = str(accion.get("title") or accion.get("text") or "")[:100]
    tipo = str(accion.get("type") or "QUICK_REPLY").upper()
    if tipo == "QUICK_REPLY":
        ident = accion.get("id")
        return BotonPlantilla("respuesta_rapida", texto, str(ident) if ident else None)
    if tipo == "URL":
        return BotonPlantilla("url", texto, None)
    if tipo == "PHONE_NUMBER":
        return BotonPlantilla("telefono", texto, None)
    return BotonPlantilla("otro", texto, None)
