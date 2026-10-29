"""Test sugli effetti del montaggio veloce dello Short (effetti.py).

La logica (dove tagliare, cosa accendere, quando suonare) e' pura e si
verifica sempre. I suoni vogliono numpy e il montaggio vero moviepy: nella
suite della CI non ci sono, per scelta (vedi requirements-dev.txt), quindi
quei test si saltano da soli dove mancano e girano dove ci sono. Nessun test
tocca la rete.
"""
import json
import os
import wave

import pytest

import config
import effetti
import veste


def _parole(testo, passo=0.30, pausa_frase=0.40, inizio=0.1):
    """Tempi finti, senza punteggiatura come li da' Edge-TTS."""
    parole, t = [], inizio
    for w in testo.split():
        nuda = w.strip(".,!?")
        parole.append({"parola": nuda, "inizio": round(t, 3),
                       "fine": round(t + passo, 3)})
        t += passo + (pausa_frase if w[-1] in ".!?" else 0.03)
    return parole


TESTO = ("La nuova Panda arriva in Italia. Costa 18.900 euro e con gli incentivi "
         "scende del 20 per cento. Stellantis vuole vendere 100 mila auto entro "
         "il 2027. Tu la compreresti?")


# ===========================================================================
# STACCHI A TEMPO
# ===========================================================================
class TestPuntiDiStacco:
    def test_gli_stacchi_restano_nella_finestra(self):
        parole = effetti.ripunteggia(_parole(TESTO), TESTO)
        durata = parole[-1]["fine"] + 2.0
        punti = effetti.punti_di_stacco(parole, durata, 1.5, 2.0)
        assert punti[0] == 0.0
        distanze = [b - a for a, b in zip(punti, punti[1:])]
        assert distanze and all(1.5 - 1e-6 <= d <= 2.0 + 1e-6 for d in distanze)
        # l'ultimo pezzo non e' ne' un frammento ne' troppo lungo
        assert effetti.STACCO_MINIMO_FINALE <= durata - punti[-1] <= 2.0 + 1e-6

    def test_taglia_a_fine_frase_quando_cade_nella_finestra(self):
        parole = effetti.ripunteggia(_parole("Uno due tre quattro. Cinque sei sette otto nove dieci"),
                                     "Uno due tre quattro. Cinque sei sette otto nove dieci")
        fine_frase = parole[3]["fine"]
        inizio_dopo = parole[4]["inizio"]
        punti = effetti.punti_di_stacco(parole, 6.0, minimo=0.9, massimo=2.0)
        # il primo taglio cade nella pausa dopo "quattro.", non a meta' parola
        assert fine_frase <= punti[1] <= inizio_dopo

    def test_senza_punteggiatura_usa_le_pause(self):
        parole = _parole("uno due tre quattro cinque sei sette otto", pausa_frase=0)
        parole[4]["inizio"] += 0.3   # una pausa vera prima di "cinque"
        for p in parole[5:]:
            p["inizio"] += 0.3
            p["fine"] += 0.3
        parole[4]["fine"] += 0.3
        punti = effetti.punti_di_stacco(parole, 4.0, minimo=1.0, massimo=1.8)
        assert parole[3]["fine"] <= punti[1] <= parole[4]["inizio"]

    def test_mai_in_mezzo_a_una_parola(self):
        parole = effetti.ripunteggia(_parole(TESTO), TESTO)
        punti = effetti.punti_di_stacco(parole, parole[-1]["fine"] + 2, 1.5, 2.0)
        for t in punti[1:]:
            assert not any(p["inizio"] < t < p["fine"] for p in parole), t

    def test_senza_parole_taglia_a_ritmo_fisso(self):
        punti = effetti.punti_di_stacco([], 10.0, 1.5, 2.0)
        distanze = [b - a for a, b in zip(punti, punti[1:])]
        assert all(abs(d - 1.75) < 1e-6 for d in distanze)
        assert 10.0 - punti[-1] <= 2.0

    def test_video_cortissimo_un_solo_stacco(self):
        assert effetti.punti_di_stacco([], 1.2, 1.5, 2.0) == [0.0]

    def test_i_segmenti_coprono_tutta_la_durata(self):
        punti = effetti.punti_di_stacco([], 9.3, 1.5, 2.0)
        segmenti = effetti.segmenti_da_punti(punti, 9.3)
        assert abs(sum(d for _, d in segmenti) - 9.3) < 1e-6
        assert segmenti[0][0] == 0.0


class TestOrdineSorgenti:
    @pytest.mark.parametrize("n", [2, 3, 4, 7])
    def test_mai_la_stessa_clip_due_volte_di_fila(self, n):
        ordine = effetti.ordine_sorgenti(n, 25)
        assert len(ordine) == 25
        assert all(a != b for a, b in zip(ordine, ordine[1:]))
        assert set(ordine) == set(range(n))

    def test_con_una_sola_sorgente_si_ripete_per_forza(self):
        assert effetti.ordine_sorgenti(1, 3) == [0, 0, 0]

    def test_senza_sorgenti_niente(self):
        assert effetti.ordine_sorgenti(0, 5) == []


# ===========================================================================
# PAROLE CHIAVE E RIGHE
# ===========================================================================
class TestParoleChiave:
    def _tipi(self, testo, titolo=()):
        parole = effetti.ripunteggia(_parole(testo), testo)
        return {p["parola"].strip(".,!?"): effetti.tipo_parola(parole, i, titolo)
                for i, p in enumerate(parole)}

    def test_numeri_prezzi_e_percentuali(self):
        tipi = self._tipi("Costa 18.900 euro e scende del 20% oppure di 15 per cento")
        assert tipi["18.900"] == "numero"
        assert tipi["euro"] == "numero"      # l'unita' dopo il numero
        assert tipi["20%"] == "numero"
        assert tipi["15"] == "numero"
        assert tipi["Costa"] == ""
        assert tipi["scende"] == ""

    def test_numeri_detti_in_lettere(self):
        tipi = self._tipi("Arrivano cento mila auto nuove")
        assert tipi["cento"] == "numero"
        assert tipi["mila"] == "numero"
        assert tipi["auto"] == ""

    def test_nomi_propri_ma_non_l_inizio_frase(self):
        tipi = self._tipi("Oggi Ferrari e Stellantis presentano. Domani tocca a Tesla")
        assert tipi["Ferrari"] == "nome"
        assert tipi["Stellantis"] == "nome"
        assert tipi["Tesla"] == "nome"
        assert tipi["Oggi"] == ""
        assert tipi["Domani"] == ""          # apre la frase dopo il punto
        assert tipi["presentano"] == ""

    def test_l_inizio_frase_si_riconosce_anche_dalla_pausa(self):
        # senza punteggiatura: la pausa lunga prima di "Domani" fa da punto
        parole = _parole("presentano Domani tocca", pausa_frase=0)
        parole[1]["inizio"] += 0.5
        assert effetti.tipo_parola(parole, 1) == ""

    def test_le_parole_del_titolo_contano_come_chiave(self):
        titolo = effetti.parole_del_titolo("Grande Panda: arriva l'ibrida")
        assert "PANDA" in titolo and "IBRIDA" in titolo
        parole = _parole("La grande novita e la panda")
        assert effetti.tipo_parola(parole, 5, titolo) == "nome"


class TestRipunteggia:
    def test_rimette_punti_e_virgole(self):
        parole = _parole("Arriva oggi, costa poco. Tu la compri?")
        risultato = effetti.ripunteggia(parole, "Arriva oggi, costa poco. Tu la compri?")
        assert [p["parola"] for p in risultato] == [
            "Arriva", "oggi,", "costa", "poco.", "Tu", "la", "compri?"]
        # l'originale non si tocca
        assert parole[1]["parola"] == "oggi"

    def test_regge_parole_che_il_testo_non_ha(self):
        parole = _parole("costa diciottomila euro.")
        risultato = effetti.ripunteggia(parole, "Costa 18.000 euro.")
        assert [p["parola"] for p in risultato] == ["costa", "diciottomila", "euro."]


class TestRighe:
    def test_righe_corte_e_spezzate_a_fine_frase(self):
        parole = effetti.ripunteggia(_parole(TESTO), TESTO)
        righe = effetti.raggruppa_parole(parole)
        assert sum(len(r) for r in righe) == len(parole)
        assert [i for r in righe for i in r] == list(range(len(parole)))
        for riga in righe:
            assert 1 <= len(riga) <= 3
            # una riga non scavalca mai un punto
            for i in riga[:-1]:
                assert parole[i]["parola"][-1] not in ".!?"


class TestMomentiPop:
    def test_un_pop_per_numero_e_non_troppo_vicini(self):
        parole = effetti.ripunteggia(_parole(TESTO), TESTO)
        istanti = effetti.momenti_pop(parole)
        assert istanti, "nessun pop su un testo pieno di numeri"
        assert all(b - a >= effetti.DISTANZA_MIN_POP for a, b in zip(istanti, istanti[1:]))
        inizi_numeri = {p["inizio"] for i, p in enumerate(parole)
                        if effetti.tipo_parola(parole, i) == "numero"}
        assert set(istanti) <= inizi_numeri

    def test_senza_numeri_nessun_pop(self):
        assert effetti.momenti_pop(_parole("arriva la nuova auto")) == []


class TestFinale:
    def test_usa_il_nome_del_canale_non_un_testo_fisso(self):
        righe = effetti.testi_finale("Cucina in 60 secondi", "@cucina60")
        assert righe == ["SEGUICI", "Cucina in 60 secondi", "@cucina60"]
        assert not any("motori" in r.lower() for r in righe)

    def test_in_inglese(self):
        assert effetti.testi_finale("Cars", lingua="en")[0] == "FOLLOW US"

    def test_logo_solo_se_c_e(self, tmp_path):
        assert effetti.trova_logo(str(tmp_path)) is None
        (tmp_path / "logo.png").write_bytes(b"x")
        assert effetti.trova_logo(str(tmp_path)) == str(tmp_path / "logo.png")


# ===========================================================================
# SUONI (numpy)
# ===========================================================================
class TestSuoni:
    @pytest.fixture(autouse=True)
    def _numpy(self):
        pytest.importorskip("numpy")

    def test_whoosh_lunghezza_e_volume(self):
        import numpy as np
        suono = effetti.suono_whoosh(durata=0.5)
        assert len(suono) == int(0.5 * effetti.FREQUENZA_AUDIO)
        picco = float(np.max(np.abs(suono)))
        assert picco == pytest.approx(effetti.VOLUME_WHOOSH, rel=1e-6)
        assert picco < 1.0
        # parte e finisce nel silenzio: niente "clic" ai bordi
        assert abs(suono[0]) < 0.01 and abs(suono[-1]) < 0.01
        assert np.isfinite(suono).all()

    def test_pop_lunghezza_e_volume(self):
        import numpy as np
        suono = effetti.suono_pop(durata=0.18)
        assert len(suono) == int(0.18 * effetti.FREQUENZA_AUDIO)
        assert float(np.max(np.abs(suono))) == pytest.approx(effetti.VOLUME_POP, rel=1e-6)
        # si spegne: l'ultimo decimo e' molto piu' basso del primo
        n = len(suono) // 10
        assert np.abs(suono[-n:]).max() < np.abs(suono[:n]).max() * 0.2

    def test_gli_effetti_restano_sotto_la_voce(self):
        assert effetti.VOLUME_WHOOSH <= 0.4
        assert effetti.VOLUME_POP <= 0.4

    def test_traccia_mette_i_suoni_al_loro_posto_e_non_satura(self):
        import numpy as np
        pop = effetti.suono_pop()
        eventi = [(0.5, pop)] + [(1.0, effetti.suono_whoosh(volume=0.9))] * 4
        traccia = effetti.traccia_effetti(3.0, eventi + [(5.0, pop)])
        assert traccia.shape == (3 * effetti.FREQUENZA_AUDIO, 2)
        assert np.abs(traccia).max() <= 0.9 + 1e-9
        assert np.abs(traccia[: int(0.49 * effetti.FREQUENZA_AUDIO)]).max() == 0
        assert np.abs(traccia[int(0.5 * effetti.FREQUENZA_AUDIO):]).max() > 0


# ===========================================================================
# MONTAGGIO VERO, IN PICCOLO (moviepy)
# ===========================================================================
@pytest.fixture
def piccolo(monkeypatch, tmp_path):
    """Uno Short in miniatura: 108x192, 10 fps, cartelle nella tmp del test."""
    pytest.importorskip("moviepy")
    pytest.importorskip("PIL")
    monkeypatch.setattr(config, "VIDEO_W", 108)
    monkeypatch.setattr(config, "VIDEO_H", 192)
    monkeypatch.setattr(config, "FPS", 10)
    monkeypatch.setattr(config, "PRESET_RENDER", "ultrafast")
    monkeypatch.setattr(config, "VIDEO_LUNGO", False)
    monkeypatch.setattr(config, "DIR_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setattr(config, "DIR_TEMP", str(tmp_path / "temp"))
    monkeypatch.setattr(config, "FILE_MINIATURA", str(tmp_path / "out" / "mini.jpg"))
    return tmp_path


def _sorgenti(cartella, quante=3):
    from PIL import Image
    colori = [(200, 40, 40), (40, 160, 60), (40, 70, 200), (220, 200, 40)]
    sorgenti = []
    for i in range(quante):
        percorso = cartella / f"img{i}.png"
        Image.new("RGB", (108, 192), colori[i % len(colori)]).save(percorso)
        sorgenti.append({"tipo": "immagine", "path": str(percorso), "gioco": None})
    return sorgenti


def _voce(cartella, testo):
    """Un audio finto (tono) lungo quanto le parole, con i loro tempi accanto."""
    import numpy as np
    import voice
    parole = _parole(testo)
    sr = 22050
    durata = parole[-1]["fine"] + 0.2
    t = np.arange(int(durata * sr)) / sr
    onda = (0.3 * np.sin(2 * np.pi * 180 * t) * 32000).astype("<i2")
    percorso = str(cartella / "voce.wav")
    with wave.open(percorso, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(onda.tobytes())
    voice._salva_parole(percorso, parole)
    return percorso, durata


class TestMontaggioInPiccolo:
    def test_lo_sfondo_a_tempo_dura_giusto_e_cambia_clip_agli_stacchi(self, piccolo):
        import maker
        stile = veste.VESTI[2]
        punti = effetti.punti_di_stacco([], 6.0, *stile["stacco"])
        sfondo = maker.costruisci_sfondo_montato(_sorgenti(piccolo), 6.0, stile, punti)
        assert sfondo is not None
        assert sfondo.duration == pytest.approx(6.0, abs=0.05)
        assert sfondo.size == (108, 192)
        # a meta' di due stacchi consecutivi le clip sono diverse
        meta = [a + (b - a) / 2 for a, b in zip(punti, punti[1:] + [6.0])]
        colori = [tuple(sfondo.get_frame(t)[96, 54]) for t in meta]
        assert all(a != b for a, b in zip(colori, colori[1:]))

    def test_sottotitoli_accesi_e_righe(self, piccolo):
        import numpy as np
        import maker
        stile = veste.VESTI[0]
        immagine, (x0, y0, x1, y1) = maker.crea_immagine_riga(
            ["COSTA", "18.900", "EURO"], 1,
            [maker.BIANCO, stile["colore_evidenza"], stile["colore_evidenza"]],
            font_size=40, larghezza_max=400)
        assert immagine.shape[2] == 4
        assert 0 <= x0 < x1 <= immagine.shape[1] and 0 <= y0 < y1 <= immagine.shape[0]
        assert np.any(immagine[y0:y1, x0:x1, 3] > 0)

    def test_short_completo_con_effetti(self, piccolo, monkeypatch):
        """assembla_video_finale da capo a fondo, senza rete: sorgenti finte,
        voce finta, nessuna veste annotata. Il video esce, dura voce + finale
        e ha l'audio."""
        import gameplay
        import maker
        from moviepy import VideoFileClip

        sorgenti = _sorgenti(piccolo)
        monkeypatch.setattr(gameplay, "procura_materiale",
                            lambda **kw: (list(sorgenti), None))
        monkeypatch.setattr(veste, "segna_veste", lambda nome: None)
        monkeypatch.setattr(maker, "crea_miniatura", lambda *a, **k: None)
        testo = "La nuova Panda costa 18.900 euro. Tu la compreresti?"
        audio, durata_voce = _voce(piccolo, testo)

        uscita = maker.assembla_video_finale(
            testo_per_audio=testo, titolo="Panda: costa 18.900 euro",
            audio_pronto=audio, query_video="auto")
        assert uscita and os.path.exists(uscita)
        video = VideoFileClip(uscita)
        try:
            assert tuple(video.size) == (108, 192)
            assert video.duration == pytest.approx(
                durata_voce + 0.1 + effetti.SECONDI_FINALE, abs=0.25)
            assert video.audio is not None
        finally:
            video.close()

    def test_il_video_lungo_non_usa_gli_effetti(self, piccolo, monkeypatch):
        import maker
        monkeypatch.setattr(config, "VIDEO_LUNGO", True)
        sorgenti = _sorgenti(piccolo)
        # senza punti il montaggio e' quello di sempre, a stacchi casuali
        sfondo = maker.costruisci_sfondo_montato(sorgenti, 5.0, veste.VESTI[0])
        assert sfondo is not None
        with open(os.path.join(os.path.dirname(maker.__file__), "maker.py"),
                  encoding="utf-8") as f:
            sorgente = f.read()
        assert "wow = not config.VIDEO_LUNGO" in sorgente
