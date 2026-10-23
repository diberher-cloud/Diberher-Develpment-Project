import copy

import pytest
from pydantic import ValidationError

from app.modulos.cumplimiento.politica import PoliticaCumplimiento, politica_por_defecto


def _cfg(**cambios):
    cfg = copy.deepcopy(politica_por_defecto())
    cfg.update(cambios)
    return cfg


def test_por_defecto_valida():
    p = PoliticaCumplimiento.model_validate(politica_por_defecto())
    assert p.franjas.sabado[0].fin == "15:00"
    assert p.model_dump(mode="json") == politica_por_defecto()


def _franjas(**dias):
    f = copy.deepcopy(politica_por_defecto()["franjas"])
    f.update(dias)
    return f


@pytest.mark.parametrize(
    "cfg",
    [
        _cfg(
            franjas=_franjas(
                lunes=[{"inicio": "07:00", "fin": "12:00"}, {"inicio": "11:00", "fin": "13:00"}]
            )
        ),
        _cfg(
            franjas=_franjas(
                lunes=[{"inicio": "14:00", "fin": "15:00"}, {"inicio": "07:00", "fin": "08:00"}]
            )
        ),
        _cfg(franjas=_franjas(lunes=[{"inicio": "19:00", "fin": "07:00"}])),
        _cfg(franjas=_franjas(lunes=[{"inicio": "07:00", "fin": "07:00"}])),
        _cfg(franjas=_franjas(lunes=[{"inicio": "07:00", "fin": "25:00"}])),
        _cfg(franjas={k: v for k, v in _franjas().items() if k != "domingo"}),
        _cfg(extra=1),
        _cfg(zona_horaria="Mars/Olympus"),
        _cfg(frecuencia={**politica_por_defecto()["frecuencia"], "max_contactos_dia": 0}),
        _cfg(frecuencia={**politica_por_defecto()["frecuencia"], "semana": "otra"}),
    ],
)
def test_rechaza(cfg):
    with pytest.raises(ValidationError):
        PoliticaCumplimiento.model_validate(cfg)


def test_franjas_contiguas_permitidas():
    cfg = _cfg(
        franjas=_franjas(
            lunes=[{"inicio": "07:00", "fin": "12:00"}, {"inicio": "12:00", "fin": "19:00"}]
        )
    )
    assert PoliticaCumplimiento.model_validate(cfg)
