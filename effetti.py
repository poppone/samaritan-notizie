"""
Gli effetti del montaggio dello Short: quello che fa dire "wow" nei primi
secondi e tiene l'occhio incollato fino alla fine.

  1. AMO: nei primi due secondi il titolo entra enorme con uno scatto (zoom
     che parte grande e si ferma) e un "whoosh"; anche lo sfondo parte con
     uno zoom veloce.
  2. STACCHI A TEMPO: un cambio d'immagine ogni 1,5-2 secondi, tagliato dove
     la voce prende fiato (fine frase o pausa), non a caso in mezzo a una
     parola.
  3. SOTTOTITOLI CHE SI ACCENDONO: una riga di poche parole, quella detta in
     quel momento accesa e piu' grande; numeri, prezzi, percentuali e nomi
     propri in un colore forte.
  4. TRANSIZIONI E SUONI: un lampo bianco di due-tre fotogrammi sullo stacco,
     un "pop" quando la voce dice un numero importante.
  5. FINALE: gli ultimi due secondi invitano a seguire il canale.

Qui sta solo la LOGICA (dove tagliare, cosa evidenziare, che suono fare):
il montaggio vero, con moviepy, sta in maker.py. Cosi' le scelte si possono
verificare nei test senza moviepy, che nella suite non c'e' per scelta.

I suoni NON si scaricano: si generano qui con numpy (importato solo quando
serve), quindi non ci sono file audio da tenere nel repo ne' licenze da
controllare.
"""
import os
import re

import config

# Durata dell'amo iniziale (titolo enorme) e del finale, in secondi.
SECONDI_AMO = 1.9
SECONDI_FINALE = 2.0

# Quanto deve durare almeno l'ultimo stacco: piu' corto si vede come un
# errore di montaggio, quindi si accorpa al precedente.
STACCO_MINIMO_FINALE = 0.8

# Una pausa fra due parole oltre questa soglia e' un buon posto per tagliare.
PAUSA_DI_TAGLIO = 0.12

# Di quanto si allarga la finestra di taglio [minimo, massimo] per andare a
# prendere una fine frase o una virgola: uno stacco un po' piu' corto o piu'
# lungo si nota meno di uno stacco che spezza la frase.
ANTICIPO_TAGLIO = 0.4
RITARDO_TAGLIO = 0.6

# I lampi bianchi: pochi e sugli stacchi che contano (la fine dell'amo e
# qualche fine frase), lontani fra loro. Su ogni stacco stancano e tolgono
# peso proprio agli stacchi importanti: per gli altri basta lo scatto di zoom.
MAX_LAMPI = 3
DISTANZA_MIN_LAMPI = 5.0

# Volumi degli effetti, in frazione del fondo scala. La voce resta sopra:
# gli effetti si sentono, non coprono.
VOLUME_WHOOSH = 0.30
VOLUME_POP = 0.22

# Al massimo un pop ogni tanto: dieci "ding" in mezzo minuto stancano.
DISTANZA_MIN_POP = 1.6
MAX_POP = 7

FREQUENZA_AUDIO = 44100

# Dove cercare il logo del canale, in ordine. Se non c'e', il finale e' solo
# testo animato.
PERCORSI_LOGO = ("logo.png", "assets/logo.png", "assets/logo-512.png",
                 "clip_mie/logo.png")

INVITO_FINALE = {"it": "SEGUICI", "en": "FOLLOW US"}

# Lo stesso invito detto dalla voce, in coda allo script (Davide, 29/10/2026:
# "integra nella voce la parte finale"). Il finale a schermo parte quando la
# voce dice la prima parola dell'invito.
INVITO_PARLATO = {"it": "Seguici", "en": "Follow"}

# Fra quante parole in fondo si cerca l'inizio dell'invito detto dalla voce.
PAROLE_CODA_INVITO = 12

_FINE_FRASE = ".!?;:"
_FINE_INCISO = ","

# Parole che, dette dopo un numero, ne fanno un prezzo o una quantita'
# importante ("18 mila euro", "20 per cento").
_UNITA = {
    "euro", "€", "dollari", "$", "mila", "milioni", "miliardi", "percento",
    "cento", "%", "km", "cavalli", "cv", "kw", "kwh", "chilometri", "anni",
    "dollars", "million", "billion", "percent", "thousand", "miles", "hp",
}
_NUMERI_A_PAROLE = {
    "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove",
    "dieci", "venti", "trenta", "quaranta", "cinquanta", "cento", "mille",
    "mila", "milioni", "miliardi", "one", "two", "three", "four", "five",
    "ten", "hundred", "thousand", "million", "billion",
}
# Parole maiuscole che non sono nomi propri anche fuori dall'inizio frase.
_NON_NOMI = {"I", "E", "A", "O"}

_RE_NUMERO = re.compile(r"\d")
_RE_PUNTEGGIATURA = re.compile(r"^[\"'‘’“”(\[]+|[\"'‘’“”)\].,!?;:]+$")


def _nudo(parola):
    """La parola senza punteggiatura e virgolette ai bordi."""
    precedente = None
    parola = (parola or "").strip()
    while precedente != parola:
        precedente = parola
        parola = _RE_PUNTEGGIATURA.sub("", parola)
    return parola


# ===========================================================================
# STACCHI A TEMPO CON LA VOCE
# ===========================================================================
def _continua_un_numero(parole, i):
    """True se la parola i e' il seguito di una cifra appena detta ("18.900
    | euro", "20 | per | cento", "100 | mila"): li' non si taglia."""
    if i <= 0:
        return False
    nuda = _nudo(parole[i].get("parola") or "").lower()
    prima = _nudo(parole[i - 1].get("parola") or "").lower()
    dopo = (_nudo(parole[i + 1].get("parola") or "").lower()
            if i + 1 < len(parole) else "")
    prima_numero = e_numero(prima) or prima in _UNITA
    if nuda == "per":
        return prima_numero and dopo == "cento"
    if nuda == "cento" and prima == "per":
        return True
    return prima_numero and (e_numero(nuda) or nuda in _UNITA)


def _candidati_di_taglio(parole):
    """[(istante, peso)]: i punti dove tagliare non si nota.

    Peso 3 a fine frase, 2 su una virgola, 1 su una pausa, 0 all'inizio di
    una parola qualunque (sempre meglio che in mezzo a una parola), ma non
    dentro un prezzo o una quantita' ("18.900 euro" non si spezza).
    """
    candidati = []
    for i, p in enumerate(parole):
        testo = (p.get("parola") or "").strip()
        fine = float(p["fine"])
        prossima = float(parole[i + 1]["inizio"]) if i + 1 < len(parole) else None
        pausa = (prossima - fine) if prossima is not None else 0.0
        # Il taglio cade a meta' della pausa: ne' sulla coda della parola
        # prima ne' sull'attacco di quella dopo.
        istante = fine + max(pausa, 0.0) / 2 if prossima is not None else fine
        if testo and testo[-1] in _FINE_FRASE:
            candidati.append((istante, 3))
        elif testo and testo[-1] in _FINE_INCISO:
            candidati.append((istante, 2))
        elif pausa >= PAUSA_DI_TAGLIO:
            candidati.append((istante, 1))
        if i > 0 and not _continua_un_numero(parole, i):
            candidati.append((float(p["inizio"]), 0))
    return candidati


def punti_di_stacco(parole, durata_totale, minimo=1.5, massimo=2.0):
    """Gli istanti in cui cambiare immagine, 0 compreso.

    Dall'ultimo stacco si cerca prima una fine frase o una virgola nella
    finestra allargata [minimo - ANTICIPO_TAGLIO, massimo + RITARDO_TAGLIO]:
    e' li' che il taglio cade a tempo con la voce. Se non c'e', si prende il
    punto migliore della finestra [minimo, massimo] (pausa > inizio parola);
    se nemmeno li' c'e' niente, l'inizio parola o la pausa piu' vicina al
    centro nella finestra allargata. A pari merito vince il piu' vicino al
    centro. Il ritmo fisso resta solo dove la voce manca davvero.
    """
    minimo = max(float(minimo), 0.3)
    massimo = max(float(massimo), minimo)
    parole = parole or []
    candidati = _candidati_di_taglio(parole)
    punti = [0.0]
    while True:
        ultimo = punti[-1]
        if durata_totale - ultimo <= massimo:
            break
        da, a = ultimo + minimo, ultimo + massimo
        centro = (da + a) / 2
        largo_da = ultimo + max(minimo - ANTICIPO_TAGLIO, 0.3)
        largo_a = ultimo + massimo + RITARDO_TAGLIO

        def migliore(scelta):
            return max(scelta, key=lambda c: (c[1], -abs(c[0] - centro)))[0]

        nel_largo = [(t, peso) for t, peso in candidati if largo_da <= t <= largo_a]
        forti = [c for c in nel_largo if c[1] >= 2]
        stretti = [c for c in nel_largo if da <= c[0] <= a]
        if forti:
            scelto = migliore(forti)
        elif stretti:
            scelto = migliore(stretti)
        elif nel_largo:
            scelto = min(nel_largo, key=lambda c: abs(c[0] - centro))[0]
        else:
            scelto = centro
            # Senza candidati la voce tace (o e' un'unica parola lunghissima):
            # in ogni caso mai a meta' parola, si sposta alla sua fine.
            for p in parole:
                if float(p["inizio"]) < scelto < float(p["fine"]):
                    scelto = float(p["fine"])
                    break
        if durata_totale - scelto < STACCO_MINIMO_FINALE:
            break
        punti.append(round(scelto, 3))
    return punti


def punti_dei_lampi(punti, parole, massimo=MAX_LAMPI,
                    distanza=DISTANZA_MIN_LAMPI):
    """Gli stacchi su cui mettere il lampo bianco: pochi, scelti.

    Il primo stacco (quello che chiude l'amo) e poi solo stacchi caduti a
    fine frase, almeno `distanza` secondi dopo il lampo precedente, al
    massimo `massimo` in tutto. Senza parole resta solo il primo.
    """
    fini_frase = [t for t, peso in _candidati_di_taglio(parole or []) if peso >= 3]
    scelti = []
    for t in punti or []:
        if t <= 0:
            continue
        if not scelti:
            scelti.append(t)
        elif (t - scelti[-1] >= distanza
              and any(abs(t - f) < 0.01 for f in fini_frase)):
            scelti.append(t)
        if len(scelti) >= massimo:
            break
    return scelti


def segmenti_da_punti(punti, durata_totale):
    """[(inizio, durata)] da una lista di punti di stacco."""
    confini = list(punti) + [durata_totale]
    return [(confini[i], confini[i + 1] - confini[i])
            for i in range(len(punti)) if confini[i + 1] > confini[i]]


def ordine_sorgenti(n_sorgenti, n_segmenti, primo_video=None):
    """L'indice della sorgente per ogni stacco, senza mai ripetere la stessa
    due volte di fila (finche' ce n'e' piu' di una)."""
    if n_sorgenti <= 0:
        return []
    ordine = []
    for i in range(n_segmenti):
        indice = i % n_sorgenti
        if ordine and indice == ordine[-1] and n_sorgenti > 1:
            indice = (indice + 1) % n_sorgenti
        ordine.append(indice)
    return ordine


# ===========================================================================
# PAROLE CHIAVE E RIGHE DEI SOTTOTITOLI
# ===========================================================================
def e_numero(parola):
    nuda = _nudo(parola).lower()
    if not nuda:
        return False
    return bool(_RE_NUMERO.search(nuda)) or nuda in _NUMERI_A_PAROLE or "%" in nuda or "€" in nuda


def tipo_parola(parole, indice, parole_titolo=()):
    """'numero', 'nome' o '' per la parola in posizione `indice`.

    - numero: cifre, percentuali, prezzi, e le unita' subito dopo un numero
      ("18 MILA EURO" si accende tutto, non solo il 18);
    - nome: parola con l'iniziale maiuscola che non apre la frase (Ferrari,
      Stellantis), o un nome proprio del titolo (scritto maiuscolo li').
    """
    testo = (parole[indice].get("parola") or "").strip()
    nuda = _nudo(testo)
    if not nuda:
        return ""
    if e_numero(nuda):
        return "numero"
    if indice > 0 and nuda.lower() in _UNITA:
        prima = _nudo(parole[indice - 1].get("parola") or "")
        if e_numero(prima) or prima.lower() in _UNITA:
            return "numero"
    inizio_frase = indice == 0 or (
        (parole[indice - 1].get("parola") or "").strip()[-1:] in _FINE_FRASE
        # Una pausa lunga prima della parola vale come un punto: certe voci
        # danno i tempi delle parole senza la punteggiatura.
        or float(parole[indice]["inizio"]) - float(parole[indice - 1]["fine"]) > 0.3)
    if (nuda[0].isupper() and not inizio_frase and nuda not in _NON_NOMI
            and len(nuda) > 1):
        return "nome"
    if nuda.upper() in parole_titolo:
        return "nome"
    return ""


def _chiave(testo):
    return re.sub(r"[^\w]", "", (testo or "").lower())


def ripunteggia(parole, testo):
    """Rimette alle parole la punteggiatura del testo letto dalla voce.

    Alcune voci danno i tempi parola per parola ma senza punti e virgole, e
    senza punteggiatura non si sa dove finisce una frase (dove tagliare, dove
    chiudere una riga di sottotitoli). Si scorrono insieme le parole e il
    testo: dove coincidono, la parola prende la punteggiatura che la segue
    nel testo. Dove non coincidono (numeri letti in lettere, sigle) resta
    com'e'. Ritorna una lista nuova, l'originale non si tocca.
    """
    gettoni = (testo or "").split()
    risultato, j = [], 0
    for p in parole or []:
        nuova = dict(p)
        chiave = _chiave(p.get("parola"))
        for avanti in range(j, min(j + 4, len(gettoni))):
            if chiave and _chiave(gettoni[avanti]) == chiave:
                coda = re.search(r"[.,!?;:]+[\"'\u2019\u201d)]*$", gettoni[avanti])
                parola = (p.get("parola") or "").rstrip(".,!?;:")
                if coda:
                    parola += coda.group(0).rstrip("\"'\u2019\u201d)")
                nuova["parola"] = parola
                j = avanti + 1
                break
        risultato.append(nuova)
    return risultato


def parole_del_titolo(*testi):
    """I nomi propri di titolo e soggetto, in maiuscolo.

    Conta solo chi nel titolo e' scritto con l'iniziale maiuscola (Fiat,
    Panda), non "costa" o "ibrida": se si accendesse ogni parola del titolo
    l'evidenza sarebbe sempre accesa e non direbbe piu' niente. Un testo
    tutto in maiuscolo o con tutte le iniziali maiuscole non dice quali sono
    i nomi, e non conta.
    """
    nomi = set()
    for testo in testi:
        parole = re.findall(r"\b[^\W\d_]{3,}\b", testo or "")
        if not parole:
            continue
        maiuscole = [w for w in parole if w[0].isupper()]
        if testo.upper() == testo or len(maiuscole) > len(parole) * 0.6:
            continue
        nomi.update(w.upper() for w in maiuscole)
    return nomi


def raggruppa_parole(parole, max_parole=3, max_caratteri=16, pausa=0.35):
    """Le parole divise in righe brevi da mostrare una alla volta.

    Una riga si chiude dopo `max_parole`, se supererebbe `max_caratteri`, a
    fine frase o virgola, e prima di una pausa lunga: il sottotitolo segue il
    respiro della voce. Ritorna liste di indici in `parole`.
    """
    righe, corrente, lunghezza = [], [], 0
    for i, p in enumerate(parole):
        testo = (p.get("parola") or "").strip()
        if not testo:
            continue
        aggiunta = len(testo) + (1 if corrente else 0)
        if corrente and (len(corrente) >= max_parole
                         or lunghezza + aggiunta > max_caratteri):
            righe.append(corrente)
            corrente, lunghezza, aggiunta = [], 0, len(testo)
        corrente.append(i)
        lunghezza += aggiunta
        prossima = parole[i + 1]["inizio"] if i + 1 < len(parole) else None
        if (testo[-1] in _FINE_FRASE + _FINE_INCISO
                or (prossima is not None and prossima - p["fine"] > pausa)):
            righe.append(corrente)
            corrente, lunghezza = [], 0
    if corrente:
        righe.append(corrente)
    return righe


def momenti_pop(parole, minimo_distanza=DISTANZA_MIN_POP, massimo=MAX_POP):
    """Gli istanti in cui suonare il "pop": quando la voce dice un numero.

    Una cifra seguita dalla sua unita' ("18 mila euro") fa un pop solo, sul
    primo pezzo; e mai due pop piu' vicini di `minimo_distanza`.
    """
    istanti = []
    for i, p in enumerate(parole or []):
        if tipo_parola(parole, i) != "numero":
            continue
        if i > 0 and tipo_parola(parole, i - 1) == "numero":
            continue
        t = float(p["inizio"])
        if istanti and t - istanti[-1] < minimo_distanza:
            continue
        istanti.append(t)
        if len(istanti) >= massimo:
            break
    return istanti


# ===========================================================================
# FINALE
# ===========================================================================
def testi_finale(nome_canale, handle="", lingua="it"):
    """Le righe del finale: invito, nome del canale, handle."""
    invito = INVITO_FINALE.get(lingua, INVITO_FINALE["it"])
    righe = [invito]
    if nome_canale:
        righe.append(nome_canale.strip())
    if handle and handle.strip().lower() != (nome_canale or "").strip().lower():
        righe.append(handle.strip())
    return righe


def frase_finale_parlata(nome_canale, lingua="it"):
    """L'invito che la voce dice in fondo allo Short, o "" senza nome canale."""
    nome = (nome_canale or "").strip()
    if not nome:
        return ""
    return f"{INVITO_PARLATO.get(lingua, INVITO_PARLATO['it'])}: {nome}."


def indice_invito_parlato(parole, lingua="it"):
    """L'indice della parola con cui la voce comincia l'invito finale.

    Si cerca solo fra le ultime PAROLE_CODA_INVITO parole, dall'ultima: lo
    script stesso potrebbe dire "seguici" prima. None se non c'e'.
    """
    invito = INVITO_PARLATO.get(lingua, INVITO_PARLATO["it"]).lower()
    parole = parole or []
    for i in range(len(parole) - 1, max(len(parole) - PAROLE_CODA_INVITO, 0) - 1, -1):
        testo = re.sub(r"[^\w]", "", str(parole[i].get("parola", ""))).lower()
        if testo == invito:
            return i
    return None


def trova_logo(radice=None):
    """Il percorso del logo del canale, o None se nel repo non c'e'."""
    radice = radice or config.DIR_PROGETTO
    for relativo in PERCORSI_LOGO:
        percorso = os.path.join(radice, relativo)
        if os.path.isfile(percorso):
            return percorso
    return None


# ===========================================================================
# SUONI GENERATI
# ===========================================================================
def suono_whoosh(durata=0.55, frequenza=FREQUENZA_AUDIO, volume=VOLUME_WHOOSH,
                 seme=7):
    """Un "whoosh": rumore filtrato con il taglio che sale e poi scende.

    Il filtro e' un passa-basso a un polo con la frequenza di taglio che
    spazza da 300 Hz a ~6 kHz e torna giu'; l'inviluppo sale in fretta e
    cala piano, come un oggetto che passa vicino. Mono, valori in [-1, 1].
    """
    import numpy as np

    n = max(int(durata * frequenza), 1)
    rumore = np.random.default_rng(seme).uniform(-1.0, 1.0, n)
    x = np.linspace(0.0, 1.0, n)
    sweep = 300.0 + 5700.0 * np.sin(np.pi * np.clip(x * 1.15, 0, 1)) ** 2
    alfa = 1.0 - np.exp(-2.0 * np.pi * sweep / frequenza)
    uscita = np.empty(n)
    stato = 0.0
    for i in range(n):
        stato += alfa[i] * (rumore[i] - stato)
        uscita[i] = stato
    inviluppo = np.where(x < 0.35, (x / 0.35) ** 2, ((1 - x) / 0.65) ** 1.6)
    uscita *= inviluppo
    picco = float(np.max(np.abs(uscita))) or 1.0
    return uscita / picco * volume


def suono_pop(durata=0.18, frequenza=FREQUENZA_AUDIO, volume=VOLUME_POP,
              nota=880.0):
    """Un "pop/ding" breve: sinusoide che scende appena di tono e si spegne
    in fretta, con un'armonica che le da' il timbro di campanello."""
    import numpy as np

    n = max(int(durata * frequenza), 1)
    t = np.arange(n) / frequenza
    tono = nota * (1.0 + 0.25 * np.exp(-t * 40))
    fase = 2 * np.pi * np.cumsum(tono) / frequenza
    onda = np.sin(fase) + 0.35 * np.sin(1.5 * fase)
    attacco = np.clip(t / 0.004, 0, 1)
    onda *= attacco * np.exp(-t * 22)
    picco = float(np.max(np.abs(onda))) or 1.0
    return onda / picco * volume


def traccia_effetti(durata, eventi, frequenza=FREQUENZA_AUDIO):
    """Una traccia stereo lunga `durata` con i suoni messi al loro istante.

    `eventi` e' una lista di (istante, campioni mono). Dove due suoni si
    sovrappongono si sommano, poi la traccia si limita a 0.9 cosi' non
    satura mai, qualunque cosa ci finisca dentro.
    """
    import numpy as np

    n = max(int(durata * frequenza), 1)
    mono = np.zeros(n)
    for istante, campioni in eventi:
        inizio = int(max(istante, 0) * frequenza)
        if inizio >= n:
            continue
        pezzo = np.asarray(campioni, dtype=float)[: n - inizio]
        mono[inizio:inizio + len(pezzo)] += pezzo
    picco = float(np.max(np.abs(mono))) if n else 0.0
    if picco > 0.9:
        mono *= 0.9 / picco
    return np.stack([mono, mono], axis=1)
