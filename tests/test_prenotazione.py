# -*- coding: utf-8 -*-
"""Due lavorazioni partite insieme non devono scegliere la stessa notizia.

Il 30 settembre 2026 sul canale notizie e' successo proprio questo: vedi
prenotazione.py. Qui si simulano con un repository vero, in locale.
"""
import json
import os
import subprocess

import pytest

import brain
import config
import prenotazione


def _git(cartella, *argomenti):
    subprocess.run(["git", *argomenti], cwd=cartella, check=True,
                   capture_output=True, text=True)


def _voce(titolo, fonte, ts, video_id="abc"):
    return {"timestamp": ts, "titolo": titolo, "fonte": fonte, "video_id": video_id}


@pytest.fixture
def due_copie(tmp_path, monkeypatch):
    """Un remoto e due cloni, come due lavorazioni sullo stesso repository."""
    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remoto)], check=True)
    seme = tmp_path / "seme"
    subprocess.run(["git", "clone", "-q", str(remoto), str(seme)], check=True)
    (seme / "cronologia_trend.json").write_text(
        json.dumps([_voce("Vecchio video", "Vecchia notizia (ANSA)", 100)]), encoding="utf-8")
    (seme / "performance.json").write_text("{}", encoding="utf-8")
    _git(seme, "add", ".")
    _git(seme, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "inizio")
    _git(seme, "push", "-q", "origin", "HEAD:main")
    copie = []
    for nome in ("prima", "seconda"):
        c = tmp_path / nome
        subprocess.run(["git", "clone", "-q", str(remoto), str(c)], check=True)
        copie.append(c)
    monkeypatch.setenv("SAMARITAN_PRENOTA", "1")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    return remoto, copie


def _in(monkeypatch, cartella):
    monkeypatch.setattr(config, "DIR_PROGETTO", str(cartella))
    monkeypatch.setattr(config, "FILE_CRONOLOGIA", str(cartella / "cronologia_trend.json"))
    monkeypatch.setattr(config, "FILE_PRENOTAZIONI", str(cartella / "prenotazioni.json"))
    # Ogni copia e' una lavorazione a se': la riga in corso non si eredita.
    monkeypatch.setattr(prenotazione, "_IN_CORSO", None)


def _remota(remoto, file="cronologia_trend.json"):
    uscita = subprocess.run(["git", "--git-dir", str(remoto), "show", f"main:{file}"],
                            capture_output=True, text=True, check=True)
    return json.loads(uscita.stdout)


def _dati(titolo, fonte):
    return {"titolo": titolo, "script": "x", "stile": "VIRAL_HOOK_NEWS",
            "query_video": "stage", "fonte": fonte}


def test_la_seconda_vede_la_notizia_della_prima(due_copie, monkeypatch):
    remoto, (prima, seconda) = due_copie
    _in(monkeypatch, prima)
    brain.prepara_voce_cronologia(_dati("Sanremo: festival targato De Martino",
                                        "Sanremo (Adnkronos)"))
    assert prenotazione.prenota("Sanremo")
    assert [v["titolo"] for v in _remota(remoto, "prenotazioni.json")] == \
        ["Sanremo: festival targato De Martino"]

    _in(monkeypatch, seconda)
    assert prenotazione.riallinea_cronologia()
    fonti = [v.get("fonte") for v in brain._memoria_per_la_scelta()]
    assert "Sanremo (Adnkronos)" in fonti


def test_la_prenotazione_non_scrive_la_cronologia(due_copie, monkeypatch):
    """Il difetto del 12 ottobre 2026: la riga di un video mai uscito."""
    remoto, (prima, _) = due_copie
    _in(monkeypatch, prima)
    brain.prepara_voce_cronologia(_dati("T", "F (X)"))
    assert prenotazione.prenota("T")
    assert [v["titolo"] for v in _remota(remoto)] == ["Vecchio video"]
    assert [v["titolo"] for v in brain.carica_cronologia()] == ["Vecchio video"]


def test_la_prenotazione_non_sposta_il_ramo_locale(due_copie, monkeypatch):
    remoto, (prima, _) = due_copie
    _in(monkeypatch, prima)
    prima_di = subprocess.run(["git", "rev-parse", "HEAD"], cwd=prima,
                              capture_output=True, text=True).stdout
    (prima / "performance.json").write_text('{"nostra": 1}', encoding="utf-8")
    brain.prepara_voce_cronologia(_dati("T", "F (X)"))
    assert prenotazione.prenota("T")
    dopo = subprocess.run(["git", "rev-parse", "HEAD"], cwd=prima,
                          capture_output=True, text=True).stdout
    assert prima_di == dopo
    # Nel commit di prenotazione ci sono solo le prenotazioni.
    remota_perf = subprocess.run(["git", "--git-dir", str(remoto), "show", "main:performance.json"],
                                 capture_output=True, text=True).stdout
    assert remota_perf == "{}"


def test_due_prenotazioni_non_si_cancellano(due_copie, monkeypatch):
    remoto, (prima, seconda) = due_copie
    for cartella, titolo in ((prima, "Uno"), (seconda, "Due")):
        _in(monkeypatch, cartella)
        brain.prepara_voce_cronologia(_dati(titolo, titolo + " (X)"))
        assert prenotazione.prenota(titolo)
    titoli = [v["titolo"] for v in _remota(remoto, "prenotazioni.json")]
    assert "Uno" in titoli and "Due" in titoli


def test_la_riga_entra_in_cronologia_solo_a_video_caricato(due_copie, monkeypatch):
    _, (prima, _) = due_copie
    _in(monkeypatch, prima)
    brain.prepara_voce_cronologia(_dati("Nostra", "N (X)"))
    # Una lavorazione partita insieme ha registrato il suo video nel frattempo.
    cronologia = brain.carica_cronologia()
    cronologia.append(_voce("Altra", "A (X)", 10 ** 10))
    with open(config.FILE_CRONOLOGIA, "w", encoding="utf-8") as f:
        json.dump(cronologia, f)

    assert brain.registra_video_caricato("VID123")

    per_titolo = {v["titolo"]: v.get("video_id") for v in brain.carica_cronologia()}
    assert per_titolo["Nostra"] == "VID123"
    assert per_titolo["Altra"] == "abc"
    # La prenotazione e' chiusa: la notizia ora sta in cronologia.
    assert prenotazione.attive() == []
    assert prenotazione.voce_in_corso() is None


def test_senza_video_id_non_si_scrive_niente(tmp_path, monkeypatch):
    _in(monkeypatch, tmp_path)
    brain.prepara_voce_cronologia(_dati("Caricamento fallito", "C (X)"))
    assert brain.registra_video_caricato(None) is False
    assert brain.carica_cronologia() == []


def test_le_prenotazioni_scadono(tmp_path, monkeypatch):
    """Una lavorazione morta a meta' non blocca la notizia per sempre."""
    _in(monkeypatch, tmp_path)
    brain.prepara_voce_cronologia(_dati("Morta", "M (X)"))
    ts = prenotazione.voce_in_corso()["timestamp"]
    assert [p["titolo"] for p in prenotazione.attive(adesso=ts + 3600)] == ["Morta"]
    assert prenotazione.attive(adesso=ts + (prenotazione.ORE_VALIDITA + 1) * 3600) == []


def test_spenta_fuori_dal_workflow(tmp_path, monkeypatch):
    monkeypatch.delenv("SAMARITAN_PRENOTA", raising=False)
    _in(monkeypatch, tmp_path)
    assert prenotazione.prenota("x") is False
    assert prenotazione.riallinea_cronologia() is False


def _workflow():
    radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(radice, ".github", "workflows", "samaritan.yml"), encoding="utf-8") as f:
        return f.read()


def test_il_workflow_la_accende():
    assert "SAMARITAN_PRENOTA: '1'" in _workflow()


def test_il_workflow_salva_la_cronologia_solo_a_pipeline_riuscita():
    """Run 38239595126: caduta con tutti gli script scartati, memoria salvata lo stesso."""
    testo = _workflow()
    passo = testo[testo.index("- name: Salva memoria e performance"):]
    passo = passo[:passo.index("- name: Conserva il video prodotto")]
    assert "ESITO_PIPELINE: ${{ steps.pipeline.outcome }}" in passo
    assert 'if [ "$ESITO_PIPELINE" = "success" ]; then' in passo
    # Nessun elenco fisso che contenga sempre la cronologia.
    assert "for file_memoria in cronologia_trend.json" not in passo
    ramo_fallito = passo[passo.index("else"):passo.index("fi", passo.index("else"))]
    assert "cronologia_trend.json" not in ramo_fallito.split("memoria=")[1]
