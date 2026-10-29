"""Correzione ortografica dello script prima della voce (29/10/2026)."""
from types import SimpleNamespace

import pytest

import brain

pytestmark = pytest.mark.correttore


def _risponde(monkeypatch, testo=None, errore=None):
    chiamate = []

    def crea(**kwargs):
        chiamate.append(kwargs)
        if errore:
            raise errore
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=testo))])

    monkeypatch.setattr(brain.client.chat.completions, "create", crea)
    return chiamate


def test_il_refuso_si_corregge(monkeypatch):
    _risponde(monkeypatch, "Il cancellamento segna un colpo al mercato.")
    assert (brain.correggi_ortografia("Il cancelamento segna un colpo al mercato.")
            == "Il cancellamento segna un colpo al mercato.")


def test_se_riscrive_la_frase_resta_l_originale(monkeypatch):
    _risponde(monkeypatch, "La decisione colpisce duramente tutto il settore.")
    originale = "Il cancelamento segna un colpo al mercato."
    assert brain.correggi_ortografia(originale) == originale


def test_se_aggiunge_parole_resta_l_originale(monkeypatch):
    _risponde(monkeypatch, "Il cancellamento segna un grande colpo al mercato.")
    originale = "Il cancelamento segna un colpo al mercato."
    assert brain.correggi_ortografia(originale) == originale


def test_se_groq_non_risponde_resta_l_originale(monkeypatch):
    _risponde(monkeypatch, errore=RuntimeError("429"))
    assert brain.correggi_ortografia("Testo giusto.") == "Testo giusto."


def test_testo_vuoto_niente_chiamate(monkeypatch):
    chiamate = _risponde(monkeypatch, "x")
    assert brain.correggi_ortografia("") == ""
    assert chiamate == []
