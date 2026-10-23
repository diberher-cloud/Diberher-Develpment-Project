import jwt
from escenario import cab

from app.config import Settings, get_settings
from app.integraciones.telefonia.twilio import ProveedorTwilio


def test_token_falso(client, crear_usuario):
    ag = crear_usuario("agente")
    r = client.post("/api/v1/telefonia/token", headers=cab(ag))
    assert r.status_code == 200
    t = r.json()
    assert t["proveedor"] == "falso" and t["identity"] == f"agente_{ag.id}"
    assert t["token"].startswith(f"falso.agente_{ag.id}.") and t["expira_en"].endswith("Z")


def test_solo_agentes(client, h_admin, h_supervisor):
    for h in (h_admin, h_supervisor):
        assert client.post("/api/v1/telefonia/token", headers=h).status_code == 403
    assert client.post("/api/v1/telefonia/token").status_code == 401


def test_token_twilio_lleva_voicegrant_sin_entrantes():
    s = Settings(
        _env_file=None,
        entorno="test",
        telefonia_proveedor="twilio",
        twilio_account_sid="ACabc",
        twilio_auth_token="tok",
        twilio_api_key_sid="SKabc",
        twilio_api_key_secret="secreto-de-la-api-key-de-pruebas-0123456789",
        twilio_twiml_app_sid="APabc",
        twilio_numero_saliente="+576015550000",
        public_base_url="http://localhost:8000",
    )
    t = ProveedorTwilio(s).emitir_token("agente_5", 600)
    assert t.proveedor == "twilio" and t.identity == "agente_5"
    claims = jwt.decode(t.token, s.twilio_api_key_secret, algorithms=["HS256"])
    assert claims["iss"] == "SKabc" and claims["sub"] == "ACabc"
    voz = claims["grants"]["voice"]
    assert voz["outgoing"]["application_sid"] == "APabc"
    assert not voz.get("incoming", {}).get("allow", False)  # las entrantes llegan en 2E
    assert claims["grants"]["identity"] == "agente_5"
    assert 0 < claims["exp"] - claims["nbf"] <= 600 + 5


def test_colgar_usa_rest_con_status_completed():
    llamadas = []

    class Cliente:
        def calls(self, sid):
            class Llamada:
                def update(self, **kw):
                    llamadas.append((sid, kw))

            return Llamada()

    s = Settings(_env_file=None, entorno="test")
    ProveedorTwilio(s, cliente_rest=Cliente).colgar("CA123")
    assert llamadas == [("CA123", {"status": "completed"})]


def test_proveedor_por_defecto_es_falso():
    assert get_settings().telefonia_proveedor == "falso"
