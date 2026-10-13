# -*- coding: utf-8 -*-
"""La copia pubblica dello Short: indirizzo e didascalia nella voce giusta,
e mai una pipeline fermata per colpa sua. Niente rete: requests e' finto."""
import json
from datetime import datetime, timezone

import brain
import config
import copia_pubblica
import prenotazione


class Risposta:
    def __init__(self, ok=True, j=None, status=200):
        self.ok, self._j, self.status_code, self.text = ok, j or {}, status, ""

    def json(self):
        return self._j


URL = "https://x.public.blob.vercel-storage.com/notizie/abc-r.mp4"

DATI = {
    "titolo": "Manovra, cosa cambia per le pensioni",
    "descrizione": "Le novita' approvate dal governo.\nTu cosa ne pensi?",
    "script": "x", "stile": "VIRAL_HOOK_NEWS", "query_video": "parlamento",
    "gioco": "",
    "fonte": "Manovra, via libera alle pensioni (ANSA)",
    "fonte_url": "https://news.example.com/manovra",
}


def _in(monkeypatch, cartella):
    monkeypatch.setattr(config, "DIR_PROGETTO", str(cartella))
    monkeypatch.setattr(config, "FILE_CRONOLOGIA", str(cartella / "cronologia_trend.json"))
    monkeypatch.setattr(config, "FILE_PRENOTAZIONI", str(cartella / "prenotazioni.json"))
    monkeypatch.setattr(prenotazione, "_IN_CORSO", None)
    monkeypatch.delenv("SAMARITAN_PRENOTA", raising=False)


# --- copia_pubblica.prepara ------------------------------------------------

def test_senza_token_non_fa_niente(monkeypatch, tmp_path):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)

    def put(*a, **k):
        raise AssertionError("senza token non si chiama la rete")

    monkeypatch.setattr(copia_pubblica.requests, "put", put)
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    assert copia_pubblica.prepara(str(f), "abc", DATI) == {}


def test_carica_in_notizie_e_restituisce_url_e_didascalia(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "t")
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    chiamate = []

    def put(url, params=None, data=None, headers=None, timeout=None):
        chiamate.append((params, headers))
        return Risposta(j={"url": URL})

    monkeypatch.setattr(copia_pubblica.requests, "put", put)
    monkeypatch.setattr(copia_pubblica, "pulisci", lambda token: 0)
    campi = copia_pubblica.prepara(str(f), "abc", DATI)
    assert campi["video_file_url"] == URL
    assert campi["didascalia_tiktok"].startswith(DATI["titolo"])
    assert chiamate[0][0] == {"pathname": "notizie/abc.mp4"}
    assert chiamate[0][1]["authorization"] == "Bearer t"


def test_errore_di_rete_non_esce(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "t")
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")

    def put(*a, **k):
        raise ConnectionError("giu'")

    monkeypatch.setattr(copia_pubblica.requests, "put", put)
    assert copia_pubblica.prepara(str(f), "abc", DATI) == {}


def test_http_non_ok_non_scrive_niente(monkeypatch, tmp_path):
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "t")
    f = tmp_path / "v.mp4"; f.write_bytes(b"x")
    monkeypatch.setattr(copia_pubblica.requests, "put",
                        lambda *a, **k: Risposta(ok=False, status=403))
    assert copia_pubblica.prepara(str(f), "abc", DATI) == {}


def test_pulisci_cancella_solo_le_vecchie_di_notizie(monkeypatch):
    elenco = {"blobs": [
        {"url": "u-vecchia", "pathname": "notizie/a.mp4", "uploadedAt": "2026-10-01T10:00:00.000Z"},
        {"url": "u-nuova", "pathname": "notizie/b.mp4", "uploadedAt": "2026-10-12T10:00:00.000Z"},
        {"url": "u-altrui", "pathname": "samaritan/c.mp4", "uploadedAt": "2026-10-01T10:00:00.000Z"},
    ], "hasMore": False}
    cancellate, prefissi = [], []

    def get(url, params=None, **k):
        prefissi.append(params["prefix"])
        return Risposta(j=elenco)

    monkeypatch.setattr(copia_pubblica.requests, "get", get)
    monkeypatch.setattr(copia_pubblica.requests, "post",
                        lambda url, json=None, **k: cancellate.extend(json["urls"]) or Risposta())
    n = copia_pubblica.pulisci("t", adesso=datetime(2026, 10, 13, tzinfo=timezone.utc))
    assert prefissi == ["notizie/"]
    assert n == 1 and cancellate == ["u-vecchia"]


# --- la voce di cronologia -------------------------------------------------

def test_i_campi_finiscono_nella_voce_del_video(monkeypatch, tmp_path):
    _in(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "LINGUA", "it")
    brain.prepara_voce_cronologia(DATI)
    assert brain.registra_video_caricato("VID1")
    # Un'altra lavorazione scrive la sua riga subito dopo.
    cronologia = brain.carica_cronologia()
    cronologia.append({"timestamp": 10 ** 10, "titolo": "Altra", "video_id": "VID2"})
    with open(config.FILE_CRONOLOGIA, "w", encoding="utf-8") as f:
        json.dump(cronologia, f)

    assert brain.aggiungi_alla_voce("VID1", video_file_url=URL, didascalia_tiktok="d")

    per_id = {v["video_id"]: v for v in brain.carica_cronologia()}
    assert per_id["VID1"]["video_file_url"] == URL
    assert per_id["VID1"]["didascalia_tiktok"] == "d"
    assert per_id["VID1"]["lingua"] == "it"
    assert "video_file_url" not in per_id["VID2"]


def test_video_sconosciuto_non_tocca_niente(monkeypatch, tmp_path):
    _in(monkeypatch, tmp_path)
    assert brain.aggiungi_alla_voce("NESSUNO", video_file_url=URL) is False
    assert brain.aggiungi_alla_voce("VID1") is False
    assert brain.carica_cronologia() == []


# --- la didascalia ---------------------------------------------------------

def test_didascalia_con_testata_nota_ai_e_hashtag(monkeypatch):
    monkeypatch.setattr(config, "LINGUA", "it")
    d = brain.costruisci_didascalia_tiktok(DATI)
    assert d.startswith(DATI["titolo"])
    assert "Fonte: ANSA" in d
    assert "AI" in d
    assert DATI["fonte_url"] not in d          # su TikTok i link non si cliccano
    assert d.splitlines()[-1].startswith("#")
    assert len(d) <= 2200


def test_didascalia_senza_fonte_non_inventa_niente(monkeypatch):
    monkeypatch.setattr(config, "LINGUA", "it")
    d = brain.costruisci_didascalia_tiktok(dict(DATI, fonte=""))
    assert "Fonte" not in d


def test_didascalia_in_inglese(monkeypatch):
    monkeypatch.setattr(config, "LINGUA", "en")
    d = brain.costruisci_didascalia_tiktok(DATI)
    assert "Source: ANSA" in d and "#fyp" in d


# --- la pipeline -----------------------------------------------------------

def _pipeline(monkeypatch, tmp_path):
    """esegui_pipeline_samaritan con scrittura, upload e notifiche finti."""
    import analyst
    import main
    _in(monkeypatch, tmp_path)
    video = tmp_path / "v.mp4"; video.write_bytes(b"x")

    def scrivi_e_monta(tema):
        brain.prepara_voce_cronologia(DATI)
        return DATI, str(video), {}, ""

    monkeypatch.setattr(main, "prepara_uscita", lambda: True)
    monkeypatch.setattr(main.autoprofilo, "aggiorna_se_serve", lambda: None)
    monkeypatch.setattr(analyst, "aggiorna_performance", lambda: None)
    monkeypatch.setattr(main, "_scrivi_e_monta", scrivi_e_monta)
    monkeypatch.setattr(main, "carica_short", lambda **k: "VID9")
    monkeypatch.setattr(main.orari, "uscita_programmata", lambda: None)
    monkeypatch.setattr(main.notifier, "notifica_pubblicazione", lambda *a, **k: None)
    monkeypatch.setattr(config, "VIDEO_LUNGO", False)
    monkeypatch.setattr(config, "LINGUA", "it")
    return main


def test_pipeline_scrive_indirizzo_e_didascalia_nella_voce(monkeypatch, tmp_path):
    main = _pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(main.copia_pubblica, "prepara",
                        lambda percorso, video_id, dati: {"video_file_url": URL,
                                                          "didascalia_tiktok": "d"})
    assert main.esegui_pipeline_samaritan() == "VID9"
    [voce] = brain.carica_cronologia()
    assert voce["video_id"] == "VID9" and voce["lingua"] == "it"
    assert voce["video_file_url"] == URL and voce["didascalia_tiktok"] == "d"


def test_pipeline_senza_token_lascia_la_voce_com_era(monkeypatch, tmp_path):
    main = _pipeline(monkeypatch, tmp_path)
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    assert main.esegui_pipeline_samaritan() == "VID9"
    [voce] = brain.carica_cronologia()
    assert voce["video_id"] == "VID9"
    assert "video_file_url" not in voce


def test_se_la_copia_esplode_la_pipeline_finisce_lo_stesso(monkeypatch, tmp_path):
    main = _pipeline(monkeypatch, tmp_path)

    def esplode(*a):
        raise RuntimeError("blob rotto")

    monkeypatch.setattr(main.copia_pubblica, "prepara", esplode)
    assert main.esegui_pipeline_samaritan() == "VID9"
    assert [v["video_id"] for v in brain.carica_cronologia()] == ["VID9"]
