"""La notizia scelta si prenota subito, non a video finito.

Il 30 settembre 2026 sul canale notizie due lavorazioni lanciate a mano a
cinquanta secondi di distanza (le uscite delle 14:00 e delle 18:00) hanno
scelto la stessa notizia, Sanremo condotto da De Martino. Ciascuna ha letto
la memoria del repository com'era alla partenza e l'ha salvata solo dieci
minuti dopo, a video caricato: nessuna delle due poteva sapere dell'altra.

Adesso la lavorazione, prima di scegliere, riprende la memoria e le
prenotazioni salvate nel frattempo da altre (riallinea_cronologia), e appena
ha lo script salva la sua prenotazione sul repository (prenota), prima di
montare il video. Chi sceglie dopo la trova e la notizia gli risulta gia'
usata. Resta scoperto solo il caso di due lavorazioni che scelgono nello
stesso minuto.

La prenotazione NON e' una riga di cronologia. Fino al 12 ottobre 2026 lo
era: la riga si scriveva appena lo script era pronto, e una lavorazione
morta a meta' lasciava in cronologia un video mai uscito. Adesso la
prenotazione vive in prenotazioni.json, scade da sola dopo ORE_VALIDITA, e
la riga di cronologia la scrive brain.registra_video_caricato solo quando
YouTube ha restituito l'identificativo del video.

Gira solo nel workflow (SAMARITAN_PRENOTA=1): in locale e nei test non tocca
git. Ogni errore si stampa e si ignora: una prenotazione mancata non deve
fermare un video.
"""
import json
import os
import subprocess
import time

import config
from unisci_memoria import unisci_cronologie

TENTATIVI = 3

# Quanto resta valida una prenotazione. Una lavorazione dura una decina di
# minuti (il video lungo fino a due ore): passate sei ore la lavorazione che
# l'ha fatta o ha caricato il video, e allora la notizia sta in cronologia, o
# e' morta, e allora la notizia deve tornare libera per la riserva.
ORE_VALIDITA = 6

# La riga della lavorazione in corso: nasce con lo script, si arricchisce
# durante il montaggio (veste, voce) e diventa una riga di cronologia solo a
# caricamento riuscito.
_IN_CORSO = None


def attiva():
    return os.environ.get("SAMARITAN_PRENOTA", "").strip() == "1"


def _ramo():
    return os.environ.get("GITHUB_REF_NAME", "").strip() or "main"


def _git(*argomenti, env=None):
    return subprocess.run(["git", *argomenti], capture_output=True, text=True,
                          timeout=60, cwd=config.DIR_PROGETTO,
                          env={**os.environ, **(env or {})})


def _nel_repo(percorso):
    """Il percorso di un file come lo vuole git, relativo al repo."""
    return os.path.relpath(percorso, config.DIR_PROGETTO)


def _lista_remota(percorso):
    """Il contenuto di un file-lista sul repository adesso, o None se non si legge."""
    ramo = _ramo()
    if _git("fetch", "-q", "origin", ramo).returncode != 0:
        return None
    letto = _git("show", f"origin/{ramo}:{_nel_repo(percorso)}")
    if letto.returncode != 0:
        return []          # il file non c'e' ancora
    try:
        dati = json.loads(letto.stdout)
    except ValueError:
        return None
    return dati if isinstance(dati, list) else None


def _leggi(percorso):
    try:
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
        return dati if isinstance(dati, list) else []
    except (OSError, ValueError):
        return []


def _scrivi(percorso, dati):
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)


def _valide(prenotazioni, adesso=None):
    """Solo le prenotazioni non ancora scadute."""
    adesso = adesso if adesso is not None else time.time()
    limite = adesso - ORE_VALIDITA * 3600
    return [p for p in prenotazioni or []
            if isinstance(p, dict) and (p.get("timestamp") or 0) >= limite]


# ------------------------------------------------------- riga in corso
def apri(voce):
    """Registra la riga di questa lavorazione e la prenota in locale."""
    global _IN_CORSO
    _IN_CORSO = voce
    try:
        _scrivi(config.FILE_PRENOTAZIONI,
                _valide(unisci_cronologie(_leggi(config.FILE_PRENOTAZIONI), [voce])))
    except OSError as e:
        print(f"[Prenotazione] Prenotazione locale non scritta: {e}")


def voce_in_corso():
    return _IN_CORSO


def annota(campo, valore):
    """Aggiunge un campo alla riga in corso (la veste, la voce). False se non c'e'."""
    if not isinstance(_IN_CORSO, dict):
        return False
    _IN_CORSO[campo] = valore
    return True


def chiudi():
    """Toglie la riga in corso: il video e' in cronologia, o non uscira'."""
    global _IN_CORSO
    voce, _IN_CORSO = _IN_CORSO, None
    if not isinstance(voce, dict):
        return
    chiave = (voce.get("timestamp"), voce.get("titolo"))
    try:
        rimaste = [p for p in _leggi(config.FILE_PRENOTAZIONI)
                   if not (isinstance(p, dict)
                           and (p.get("timestamp"), p.get("titolo")) == chiave)]
        _scrivi(config.FILE_PRENOTAZIONI, _valide(rimaste))
    except OSError:
        pass


def attive(adesso=None):
    """Le notizie prenotate e non scadute, da trattare come gia' usate."""
    return _valide(_leggi(config.FILE_PRENOTAZIONI), adesso)


# ------------------------------------------------------------ sul remoto
def riallinea_cronologia():
    """Aggiunge in locale la cronologia e le prenotazioni salvate da altre lavorazioni."""
    if not attiva():
        return False
    try:
        remota = _lista_remota(config.FILE_CRONOLOGIA)
        if remota is None:
            print("[Prenotazione] Memoria remota non leggibile, proseguo con la mia.")
            return False
        _scrivi(config.FILE_CRONOLOGIA,
                unisci_cronologie(remota, _leggi(config.FILE_CRONOLOGIA)))
        prenotate = _lista_remota(config.FILE_PRENOTAZIONI)
        if prenotate is not None:
            _scrivi(config.FILE_PRENOTAZIONI, _valide(
                unisci_cronologie(prenotate, _leggi(config.FILE_PRENOTAZIONI))))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[Prenotazione] Riallineo non riuscito: {e}")
        return False


def _commit_sul_remoto(ramo, percorso, testo):
    """Un commit sopra origin/ramo che cambia solo il file indicato.

    Si costruisce con un indice a parte e non si tocca il ramo locale: il
    passo finale del workflow salva la memoria come ha sempre fatto, e se
    trova il remoto avanti unisce con unisci_memoria.py.
    """
    indice = os.path.join(config.DIR_PROGETTO, ".git", "indice-prenotazione")
    env = {"GIT_INDEX_FILE": indice,
           "GIT_AUTHOR_NAME": "Samaritan Bot",
           "GIT_AUTHOR_EMAIL": "bot@samaritan.local",
           "GIT_COMMITTER_NAME": "Samaritan Bot",
           "GIT_COMMITTER_EMAIL": "bot@samaritan.local"}
    try:
        blob = _git("hash-object", "-w", "--", _nel_repo(percorso))
        if blob.returncode != 0:
            return None
        passi = [
            ("read-tree", f"origin/{ramo}"),
            ("update-index", "--add", "--cacheinfo",
             f"100644,{blob.stdout.strip()},{_nel_repo(percorso)}"),
        ]
        for passo in passi:
            if _git(*passo, env=env).returncode != 0:
                return None
        albero = _git("write-tree", env=env)
        if albero.returncode != 0:
            return None
        commit = _git("commit-tree", albero.stdout.strip(), "-p", f"origin/{ramo}",
                      "-m", testo, env=env)
        return commit.stdout.strip() if commit.returncode == 0 else None
    finally:
        if os.path.exists(indice):
            os.remove(indice)


def prenota(titolo=""):
    """Salva sul repository le prenotazioni con quella appena fatta.

    Tocca solo prenotazioni.json: la cronologia sul repository resta quella
    dei video davvero caricati.
    """
    if not attiva():
        return False
    try:
        ramo = _ramo()
        nostre = _leggi(config.FILE_PRENOTAZIONI)
        for _ in range(TENTATIVI):
            remote = _lista_remota(config.FILE_PRENOTAZIONI)
            if remote is None:
                break
            _scrivi(config.FILE_PRENOTAZIONI,
                    _valide(unisci_cronologie(remote, nostre)))
            commit = _commit_sul_remoto(ramo, config.FILE_PRENOTAZIONI,
                                        "Prenotazione notizia Samaritan [skip ci]")
            if not commit:
                break
            if _git("push", "-q", "origin", f"{commit}:refs/heads/{ramo}").returncode == 0:
                print(f"[Prenotazione] Notizia prenotata: {titolo}")
                return True
        print("[Prenotazione] Non riuscita: la notizia resta prenotata solo qui.")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"[Prenotazione] Non riuscita: {e}")
        return False
