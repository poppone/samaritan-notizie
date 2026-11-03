"""Titoli oltre i 60 caratteri: si accorciano invece di scartare lo script.

Il 1 e il 2 novembre 2026 (run 41408304757 e 41478414873) la pipeline e'
caduta con "titolo troppo lungo (63/65 caratteri, max 60)": script buoni
buttati per pochi caratteri. Ora il titolo si accorcia togliendo solo
parole, e si scarta come prima soltanto se non resta leggibile.
"""
import json

import pytest

import brain

MAX = brain.MAX_CARATTERI_TITOLO


def _coda_pulita(titolo):
    ultima = titolo.split(" ")[-1]
    assert brain._nuda(ultima) not in brain._CODE_VIETATE, titolo
    assert not titolo.endswith((":", "-", "–", "—", ",", ";")), titolo


def _solo_parole_originali(originale, accorciato):
    """Nessuna parola inventata: ogni parola viene dall'originale."""
    sorgente = {brain._nuda(p) for p in originale.split()}
    for parola in accorciato.split():
        assert brain._nuda(parola) in sorgente, (parola, accorciato)


# Titoli da 61 a 70 caratteri, nello stile del canale motori.
TITOLI_LUNGHI = [
    "Alfa Romeo Tonale 2027: nuovo pacchetto sportivo e motore ibrido",
    "Ferrari 849 Testarossa: prezzo, motore e consegne in Italia nel 2027",
    "Porsche 911 GT3 RS, il nuovo record al Nürburgring è ufficiale oggi",
    "Lamborghini Temerario: la prova su strada della nuova supercar ibrida",
    "Fiat Grande Panda elettrica: perché costa meno della concorrenza",
    "Alfa Romeo Junior Ibrida Q4: la prova su strada in montagna e città",
    "Mercedes CLA elettrica, autonomia record nella prova di Quattroruote",
    "Renault 5 Turbo 3E (prezzo e uscita in Italia confermati dalla casa)",
    "Toyota GR Yaris: aggiornamento software per il cambio automatico 🔥",
    "La Ducati Panigale V4 R vince ancora: ecco la nuova versione stradale",
]


@pytest.mark.parametrize("titolo", TITOLI_LUNGHI)
def test_titoli_da_61_a_70_caratteri_rientrano_puliti(titolo):
    assert 61 <= len(titolo) <= 70, len(titolo)
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato, titolo
    assert brain.MIN_CARATTERI_TITOLO_ACCORCIATO <= len(accorciato) <= MAX
    _coda_pulita(accorciato)
    _solo_parole_originali(titolo, accorciato)
    # L'inizio, dove sta il soggetto della notizia, resta quello.
    assert accorciato.split()[0] == titolo.split()[0]


@pytest.mark.parametrize("lunghezza", range(61, 71))
def test_ogni_lunghezza_da_61_a_70(lunghezza):
    base = ("Volkswagen ID. Polo elettrica: autonomia, prezzo e data di "
            "uscita ufficiale in Italia per tutti")
    titolo = base[:lunghezza].rstrip()
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato and len(accorciato) <= MAX
    _coda_pulita(accorciato)
    _solo_parole_originali(titolo, accorciato)


def test_entro_il_limite_non_cambia():
    titolo = "Alfa Romeo Tonale: nuovo pacchetto sportivo"
    assert brain.accorcia_titolo(titolo) == titolo


def test_prima_toglie_emoji_e_punteggiatura_finale():
    titolo = "Porsche 911 GT3 RS: il record al Nürburgring è ufficiale!!! 🚗🔥"
    assert len(titolo) > MAX
    assert brain.accorcia_titolo(titolo) == \
        "Porsche 911 GT3 RS: il record al Nürburgring è ufficiale"


def test_il_punto_di_domanda_resta():
    titolo = "Tesla Model Y Juniper: conviene davvero rispetto alla vecchia? 🤔"
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato == "Tesla Model Y Juniper: conviene rispetto alla vecchia?"


def test_poi_toglie_le_parole_riempitive_senza_tagliare():
    titolo = "Ecco la nuova BMW M3 Touring elettrica, addirittura 700 cavalli"
    assert len(titolo) > MAX
    assert brain.accorcia_titolo(titolo) == \
        "La nuova BMW M3 Touring elettrica, 700 cavalli"


def test_accenti_conservati_e_contati_come_un_carattere():
    titolo = ("Citroën ë-C3: perché è l'elettrica più venduta in città "
              "quest'anno")
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato and len(accorciato) <= MAX
    assert accorciato.startswith("Citroën ë-C3")
    _coda_pulita(accorciato)


def test_titolo_con_due_punti_non_resta_appeso():
    # Il taglio cadrebbe dopo "Torino: nuovo", un frammento: meglio fermarsi
    # prima dei due punti, senza lasciarli in fondo.
    titolo = "Alfa Romeo Tonale debutta al Salone di Torino: nuovo pacchetto"
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato == "Alfa Romeo Tonale debutta al Salone di Torino"


def test_la_subordinata_spezzata_si_toglie():
    titolo = ("Elden Ring: il boss segreto che quasi nessun giocatore "
              "ha mai battuto davvero")
    assert brain.accorcia_titolo(titolo) == "Elden Ring: il boss segreto"


def test_niente_congiunzioni_o_preposizioni_in_coda():
    titolo = "Alfa Romeo Tonale debutta al Salone di Torino con un nuovo pacchetto"
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato == "Alfa Romeo Tonale debutta al Salone di Torino"


def test_parentesi_aperta_chiusa_o_tolta():
    titolo = "Nuova Renault 5 Turbo (prezzo e uscita in Italia confermati dalla casa)"
    accorciato = brain.accorcia_titolo(titolo)
    assert accorciato.count("(") == accorciato.count(")")
    assert len(accorciato) <= MAX


def test_se_resta_incomprensibile_si_scarta():
    # Una sola parola lunghissima dopo i due punti: tagliando resterebbe
    # "BMW", che da solo non dice niente.
    titolo = "BMW: " + "x" * 70
    assert brain.accorcia_titolo(titolo) == ""
    ok, motivo = brain.valida_titolo(titolo, "")
    assert not ok and "troppo lungo" in motivo


class TestNellaPipeline:
    """Il titolo accorciato arriva dove serve: risultato, cronologia,
    prenotazione, e da li' YouTube e la didascalia TikTok."""

    _SCRIPT = (
        "Nessuno lo trova al primo giro in tutta la regione iniziale del gioco. "
        "Dietro la cascata piu' grande c'e' una porta che sembra decorazione. "
        "Si apre soltanto suonando la campana trovata nella cripta a nord, e "
        "dentro ti aspetta un boss che nessuna guida italiana ha mai filmato "
        "per davvero. Ti lascia un'arma che cambia completamente la build. "
        "Provaci stasera prima di andare avanti con la storia principale. "
        "Nessuno lo trova al primo giro."
    )

    def _finto_client(self, risposte):
        class FinteCompletions:
            @staticmethod
            def create(**kw):
                class Scelta:
                    class message:
                        content = risposte.pop(0)

                class Risposta:
                    choices = [Scelta()]

                return Risposta()

        class FintoClient:
            class chat:
                completions = FinteCompletions()

        return FintoClient()

    def test_il_titolo_lungo_si_accorcia_al_primo_tentativo(self, monkeypatch):
        lungo = ("Elden Ring: il boss segreto che quasi nessun giocatore "
                 "ha mai battuto davvero")
        risposta = json.dumps({
            "titolo": lungo, "script": self._SCRIPT,
            "gioco": "Elden Ring", "query_video": "elden ring gameplay",
            "descrizione": "Un segreto.", "indice_notizia": -1,
        })
        cronologia, prenotati = [], []
        monkeypatch.setattr(brain, "client", self._finto_client([risposta]))
        monkeypatch.setattr(brain, "recupera_trend_gaming_online", lambda **k: [])
        monkeypatch.setattr(brain, "carica_cronologia", lambda: [])
        monkeypatch.setattr(brain, "prepara_voce_cronologia",
                            lambda r: cronologia.append(r["titolo"]))
        monkeypatch.setattr(brain.prenotazione, "prenota", prenotati.append)

        risultato = brain.genera_script_samaritan()

        assert risultato["titolo"] == "Elden Ring: il boss segreto"
        assert cronologia == [risultato["titolo"]]
        assert prenotati == [risultato["titolo"]]
        didascalia = brain.costruisci_didascalia_tiktok(risultato)
        assert risultato["titolo"] in didascalia
        assert lungo not in didascalia
