# -*- coding: utf-8 -*-
"""Il riassunto del sabato: scelta degli Short, titolo, capitoli, descrizione.

Niente ffmpeg e niente rete: solo la logica che decide cosa finisce nel video.
"""
import os
from datetime import datetime, timezone

import riassunto

ADESSO = datetime(2026, 11, 7, 5, 30, tzinfo=timezone.utc)
BASE = int(ADESSO.timestamp())


def _voce(i, giorni_fa, **altro):
    voce = {"video_id": f"vid{i:08d}", "titolo": f"Notizia {i}: qualcosa di nuovo",
            "fonte": f"Titolo {i} (Testata {i})", "formato": "short", "lingua": "it",
            "uscita": BASE - int(giorni_fa * 86400)}
    voce.update(altro)
    return voce


def test_prende_solo_gli_short_usciti_della_settimana():
    cronologia = [
        _voce(1, 8),                              # troppo vecchio
        _voce(2, 6),
        _voce(3, 1, formato="lungo"),             # video lungo
        _voce(4, 2, lingua="en"),                 # altra lingua
        _voce(5, -0.3),                           # programmato per oggi pomeriggio
        _voce(6, 3, video_id=""),                 # mai caricato
        _voce(7, 0.5),
        _voce(2, 6),                              # doppione
        "vecchio formato a stringa",
    ]
    scelti = riassunto.short_della_settimana(cronologia, ADESSO)
    assert [v["video_id"] for v in scelti] == ["vid00000002", "vid00000007"]


def test_senza_uscita_usa_il_timestamp():
    voce = _voce(1, 1)
    voce["timestamp"] = voce.pop("uscita")
    assert len(riassunto.short_della_settimana([voce], ADESSO)) == 1


def test_oltre_dieci_minuti_toglie_le_meno_viste_e_tiene_l_ordine():
    voci = [_voce(i, 6 - i) for i in range(1, 7)]       # da 5 giorni fa a oggi
    durate = {v["video_id"]: 120.0 for v in voci}        # 12 minuti in tutto
    performance = {"video": {"vid00000001": {"views": 5}, "vid00000002": {"views": 900},
                             "vid00000003": {"views": 1}, "vid00000004": {"views": 50},
                             "vid00000005": {"views": 300}, "vid00000006": {"views": 4}}}
    tenute = riassunto.adatta_alla_durata(voci, durate, performance, ADESSO)
    ids = [v["video_id"] for v in tenute]
    # Escono la 3 e la 1 (le meno viste all'ora); la 6 e' online da meno di
    # sei ore e con 4 visualizzazioni batte la 1, che ne ha 5 in cinque giorni.
    assert ids == ["vid00000002", "vid00000004", "vid00000005", "vid00000006"]
    assert sum(durate[i] for i in ids) <= riassunto.MAX_SECONDI


def test_titolo_con_le_tre_piu_viste_senza_doppioni_e_dentro_100_caratteri():
    voci = [_voce(1, 5, titolo="Stellantis: batterie LFP dal 2027"),
            _voce(2, 4, titolo="Stellantis: aiuti per Mirafiori"),
            _voce(3, 3, titolo="F1: GP Messico, Ferrari in difficolta'"),
            _voce(4, 2, titolo="Il prezzo della benzina scende ancora oggi", gioco="prezzo benzina"),
            _voce(5, 1, titolo="Ducati: nuova Panigale")]
    performance = {"video": {"vid00000001": {"views": 900}, "vid00000002": {"views": 800},
                             "vid00000003": {"views": 700}, "vid00000004": {"views": 600}}}
    top = riassunto.top_notizie(voci, performance)
    assert top == ["Stellantis", "F1", "prezzo benzina"]
    titolo = riassunto.costruisci_titolo(top, ADESSO)
    assert titolo == "Motori della settimana: Stellantis, F1 e prezzo benzina (07/11)"
    lungo = riassunto.costruisci_titolo(["x" * 40, "y" * 40, "z" * 40], ADESSO)
    assert len(lungo) <= 100 and lungo.endswith("(07/11)")


def test_capitoli_validi_per_youtube():
    voci = [_voce(i, 6 - i) for i in range(1, 6)]
    durate = {v["video_id"]: 45.0 for v in voci}
    capitoli = riassunto.formatta_capitoli(riassunto.capitoli(voci, durate))
    righe = capitoli.splitlines()
    assert len(righe) == 5
    assert righe[0].startswith("0:00 Notizia 1")
    # Il secondo parte dopo apertura + primo Short.
    assert righe[1].startswith("0:49 ")


def test_descrizione_con_fonti_short_e_dichiarazione_ai():
    voci = [_voce(i, 6 - i, fonte_url="https://news.google.com/rss/articles/" + "X" * 400)
            for i in range(1, 15)]
    durate = {v["video_id"]: 40.0 for v in voci}
    testo = riassunto.costruisci_descrizione(voci, durate, ADESSO, ADESSO,
                                             "Motori in 60 secondi", "@Motoriin60secondi")
    assert len(testo) <= 5000
    assert "Capitoli:" in testo and "Fonte: Testata 3" in testo
    assert "youtube.com/shorts/vid00000014" in testo
    assert "Video realizzato con l'AI" in testo
    # Con 14 link lunghissimi non ci starebbe: i link si tolgono, il resto no.
    assert "news.google.com" not in testo


def test_non_rifa_il_riassunto_dello_stesso_sabato():
    registro = [{"data": "2026-11-07", "video_id": "abc"}]
    assert riassunto.gia_fatto(registro, ADESSO)
    assert not riassunto.gia_fatto(registro, datetime(2026, 11, 14, tzinfo=timezone.utc))


def test_meno_di_cinque_short_non_pubblica(monkeypatch, tmp_path):
    import config
    cronologia = tmp_path / "cronologia.json"
    cronologia.write_text(
        __import__("json").dumps([_voce(i, i) for i in range(1, 5)]), encoding="utf-8")
    monkeypatch.setattr(config, "FILE_CRONOLOGIA", str(cronologia))
    monkeypatch.setattr(config, "FILE_PERFORMANCE", str(tmp_path / "nessuno.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(riassunto, "procura_file",
                        lambda *a: (_ for _ in ()).throw(AssertionError("non doveva scaricare")))
    monkeypatch.setattr(riassunto, "_avvisa", lambda testo: None)
    assert riassunto.esegui("public", adesso=ADESSO) is None
    assert not os.path.exists(tmp_path / riassunto.FILE_REGISTRO)


def test_archivia_short_scrive_l_output_per_il_workflow(monkeypatch, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"0" * 100)
    uscita = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(uscita))
    percorso = riassunto.archivia_short(str(video), "Wmd6afJmlVk", str(tmp_path))
    assert percorso and os.path.exists(percorso)
    assert percorso.endswith(os.path.join("settimana", "Wmd6afJmlVk.mp4"))
    assert uscita.read_text(encoding="utf-8") == "short_id=Wmd6afJmlVk\n"
    # Un id strano non diventa mai il nome di un artifact.
    assert riassunto.archivia_short(str(video), "../../x y", str(tmp_path)) is None


def test_il_workflow_degli_short_conserva_l_artifact():
    radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(radice, ".github", "workflows", "samaritan.yml"),
              encoding="utf-8") as f:
        testo = f.read()
    assert "name: short-${{ steps.pipeline.outputs.short_id }}" in testo
    assert "output_videos/settimana/" in testo
