"""Il controllo anti-invenzioni non deve scartare le riformulazioni del titolo.

Casi veri del 5 novembre 2026 (Motori in 60 secondi, run #183 e #185): il
fact-checker aveva bocciato come "dettaglio inventato" una frase che diceva
la stessa cosa del titolo con un altro verbo, e l'uscita e' saltata.
"""
import json

import pytest

import brain


TITOLO_BREMBO = ("Brembo, dalla MotoGP alla strada: a Eicma debutta la nuova "
                 "generazione di freni")
SOMMARIO_BREMBO = ("A Eicma 2026 Brembo presenta la nuova generazione di freni "
                   "nata dalle corse e destinata alle auto di serie.")
TITOLO_MIRAFIORI = "Stellantis, Mirafiori ferma fino a fine mese: cassa integrazione"


class TestRiformulazioni:
    def test_il_caso_brembo_e_una_riformulazione(self):
        assert brain.e_riformulazione(
            "Brembo ha lanciato la nuova generazione di freni a Eicma",
            TITOLO_BREMBO)

    def test_un_fatto_del_sommario_non_e_inventato(self):
        assert brain.e_riformulazione(
            "La tecnologia e' destinata alle auto di serie",
            TITOLO_BREMBO, SOMMARIO_BREMBO)

    def test_un_fatto_inventato_resta_segnalato(self):
        # Nessuna di queste parole, nomi o numeri sta nel titolo: e' nuovo.
        assert not brain.e_riformulazione(
            "La chiusura e' stata causata da un disaccordo tra Stellantis e "
            "i sindacati sulle ore di straordinario", TITOLO_MIRAFIORI)

    def test_un_nome_nuovo_e_un_fatto_nuovo(self):
        assert not brain.e_riformulazione(
            "Il provvedimento e' stato annunciato dal sindacato FIOM",
            TITOLO_MIRAFIORI)

    def test_un_numero_nuovo_e_un_fatto_nuovo(self):
        assert not brain.e_riformulazione(
            "I nuovi freni costano 2.400 euro", TITOLO_BREMBO, SOMMARIO_BREMBO)

    def test_il_filtro_tiene_solo_i_dettagli_nuovi(self):
        dettagli = [
            "Brembo ha lanciato la nuova generazione di freni a Eicma",
            "I nuovi freni promettono miglioramenti significativi per i guidatori",
            "La collaborazione con Eicma porta innovazioni di performance e durata",
        ]
        tenuti = brain.senza_riformulazioni(dettagli, TITOLO_BREMBO, SOMMARIO_BREMBO)
        assert dettagli[0] not in tenuti
        # "promettono miglioramenti per i guidatori" e "innovazioni di
        # performance e durata" non stanno ne' nel titolo ne' nel sommario.
        assert dettagli[1] in tenuti and dettagli[2] in tenuti

    def test_una_lista_vuota_resta_vuota(self):
        assert brain.senza_riformulazioni([], TITOLO_BREMBO) == []


class TestRiparaJson:
    def test_legge_un_json_corretto(self):
        assert brain._ripara_json('{"titolo": "A", "script": "B"}') == {
            "titolo": "A", "script": "B"}

    def test_ripara_le_chiavi_senza_virgolette(self):
        # Il caso del 5 novembre 2026: "Expecting property name enclosed in
        # double quotes" a riga 5.
        testo = '{\n  "titolo": "A",\n  "script": "B",\n  query_video: "C",\n  "indice_notizia": 0,\n}'
        assert brain._ripara_json(testo)["query_video"] == "C"

    def test_ripara_apici_e_recinzione(self):
        testo = "```json\n{\n  'titolo': \"A\",\n  'script': 'B'\n}\n```"
        assert brain._ripara_json(testo)["titolo"] == "A"

    def test_se_non_si_ripara_solleva_valueerror(self):
        with pytest.raises(ValueError):
            brain._ripara_json("non e' json per niente")


def test_video_saltato_e_un_runtimeerror():
    # main.py lo distingue da un errore vero, ma chi non lo conosce lo
    # tratta ancora come prima.
    assert issubclass(brain.VideoSaltato, RuntimeError)
