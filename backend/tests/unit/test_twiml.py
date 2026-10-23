import xml.etree.ElementTree as ET

from app.modulos.telefonia import twiml

B = "https://pruebas.example.com"


def normalizado(xml: str) -> str:
    return ET.canonicalize(xml, strip_text=True)


def test_dial_con_grabacion_literal():
    esperado = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial callerId="+576015550000" answerOnBridge="true" timeout="30" timeLimit="3600"
        record="record-from-answer-dual"
        recordingStatusCallback="{B}/api/v1/telefonia/webhooks/grabacion?llamada_id=31"
        recordingStatusCallbackEvent="completed"
        action="{B}/api/v1/telefonia/twiml/dial-terminado?llamada_id=31" method="POST">
    <Number url="{B}/api/v1/telefonia/twiml/aviso-grabacion?llamada_id=31" method="POST"
            statusCallback="{B}/api/v1/telefonia/webhooks/estado?llamada_id=31"
            statusCallbackEvent="initiated ringing answered completed"
            statusCallbackMethod="POST">+573001234567</Number>
  </Dial>
</Response>"""
    xml = twiml.twiml_marcar(
        numero="+573001234567",
        base_url=B,
        llamada_id=31,
        grabar=True,
        caller_id="+576015550000",
    )
    assert normalizado(xml) == normalizado(esperado)


def test_dial_sin_grabacion_omite_record_y_url():
    xml = twiml.twiml_marcar(
        numero="+573001234567", base_url=B, llamada_id=1, grabar=False, caller_id="+576015550000"
    )
    raiz = ET.fromstring(xml)
    dial = raiz.find("Dial")
    assert dial is not None and "record" not in dial.attrib
    assert not any(k.startswith("recordingStatusCallback") for k in dial.attrib)
    numero = dial.find("Number")
    assert "url" not in numero.attrib and "method" not in numero.attrib
    assert "statusCallback" in numero.attrib


def test_atributos_y_textos_se_escapan():
    xml = twiml.twiml_rechazo('Hola <"&> mundo', 'es"MX')
    raiz = ET.fromstring(xml)  # sigue siendo XML válido
    say = raiz.find("Say")
    assert say.text == 'Hola <"&> mundo' and say.attrib["language"] == 'es"MX'
    xml = twiml.twiml_marcar(numero="+57<x>", base_url=B + '/"a"', llamada_id=1, grabar=True)
    ET.fromstring(xml)


def test_rechazo_aviso_y_colgar():
    assert normalizado(twiml.twiml_rechazo("No es posible.", "es-MX")) == normalizado(
        '<Response><Say language="es-MX">No es posible.</Say><Hangup/></Response>'
    )
    assert "grabada" in twiml.twiml_aviso_grabacion("Esta llamada será grabada.", "es-MX")
    assert normalizado(twiml.twiml_colgar()) == normalizado("<Response><Hangup/></Response>")
