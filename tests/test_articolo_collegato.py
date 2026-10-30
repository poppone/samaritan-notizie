"""Il link all'articolo di davidedurazzi.it nei video.

Gli articoli arrivano da una rete finta (monkeypatch su requests.get): i
test non scaricano niente.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import brain
import config
import profilo


def _giorni_fa(n):
    oggi = datetime.now(ZoneInfo("Europe/Rome")).date()
    return (oggi - timedelta(days=n)).isoformat()


def _articoli():
    return [
        {"slug": "volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027",
         "titolo": "Volvo prepara un nuovo elettrico compatto per il 2027",
         "sezione": "motori", "data": _giorni_fa(1), "pubblicato": True},
        {"slug": "gomme-invernali-obbligo-dal-15-novembre",
         "titolo": "Gomme invernali 2026: obbligo dal 15 novembre, cosa si rischia",
         "sezione": "motori", "data": _giorni_fa(2), "pubblicato": True},
        # Stessa notizia ma vecchia, non pubblicata o di un'altra sezione:
        # non si scelgono mai.
        {"slug": "volvo-elettrico-compatto-vecchio",
         "titolo": "Volvo prepara un nuovo elettrico compatto",
         "sezione": "motori", "data": _giorni_fa(9), "pubblicato": True},
        {"slug": "volvo-elettrico-compatto-bozza",
         "titolo": "Volvo prepara un nuovo elettrico compatto",
         "sezione": "motori", "data": _giorni_fa(0), "pubblicato": False},
        {"slug": "gta-6-rinviato-al-2027",
         "titolo": "GTA 6 rinviato: Rockstar sposta l'uscita al 2027",
         "sezione": "gaming", "data": _giorni_fa(1), "pubblicato": True},
    ]


class _Risposta:
    def __init__(self, dati):
        self._dati = dati

    def raise_for_status(self):
        pass

    def json(self):
        return self._dati


@pytest.fixture
def rete(monkeypatch):
    """La rete finta: conta le chiamate e restituisce gli articoli."""
    chiamate = []

    def get(url, timeout=None, **kw):
        chiamate.append((url, timeout))
        return _Risposta(_articoli())

    monkeypatch.setattr(brain, "_articoli_sito", None)
    monkeypatch.setattr(brain.requests, "get", get)
    return chiamate


@pytest.fixture
def motori(monkeypatch):
    p = profilo.predefinito()
    monkeypatch.setattr(p, "argomento", "di motori")
    monkeypatch.setattr(profilo, "_attivo", p)
    monkeypatch.setattr(config, "LINGUA", "it")
    monkeypatch.setattr(config, "VIDEO_LUNGO", False)
    return p


VOLVO = {"titolo": "Volvo, nuovo elettrico compatto in arrivo",
         "descrizione": "Il SUV piu' piccolo della casa.",
         "fonte": "Volvo prepara un nuovo elettrico compatto (Motor1)",
         "gioco": "", "stile": ""}


class TestArticoloCollegato:
    def test_porta_all_articolo_con_gli_utm(self, rete, motori):
        url = brain.articolo_collegato(VOLVO)
        assert url.startswith(
            "https://www.davidedurazzi.it/articoli/"
            "volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027?")
        assert ".html" not in url
        assert "utm_source=youtube" in url
        assert "utm_medium=short" in url
        assert "utm_campaign=volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027" in url

    def test_la_rete_cambia_la_sorgente(self, rete, motori):
        assert "utm_source=tiktok" in brain.articolo_collegato(VOLVO, "tiktok")

    def test_senza_rete_l_indirizzo_e_pulito(self, rete, motori):
        assert brain.articolo_collegato(VOLVO, rete="") == (
            "https://www.davidedurazzi.it/articoli/"
            "volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027")

    def test_scarica_una_volta_sola_per_run(self, rete, motori):
        brain.articolo_collegato(VOLVO)
        brain.articolo_collegato(VOLVO, "tiktok")
        assert len(rete) == 1
        assert rete[0][0] == "https://www.davidedurazzi.it/content/articoli.json"
        assert rete[0][1] and rete[0][1] <= 10

    def test_niente_di_simile_porta_alla_home(self, rete, motori):
        url = brain.articolo_collegato({"titolo": "Benzina alle stelle oggi",
                                        "fonte": "Prezzi carburanti su (Ansa)"})
        assert url.startswith("https://www.davidedurazzi.it/?")
        assert "utm_campaign=benzina-alle-stelle-oggi" in url

    def test_una_parola_sola_non_basta(self, rete, motori):
        url = brain.articolo_collegato({"titolo": "Volvo richiama 3000 auto"})
        assert "/articoli/" not in url

    def test_articoli_vecchi_bozze_e_altre_sezioni_esclusi(self, rete, motori, monkeypatch):
        monkeypatch.setattr(brain, "_articoli_sito", [
            a for a in _articoli() if a["slug"].startswith("volvo-elettrico")])
        assert "/articoli/" not in brain.articolo_collegato(VOLVO)
        url = brain.articolo_collegato({"titolo": "GTA 6 rinviato al 2027",
                                        "fonte": "Rockstar sposta GTA 6 (IGN)"})
        assert "/articoli/" not in url

    def test_canale_gaming_legge_la_sezione_gaming(self, rete, monkeypatch):
        monkeypatch.setattr(config, "LINGUA", "it")
        url = brain.articolo_collegato({"titolo": "GTA 6 rinviato al 2027",
                                        "fonte": "Rockstar sposta GTA 6 (IGN)",
                                        "gioco": "Grand Theft Auto VI"})
        assert "/articoli/gta-6-rinviato-al-2027?" in url

    def test_rete_giu_porta_alla_home_senza_errori(self, monkeypatch, motori):
        def esplode(*a, **kw):
            raise brain.requests.ConnectionError("giu'")
        monkeypatch.setattr(brain, "_articoli_sito", None)
        monkeypatch.setattr(brain.requests, "get", esplode)
        assert brain.articolo_collegato(VOLVO).startswith("https://www.davidedurazzi.it/?")

    def test_json_rotto_porta_alla_home(self, monkeypatch, motori):
        monkeypatch.setattr(brain, "_articoli_sito", None)
        monkeypatch.setattr(brain.requests, "get",
                            lambda *a, **kw: _Risposta({"non": "una lista"}))
        assert "/articoli/" not in brain.articolo_collegato(VOLVO)

    def test_una_voce_storta_non_spegne_le_altre(self, rete, motori, monkeypatch):
        storte = [{"slug": "a", "titolo": 5, "sezione": ["motori"],
                   "data": None, "pubblicato": True},
                  {"slug": "b", "titolo": ["x"], "sezione": "motori",
                   "data": _giorni_fa(0), "pubblicato": True}]
        monkeypatch.setattr(brain, "_articoli_sito", storte + _articoli())
        assert "/articoli/volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027?" in (
            brain.articolo_collegato(VOLVO))

    def test_slug_strano_non_finisce_nell_indirizzo(self, rete, motori, monkeypatch):
        articoli = _articoli()
        articoli[0]["slug"] = "x y/../\u00e9?a=b"
        monkeypatch.setattr(brain, "_articoli_sito", articoli)
        url = brain.articolo_collegato(VOLVO)
        assert url.startswith("https://www.davidedurazzi.it/?")

    def test_senza_fusi_orari_usa_utc(self, rete, motori, monkeypatch):
        def manca(nome):
            raise brain.ZoneInfoNotFoundError(nome)
        monkeypatch.setattr(brain, "ZoneInfo", manca)
        assert "/articoli/volvo-" in brain.articolo_collegato(VOLVO)


class TestNeiTesti:
    def test_descrizione_porta_l_articolo_in_alto(self, rete, motori):
        righe = brain.costruisci_descrizione(VOLVO).split("\n")
        assert any(r.startswith("Articolo completo: https://www.davidedurazzi.it/articoli/volvo")
                   for r in righe[:3])

    def test_descrizione_senza_articolo_porta_alla_home(self, rete, motori):
        descrizione = brain.costruisci_descrizione({"titolo": "Benzina alle stelle"})
        assert "Articolo completo" not in descrizione
        assert "Altre notizie su https://www.davidedurazzi.it/?utm_source=youtube" in descrizione

    def test_descrizione_in_inglese_senza_sito(self, rete, motori, monkeypatch):
        monkeypatch.setattr(config, "LINGUA", "en")
        assert "davidedurazzi.it" not in brain.costruisci_descrizione(VOLVO)

    def test_canale_di_un_altro_argomento_senza_sito(self, rete, motori, monkeypatch):
        monkeypatch.setattr(motori, "argomento", "di cucina")
        assert "davidedurazzi.it" not in brain.costruisci_descrizione(VOLVO)
        assert "davidedurazzi.it" not in brain.costruisci_didascalia_tiktok(VOLVO)

    def test_tiktok_nomina_il_sito_senza_link(self, rete, motori):
        didascalia = brain.costruisci_didascalia_tiktok(VOLVO)
        assert "Articolo completo su davidedurazzi.it" in didascalia
        assert "https://" not in didascalia
        righe = didascalia.split("\n\n")
        assert righe[-2] == "Articolo completo su davidedurazzi.it"
        assert righe[-1].startswith("#")

    def test_tiktok_senza_articolo_non_lo_promette(self, rete, motori):
        didascalia = brain.costruisci_didascalia_tiktok({"titolo": "Benzina alle stelle"})
        assert "Articolo completo" not in didascalia
        assert "Altre notizie su davidedurazzi.it" in didascalia

    def test_cronologia_salva_l_articolo(self, rete, motori, monkeypatch):
        monkeypatch.setattr(brain.prenotazione, "apri", lambda voce: None)
        dati = dict(VOLVO, script="x" * 100, stile="", query_video="auto")
        voce = brain.prepara_voce_cronologia(dati)
        assert voce["articolo_url"] == (
            "https://www.davidedurazzi.it/articoli/"
            "volvo-prepara-un-nuovo-elettrico-compatto-per-il-2027")

    def test_cronologia_senza_articolo_niente_campo(self, rete, motori, monkeypatch):
        monkeypatch.setattr(brain.prenotazione, "apri", lambda voce: None)
        dati = {"titolo": "Benzina alle stelle", "script": "x", "stile": "",
                "query_video": "auto"}
        assert "articolo_url" not in brain.prepara_voce_cronologia(dati)
