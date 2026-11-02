# -*- coding: utf-8 -*-
"""
"Motori della settimana": il video lungo del sabato fatto con gli Short.

Perche' esiste: per il programma partner contano le ore di visione dei video
LUNGHI (4.000 in 12 mesi), e le ore guardate sugli Short non contano (vedi
README). Il video lungo scritto da zero (lungo.py) ha fatto 6, 0 e 0
visualizzazioni; questo invece mette in fila notizie che il pubblico ha gia'
scelto di guardare, una volta a settimana. Davide ha detto si' il 2/11/2026.

Come funziona, in breve:
  1. ogni Short, appena caricato, viene conservato come artifact di GitHub
     Actions chiamato "short-<video_id>" (main.py lo mette da parte,
     samaritan.yml lo carica: 10 giorni di tenuta). Niente download da
     YouTube e niente dipendenza dalla copia su Vercel Blob, che sparisce
     dopo circa 4 giorni: quella resta solo come ripiego;
  2. il sabato mattina (riassunto.yml) si leggono in cronologia gli Short
     usciti negli ultimi 7 giorni, si scaricano i loro file e si montano con
     ffmpeg in 16:9: lo Short verticale a sinistra, sopra il suo stesso
     fotogramma sfocato, e a destra un pannello con numero, titolo, fonte e
     giorno della notizia. Davanti un'apertura di pochi secondi, in fondo una
     chiusura; nessuna musica, solo l'audio degli Short (voce sintetica ed
     effetti generati in effetti.py);
  3. si carica come video normale (non Short), dichiarato come contenuto
     sintetico (uploader.carica_short lo fa sempre), con i capitoli e le
     fonti nella descrizione.

Se gli Short disponibili sono meno di MIN_SHORT non si pubblica niente e lo
si scrive nel log. Uso:

    python riassunto.py archivia <percorso_mp4> <video_id>   # da main.py
    python riassunto.py                                       # il sabato
"""
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- Regole
MIN_SHORT = 5                 # sotto, il riassunto non esce
GIORNI = 7                    # quanto indietro si guarda
SECONDI_INTRO = 4.0
SECONDI_OUTRO = 6.0
# Durata massima del video: oltre i 10 minuti si tolgono le notizie meno viste.
MAX_SECONDI = 10 * 60
TITOLO_SERIE = os.environ.get("RIASSUNTO_TITOLO", "").strip() or "Motori della settimana"
# Ora (del fuso del canale) a cui il riassunto compare sul canale. La run del
# sabato parte prima e GitHub la fa partire quando vuole: come per gli Short,
# il video sale privato e YouTube lo rende pubblico da solo (publishAt).
ORA_USCITA = os.environ.get("RIASSUNTO_ORA", "").strip() or "11:00"

DIR_LAVORO = "temp_riassunto"
DIR_ARCHIVIO = os.path.join("output_videos", "settimana")
FILE_REGISTRO = "riassunti_settimanali.json"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_NORMALE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
COLORE_FONDO = "0x10162B"
COLORE_ACCENTO = "0xE85A16"
RIGA_AI = "Video realizzato con l'AI: voce sintetica e montaggio automatico."

_ID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


# ===========================================================================
# 1. ARCHIVIO: chiamato da main.py subito dopo l'upload di ogni Short
# ===========================================================================
def archivia_short(percorso_video, video_id, radice="."):
    """Mette da parte lo Short come <video_id>.mp4 e lo dice al workflow.

    Scrive 'short_id=<video_id>' in $GITHUB_OUTPUT: samaritan.yml lo usa per
    caricare l'artifact "short-<video_id>". Non solleva mai: lo Short e' gia'
    su YouTube, qui si prepara solo il riassunto del sabato.
    """
    try:
        if not video_id or not _ID_VALIDO.match(video_id):
            return None
        if not percorso_video or not os.path.exists(percorso_video):
            return None
        cartella = os.path.join(radice, DIR_ARCHIVIO)
        os.makedirs(cartella, exist_ok=True)
        destinazione = os.path.join(cartella, f"{video_id}.mp4")
        try:
            os.link(percorso_video, destinazione)
        except OSError:
            shutil.copy2(percorso_video, destinazione)
        uscita = os.environ.get("GITHUB_OUTPUT")
        if uscita:
            with open(uscita, "a", encoding="utf-8") as f:
                f.write(f"short_id={video_id}\n")
        print(f"[Riassunto] Short conservato per il sabato: {destinazione}")
        return destinazione
    except Exception as e:
        print(f"[Warning Riassunto] Short non conservato: {e}")
        return None


# ===========================================================================
# 2. SCELTA DELLE NOTIZIE (logica pura, coperta dai test)
# ===========================================================================
def _istante(voce):
    """Quando lo Short e' uscito: 'uscita' se c'e', altrimenti 'timestamp'."""
    for campo in ("uscita", "timestamp"):
        try:
            valore = int(voce.get(campo) or 0)
        except (TypeError, ValueError):
            valore = 0
        if valore > 0:
            return valore
    return 0


def short_della_settimana(cronologia, adesso, giorni=GIORNI, lingua="it"):
    """Gli Short gia' usciti negli ultimi `giorni` giorni, dal piu' vecchio.

    Solo Short (non video lunghi), solo nella lingua del riassunto, solo con
    un video_id, e solo quelli gia' pubblici: un'uscita programmata per oggi
    pomeriggio non si mette in un video che esce stamattina.
    """
    fine = int(adesso.timestamp())
    inizio = fine - giorni * 86400
    visti, scelti = set(), []
    for voce in cronologia or []:
        if not isinstance(voce, dict):
            continue
        vid = voce.get("video_id") or ""
        if not vid or vid in visti or not _ID_VALIDO.match(vid):
            continue
        if (voce.get("formato") or "short") != "short":
            continue
        if (voce.get("lingua") or "it") != lingua:
            continue
        quando = _istante(voce)
        if not (inizio < quando <= fine):
            continue
        visti.add(vid)
        scelti.append(voce)
    return sorted(scelti, key=_istante)


def _visualizzazioni(voce, performance):
    dati = ((performance or {}).get("video") or {}).get(voce.get("video_id"), {})
    try:
        return int(dati.get("views") or 0)
    except (TypeError, ValueError):
        return 0


def _punteggio(voce, performance, adesso=None):
    """Visualizzazioni all'ora dall'uscita (minimo 6 ore): lo Short di
    venerdi' sera non deve perdere contro quello di sabato scorso solo perche'
    e' online da meno tempo. Senza `adesso`, visualizzazioni e basta."""
    viste = _visualizzazioni(voce, performance)
    if adesso is None:
        return viste
    ore = (adesso.timestamp() - _istante(voce)) / 3600
    return viste / max(ore, 6)


def adatta_alla_durata(voci, durate, performance, adesso=None, massimo=MAX_SECONDI):
    """Toglie le notizie meno viste finche' il video non sta in `massimo`.

    `durate` e' {video_id: secondi}. L'ordine resta quello cronologico.
    """
    resto = massimo - SECONDI_INTRO - SECONDI_OUTRO
    tenute = list(voci)
    while tenute and sum(durate[v["video_id"]] for v in tenute) > resto:
        # A parita' di punteggio esce la piu' vecchia.
        peggiore = min(range(len(tenute)),
                       key=lambda i: (_punteggio(tenute[i], performance, adesso), i))
        tenute.pop(peggiore)
    return tenute


def etichetta(voce, massimo=32):
    """Il nome breve di una notizia, per il titolo: 'Stellantis', 'F1'."""
    titolo = (voce.get("titolo") or "").strip()
    if ":" in titolo:
        testa = titolo.split(":", 1)[0].strip()
        if 2 <= len(testa) <= massimo:
            return testa
    soggetto = (voce.get("gioco") or "").strip()
    if 2 <= len(soggetto) <= massimo:
        return soggetto
    parole = titolo.split()
    breve = " ".join(parole[:4])
    return breve[:massimo].rstrip(" ,.;-")


def top_notizie(voci, performance, quante=3, adesso=None):
    """Le etichette delle notizie piu' viste, senza doppioni (due Short su
    Stellantis fanno una voce sola)."""
    ordinate = sorted(enumerate(voci),
                      key=lambda c: (-_punteggio(c[1], performance, adesso), c[0]))
    scelte, viste = [], set()
    for _, voce in ordinate:
        nome = etichetta(voce)
        chiave = nome.lower()
        if not nome or chiave in viste:
            continue
        viste.add(chiave)
        scelte.append(nome)
        if len(scelte) == quante:
            break
    return scelte


def costruisci_titolo(top, giorno, massimo=100):
    """'Motori della settimana: A, B e C (07/11)', dentro i 100 caratteri."""
    data = f"({giorno:%d/%m})"
    nomi = list(top)
    while nomi:
        elenco = nomi[0] if len(nomi) == 1 else ", ".join(nomi[:-1]) + " e " + nomi[-1]
        titolo = f"{TITOLO_SERIE}: {elenco} {data}"
        if len(titolo) <= massimo:
            return titolo
        nomi.pop()
    return f"{TITOLO_SERIE} {data}"


def _marca_tempo(secondi):
    secondi = int(secondi)
    minuti, resto = divmod(secondi, 60)
    ore, minuti = divmod(minuti, 60)
    return f"{ore}:{minuti:02d}:{resto:02d}" if ore else f"{minuti}:{resto:02d}"


def capitoli(voci, durate):
    """[(secondi, titolo)]: un capitolo per notizia.

    Il primo parte da 0:00 e comprende l'apertura (che dura meno dei dieci
    secondi minimi di un capitolo YouTube); la chiusura sta nell'ultimo.
    """
    elenco, istante = [], 0.0
    for i, voce in enumerate(voci):
        titolo = (voce.get("titolo") or etichetta(voce)).strip()
        if len(titolo) > 70:
            titolo = titolo[:67].rstrip() + "..."
        elenco.append((0.0 if i == 0 else istante, titolo))
        istante += (SECONDI_INTRO if i == 0 else 0) + durate[voce["video_id"]]
    return elenco


def formatta_capitoli(elenco):
    """Come lungo.formatta_capitoli: stringa vuota se YouTube li ignorerebbe."""
    if len(elenco) < 3 or elenco[0][0] > 0.5:
        return ""
    for (prima, _), (dopo, _) in zip(elenco, elenco[1:]):
        if dopo - prima < 10:
            return ""
    return "\n".join(f"{_marca_tempo(s)} {t}" for s, t in elenco)


def _testata(fonte):
    testo = (fonte or "").strip()
    if testo.endswith(")") and "(" in testo:
        testata = testo[testo.rfind("(") + 1:-1].strip()
        if testata:
            return testata
    return testo


def costruisci_descrizione(voci, durate, inizio, fine, nome_canale, handle,
                           massimo=5000):
    """Descrizione: due righe, capitoli, fonti di ogni notizia, nota AI.

    I link delle fonti (indirizzi news.google.com lunghissimi) entrano solo
    se ci stanno: senza, restano la testata e il link allo Short, che ha la
    fonte completa nella sua descrizione.
    """
    capitoli_txt = formatta_capitoli(capitoli(voci, durate))

    def componi(con_link):
        parti = [
            f"Le {len(voci)} notizie di motori della settimana dal "
            f"{inizio:%d/%m} al {fine:%d/%m}, una dopo l'altra, "
            f"dagli Short di {nome_canale}.",
        ]
        if capitoli_txt:
            parti.append("\nCapitoli:\n" + capitoli_txt)
        righe = []
        for i, voce in enumerate(voci, 1):
            riga = f"{i}. {voce.get('titolo', '').strip()}"
            testata = _testata(voce.get("fonte"))
            if testata:
                riga += f" - Fonte: {testata}"
            url = (voce.get("fonte_url") or "").strip()
            if con_link and url:
                riga += f" {url}"
            riga += f" - Short: https://youtube.com/shorts/{voce['video_id']}"
            righe.append(riga)
        parti.append("\nFonti:\n" + "\n".join(righe))
        parti.append(
            f"\n{RIGA_AI} I testi sono scritti con l'AI a partire dalle "
            "notizie citate sopra; nessuna musica nel video."
        )
        if handle:
            parti.append(f"\nUna notizia di motori in 60 secondi ogni giorno: "
                         f"youtube.com/{handle}")
        parti.append("\n#motori #auto #notizieauto")
        return "\n".join(parti)

    testo = componi(True)
    if len(testo) > massimo:
        testo = componi(False)
    return testo[:massimo]


def gia_fatto(registro, giorno):
    """True se per questo sabato un riassunto e' gia' uscito."""
    chiave = giorno.strftime("%Y-%m-%d")
    return any(isinstance(r, dict) and r.get("data") == chiave and r.get("video_id")
               for r in registro or [])


# ===========================================================================
# 3. FILE DEGLI SHORT: artifact di Actions, poi Vercel Blob come ripiego
# ===========================================================================
def _scarica_da_artifact(video_id, destinazione):
    import requests

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        return False
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    intestazioni = {"Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json"}
    r = requests.get(f"{api}/repos/{repo}/actions/artifacts",
                     params={"name": f"short-{video_id}", "per_page": 5},
                     headers=intestazioni, timeout=30)
    if not r.ok:
        print(f"[Riassunto] Elenco artifact HTTP {r.status_code} per {video_id}.")
        return False
    vivi = [a for a in r.json().get("artifacts", []) if not a.get("expired")]
    if not vivi:
        return False
    zip_path = destinazione + ".zip"
    # requests toglie da solo l'intestazione Authorization quando GitHub
    # rimanda all'archivio su un altro dominio.
    with requests.get(vivi[0]["archive_download_url"], headers=intestazioni,
                      stream=True, timeout=300) as z:
        if not z.ok:
            print(f"[Riassunto] Download artifact HTTP {z.status_code} per {video_id}.")
            return False
        with open(zip_path, "wb") as f:
            for blocco in z.iter_content(1 << 20):
                f.write(blocco)
    try:
        with zipfile.ZipFile(zip_path) as archivio:
            mp4 = [n for n in archivio.namelist() if n.lower().endswith(".mp4")]
            if not mp4:
                return False
            with archivio.open(mp4[0]) as sorgente, open(destinazione, "wb") as f:
                shutil.copyfileobj(sorgente, f)
    finally:
        os.remove(zip_path)
    return True


def _scarica_da_blob(url, destinazione):
    import requests

    if not url or not url.startswith("https://"):
        return False
    with requests.get(url, stream=True, timeout=300) as r:
        if not r.ok:
            return False
        with open(destinazione, "wb") as f:
            for blocco in r.iter_content(1 << 20):
                f.write(blocco)
    return True


def procura_file(voce, cartella):
    """Il percorso locale dello Short, o None se non si trova da nessuna parte."""
    vid = voce["video_id"]
    destinazione = os.path.join(cartella, f"{vid}.mp4")
    locale = os.path.join(DIR_ARCHIVIO, f"{vid}.mp4")
    if os.path.exists(locale):
        shutil.copy2(locale, destinazione)
        return destinazione
    for nome, prova in (("artifact", lambda: _scarica_da_artifact(vid, destinazione)),
                        ("Vercel Blob", lambda: _scarica_da_blob(
                            voce.get("video_file_url"), destinazione))):
        try:
            if prova() and os.path.getsize(destinazione) > 10000:
                print(f"[Riassunto] {vid}: preso da {nome}.")
                return destinazione
        except Exception as e:
            print(f"[Riassunto] {vid}: {nome} non riuscito ({e}).")
    print(f"[Riassunto] {vid}: file non trovato, la notizia resta fuori.")
    return None


# ===========================================================================
# 4. MONTAGGIO CON FFMPEG
# ===========================================================================
def _esegui(comando, timeout=1800):
    risultato = subprocess.run(comando, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout)
    if risultato.returncode != 0:
        coda = risultato.stderr.decode("utf-8", "replace")[-1500:]
        raise RuntimeError(f"ffmpeg ha fallito:\n{coda}")
    return risultato.stdout.decode("utf-8", "replace")


def durata(percorso):
    uscita = _esegui(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=noprint_wrappers=1:nokey=1", percorso], 60)
    return float(uscita.strip())


def ha_audio(percorso):
    uscita = _esegui(["ffprobe", "-v", "error", "-select_streams", "a",
                      "-show_entries", "stream=index", "-of", "csv=p=0", percorso], 60)
    return bool(uscita.strip())


def _testo(cartella, nome, contenuto):
    """drawtext legge il testo da file: niente problemi di apostrofi e due punti."""
    percorso = os.path.join(cartella, nome)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(contenuto)
    return percorso


def _scritta(file_testo, x, y, corpo, colore="white", font=FONT_BOLD, interlinea=12):
    return (f"drawtext=fontfile={font}:textfile={file_testo}:expansion=none:"
            f"fontsize={corpo}:fontcolor={colore}:line_spacing={interlinea}:x={x}:y={y}")


_CODIFICA = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-r", "30", "-video_track_timescale", "15360",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart"]


def monta_segmento(sorgente, voce, numero, totale, giorno, cartella, uscita):
    """Uno Short in 16:9: sfondo sfocato, Short a sinistra, pannello a destra."""
    base = f"s{numero:02d}"
    titolo = "\n".join(textwrap.wrap((voce.get("titolo") or "").strip(), 28)[:5])
    fonte = _testata(voce.get("fonte")) or "fonte nella descrizione"
    f_num = _testo(cartella, base + "_n.txt", f"NOTIZIA {numero} DI {totale}  ·  {giorno}")
    f_tit = _testo(cartella, base + "_t.txt", titolo)
    f_fon = _testo(cartella, base + "_f.txt",
                   "\n".join(textwrap.wrap(f"Fonte: {fonte}", 44)[:2]))
    f_ai = _testo(cartella, base + "_a.txt", "Contenuto realizzato con l'AI")

    video = (
        # Lo sfondo si sfoca a 480x270 e poi si ingrandisce: stesso effetto,
        # una frazione del tempo di una sfocatura a 1080p.
        "[0:v]scale=480:270:force_original_aspect_ratio=increase,crop=480:270,"
        "boxblur=8:2,eq=brightness=-0.20,scale=1920:1080[sf];"
        "[0:v]scale=-2:1000,setsar=1[sh];"
        "[sf][sh]overlay=x=150:y=40,"
        f"drawbox=x=820:y=140:w=1000:h=800:color={COLORE_FONDO}@0.85:t=fill,"
        f"drawbox=x=820:y=140:w=12:h=800:color={COLORE_ACCENTO}:t=fill,"
        + ",".join([
            _scritta(f_num, 880, 200, 34, COLORE_ACCENTO),
            _scritta(f_tit, 880, 290, 58, interlinea=18),
            _scritta(f_fon, 880, 790, 32, "0xDDDDDD", FONT_NORMALE),
            _scritta(f_ai, 880, 880, 24, "0xAAAAAA", FONT_NORMALE),
        ])
        + ",fps=30,format=yuv420p[v]"
    )
    comando = ["ffmpeg", "-y", "-loglevel", "error", "-i", sorgente]
    if ha_audio(sorgente):
        audio = "[0:a]aresample=48000,aformat=channel_layouts=stereo[a]"
    else:
        comando += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        audio = "[1:a]anull[a]"
    comando += ["-filter_complex", video + ";" + audio, "-map", "[v]", "-map", "[a]",
                "-shortest", *_CODIFICA, uscita]
    _esegui(comando)
    return uscita


def monta_cartello(righe, secondi, cartella, nome, uscita):
    """Un cartello a tinta unita con righe di testo, in silenzio.

    righe: [(testo, corpo, colore, grassetto)], centrate in verticale.
    """
    altezze = [corpo + 26 for _, corpo, _, _ in righe]
    y = (1080 - sum(altezze)) // 2
    filtri = []
    for i, ((testo, corpo, colore, grassetto), alto) in enumerate(zip(righe, altezze)):
        f = _testo(cartella, f"{nome}_{i}.txt", testo)
        filtri.append(
            f"drawtext=fontfile={FONT_BOLD if grassetto else FONT_NORMALE}:"
            f"textfile={f}:expansion=none:fontsize={corpo}:fontcolor={colore}:"
            f"x=(w-text_w)/2:y={y}")
        y += alto
    comando = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={COLORE_FONDO}:s=1920x1080:r=30:d={secondi}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
        "-filter_complex", f"[0:v]{','.join(filtri)},format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a", "-t", str(secondi), *_CODIFICA, uscita,
    ]
    _esegui(comando, 300)
    return uscita


def unisci(pezzi, cartella, uscita):
    """Attacca i pezzi, tutti codificati uguali, senza ricodificare."""
    elenco = os.path.join(cartella, "pezzi.txt")
    with open(elenco, "w", encoding="utf-8") as f:
        for p in pezzi:
            f.write("file '" + os.path.abspath(p).replace("'", r"'\''") + "'\n")
    _esegui(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", elenco, "-c", "copy", "-movflags", "+faststart", uscita])
    return uscita


def miniatura(sorgente, uscita):
    """La miniatura: un fotogramma dell'apertura, che ha titolo e notizie top."""
    _esegui(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", sorgente,
             "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "3", uscita], 120)
    return uscita


def monta_video(voci, file_short, top, inizio, fine, nome_canale, handle, fuso):
    """Monta tutto e ritorna (percorso_video, percorso_miniatura)."""
    cartella = os.path.abspath(DIR_LAVORO)
    os.makedirs(cartella, exist_ok=True)
    totale = len(voci)

    righe_intro = [(TITOLO_SERIE.upper(), 96, COLORE_ACCENTO, True),
                   (f"dal {inizio:%d/%m} al {fine:%d/%m}  ·  {totale} notizie", 46,
                    "white", False)]
    righe_intro += [(f"{nome}", 52, "white", True) for nome in top]
    righe_intro.append((nome_canale, 34, "0xBBBBBB", False))
    intro = monta_cartello(righe_intro, SECONDI_INTRO, cartella, "intro",
                           os.path.join(cartella, "00_intro.mp4"))

    pezzi = [intro]
    giorni = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    for n, voce in enumerate(voci, 1):
        quando = datetime.fromtimestamp(_istante(voce), fuso)
        giorno = f"{giorni[quando.weekday()]} {quando:%d/%m}"
        print(f"[Riassunto] Monto {n}/{totale}: {voce.get('titolo', '')}")
        pezzi.append(monta_segmento(file_short[voce["video_id"]], voce, n, totale,
                                    giorno, cartella,
                                    os.path.join(cartella, f"{n:02d}_notizia.mp4")))

    righe_outro = [("Grazie per la visione", 72, "white", True),
                   (f"Ogni giorno le notizie di motori in 60 secondi", 44, "white", False),
                   (handle or nome_canale, 56, COLORE_ACCENTO, True),
                   ("Fonti di ogni notizia nella descrizione", 34, "0xBBBBBB", False),
                   (RIGA_AI, 30, "0xBBBBBB", False)]
    pezzi.append(monta_cartello(righe_outro, SECONDI_OUTRO, cartella, "outro",
                                os.path.join(cartella, "99_outro.mp4")))

    os.makedirs("output_videos", exist_ok=True)
    video = unisci(pezzi, cartella, os.path.join("output_videos", "riassunto_settimanale.mp4"))
    jpg = miniatura(intro, os.path.join("output_videos", "riassunto_miniatura.jpg"))
    print(f"[Riassunto] Video pronto: {video} ({durata(video) / 60:.1f} minuti).")
    return video, jpg


# ===========================================================================
# 5. ORCHESTRAZIONE DEL SABATO
# ===========================================================================
def _leggi_json(percorso, vuoto):
    try:
        with open(percorso, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return vuoto


def _riepilogo(testo):
    """Il messaggio finisce nel log e nel riepilogo della run su GitHub."""
    print(f"[Riassunto] {testo}")
    riepilogo = os.environ.get("GITHUB_STEP_SUMMARY")
    if riepilogo:
        with open(riepilogo, "a", encoding="utf-8") as f:
            f.write(testo + "\n\n")


def _avvisa(testo):
    try:
        import notifier
        notifier.notifica_salto(testo)
    except Exception:
        pass


def uscita_programmata(adesso, fuso):
    """L'istante di oggi alle ORA_USCITA, o None se e' gia' passato."""
    ore, minuti = (int(x) for x in ORA_USCITA.split(":"))
    locale = adesso.astimezone(fuso)
    quando = locale.replace(hour=ore, minute=minuti, second=0, microsecond=0)
    return quando if quando > locale + timedelta(minutes=10) else None


def esegui(modalita="public", adesso=None):
    """modalita: 'public' (programmato alle ORA_USCITA), 'private', 'unlisted'
    oppure 'prova' (monta e basta, niente YouTube). Ritorna il video_id o None."""
    import config

    fuso = ZoneInfo(config.FUSO_USCITA or "Europe/Rome")
    adesso = adesso or datetime.now(timezone.utc)
    oggi = adesso.astimezone(fuso)

    registro = _leggi_json(FILE_REGISTRO, [])
    if modalita == "public" and gia_fatto(registro, oggi):
        _riepilogo(f"Il riassunto del {oggi:%d/%m} e' gia' uscito: non ne faccio un secondo.")
        return None

    cronologia = _leggi_json(config.FILE_CRONOLOGIA, [])
    performance = _leggi_json(config.FILE_PERFORMANCE, {})
    voci = short_della_settimana(cronologia, adesso)
    print(f"[Riassunto] Short usciti negli ultimi {GIORNI} giorni: {len(voci)}.")

    if len(voci) < MIN_SHORT:
        _riepilogo(f"Solo {len(voci)} Short in cronologia questa settimana "
                   f"(ne servono almeno {MIN_SHORT}): il riassunto non esce.")
        _avvisa(f"Riassunto del sabato non pubblicato: solo {len(voci)} Short "
                f"nella settimana, ne servono almeno {MIN_SHORT}.")
        return None

    cartella = os.path.abspath(os.path.join(DIR_LAVORO, "short"))
    os.makedirs(cartella, exist_ok=True)
    file_short, durate = {}, {}
    for voce in voci:
        percorso = procura_file(voce, cartella)
        if not percorso:
            continue
        try:
            durate[voce["video_id"]] = durata(percorso)
            file_short[voce["video_id"]] = percorso
        except Exception as e:
            print(f"[Riassunto] {voce['video_id']}: file illeggibile ({e}).")
    voci = [v for v in voci if v["video_id"] in file_short]

    if len(voci) < MIN_SHORT:
        _riepilogo(f"Solo {len(voci)} Short della settimana hanno ancora il file "
                   f"(ne servono almeno {MIN_SHORT}): il riassunto non esce.")
        _avvisa(f"Riassunto del sabato non pubblicato: solo {len(voci)} Short con "
                f"il file disponibile, ne servono almeno {MIN_SHORT}.")
        return None

    voci = adatta_alla_durata(voci, durate, performance, adesso)
    totale = SECONDI_INTRO + SECONDI_OUTRO + sum(durate[v["video_id"]] for v in voci)
    print(f"[Riassunto] Nel video: {len(voci)} notizie, {totale / 60:.1f} minuti.")
    if totale < 8 * 60:
        print("[Riassunto] Sotto gli 8 minuti: esce lo stesso, ma senza pause "
              "pubblicitarie a meta' video.")

    top = top_notizie(voci, performance, adesso=adesso)
    inizio = datetime.fromtimestamp(_istante(voci[0]), fuso)
    fine = datetime.fromtimestamp(_istante(voci[-1]), fuso)
    titolo = costruisci_titolo(top, oggi)
    descrizione = costruisci_descrizione(voci, durate, inizio, fine,
                                         config.NOME_CANALE, config.HANDLE_CANALE)
    print(f"[Riassunto] Titolo: {titolo}")
    print(descrizione)

    video, jpg = monta_video(voci, file_short, top, inizio, fine,
                             config.NOME_CANALE, config.HANDLE_CANALE, fuso)

    if modalita == "prova":
        _riepilogo(f"Prova: video montato ({titolo}), non caricato. "
                   "Si scarica dagli artifact di questa run.")
        return None

    from uploader import carica_short
    pubblica_alle = uscita_programmata(adesso, fuso) if modalita == "public" else None
    video_id = carica_short(
        filepath=video, titolo=titolo, descrizione=descrizione,
        tag=["motori", "auto", "notizie auto", "news auto", "motori della settimana",
             "riassunto settimanale", "auto elettriche", "formula 1"],
        privacy=modalita, miniatura=jpg, pubblica_alle=pubblica_alle,
    )
    if not video_id:
        raise RuntimeError("Upload del riassunto settimanale non riuscito.")

    registro.append({
        "data": oggi.strftime("%Y-%m-%d"),
        "video_id": video_id,
        "titolo": titolo,
        "privacy": modalita,
        "short": [v["video_id"] for v in voci],
        "secondi": round(totale),
    })
    with open(FILE_REGISTRO, "w", encoding="utf-8") as f:
        json.dump(registro[-60:], f, ensure_ascii=False, indent=2)
    quando = f" (esce alle {pubblica_alle:%H:%M})" if pubblica_alle else ""
    _riepilogo(f"Riassunto caricato: https://youtu.be/{video_id}{quando} - {titolo}")
    try:
        import notifier
        notifier.invia_messaggio(
            f"<b>Samaritan - RIASSUNTO DEL SABATO</b>\n\n{titolo}\n"
            f"https://youtu.be/{video_id}{quando}")
    except Exception:
        pass
    return video_id


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "archivia":
        archivia_short(sys.argv[2], sys.argv[3])
        sys.exit(0)
    scelta = (os.environ.get("RIASSUNTO_MODALITA") or "public").strip().lower()
    if scelta not in ("public", "private", "unlisted", "prova"):
        print(f"[Riassunto] Modalita' '{scelta}' non valida.")
        sys.exit(1)
    esegui(scelta)
