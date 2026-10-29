"""
Montaggio video di Samaritan.

La qualita' visiva nasce dall'EDITING, non da riprese fatte a mano:

  1. Materiale UFFICIALE del gioco (trailer + screenshot Steam) via gameplay.py
  2. Stacco ogni 2-3 secondi: l'occhio non ha tempo di annoiarsi
  3. Zoom lento (Ken Burns) su ogni stacco: movimento costante
  4. Sorgenti di proporzioni diverse dall'uscita inserite su sfondo sfocato
  5. Progress bar, banner del titolo, sottotitoli

Lo Short ha in piu' il montaggio veloce di effetti.py: amo col titolo enorme
nei primi due secondi, stacchi ogni 1,5-2 secondi a tempo con la voce, lampi
e zoom a scatto sugli stacchi, sottotitoli con la parola detta accesa, suoni
generati (whoosh, pop sui numeri) e il finale che invita a seguire il canale.

Lo stesso montaggio produce due formati, e le misure le legge da config:
lo Short 9:16 da mezzo minuto (sottotitoli una parola per volta, enormi, al
centro) e il video lungo 16:9 da otto minuti (sottotitoli a frase, in basso).
Su otto minuti la forma dello Short vorrebbe oltre mille clip sovrapposti,
uno per parola, e non e' solo una questione di gusto.

La VESTE (colori, altezze, barra, banner, verso dello zoom, ritmo degli
stacchi) non e' fissa: la sceglie `veste.py` e cambia a ogni video, cosi' due
Short di fila non si somigliano. Qui dentro non ci sono piu' costanti grafiche
da leggere: tutto quello che si vede arriva dal dizionario `stile`.
"""
import os
import re
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioArrayClip

import config
import effetti
import profilo
import veste
from stock import scarica_clip_sfondo, scegli_sorgente  # noqa: F401
from voice import (genera_voce_samaritan, grafia_canale, leggi_parole,
                   pulisci_testo, tempi_parole)

# Le ricerche Pexels di riserva, ultimissimo ripiego quando le scene del
# video non trovano clip adatte (stock.py prende la piu' vicina al tema),
# stanno nel profilo del canale (voce 'query_stock_riserva'): per Poppone TV
# sono scene di gioco, per un canale di cucina sarebbero pentole e fornelli.

# Colore di riserva del testo, usato solo da chi chiama queste funzioni senza
# passare una veste: i colori veri stanno in veste.py.
GIALLO = "#FFE600"

# Veste di riserva: serve a chi chiama una singola funzione di questo modulo
# (test, prove a mano) senza passare da assembla_video_finale.
STILE_BASE = veste.VESTI[0]

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",        # Ubuntu (Actions)
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",                                 # Windows
    "arialbd.ttf",
    "arial.ttf",
]

# VideoFileClip aperti, riusati fra i vari stacchi della stessa sorgente
_CACHE_VIDEO = {}


def _carica_font(dimensione):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, dimensione)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


# ===========================================================================
# PEXELS (fallback quando il gioco non e' identificabile)
# ===========================================================================
# La ricerca e il download delle clip d'archivio stanno in stock.py, che non
# si porta dietro moviepy: li' c'e' anche il controllo che ogni clip c'entri
# con la frase che la voce sta dicendo. Il nome resta anche qui per chi lo
# importava da maker.


# ===========================================================================
# ADATTAMENTO AL FORMATO VERTICALE
# ===========================================================================
def _sfondo_sfocato(frame, durata, luminosita=0.42):
    """Sfondo a tutto schermo ricavato dal frame stesso: sfocato e scurito.

    La sfocatura viene fatta in miniatura e poi ingrandita: e' ~50 volte piu'
    veloce che sfocare a piena risoluzione e il risultato e' identico,
    visto che l'immagine e' comunque fuori fuoco.

    La miniatura tiene le proporzioni dell'uscita, non un 9:16 fisso: con le
    proporzioni sbagliate il ritaglio prende la parte sbagliata del fotogramma
    e lo sfondo del video lungo esce stirato.
    """
    W, H = config.VIDEO_W, config.VIDEO_H
    lato = 192
    if W >= H:
        piccolo_w, piccolo_h = lato, max(round(lato * H / W), 1)
    else:
        piccolo_w, piccolo_h = max(round(lato * W / H), 1), lato

    img = Image.fromarray(frame)
    fattore = max(piccolo_w / img.width, piccolo_h / img.height)
    img = img.resize((max(int(img.width * fattore), piccolo_w),
                      max(int(img.height * fattore), piccolo_h)), Image.BILINEAR)

    sinistra = (img.width - piccolo_w) // 2
    alto = (img.height - piccolo_h) // 2
    img = img.crop((sinistra, alto, sinistra + piccolo_w, alto + piccolo_h))

    img = img.filter(ImageFilter.GaussianBlur(4))
    img = ImageEnhance.Brightness(img).enhance(luminosita)   # scurito: il primo piano spicca
    img = img.resize((W, H), Image.BILINEAR)

    return ImageClip(np.array(img)).with_duration(durata)


# Quanto le proporzioni della sorgente possono discostarsi da quelle
# dell'uscita prima di rinunciare al pieno schermo. Dentro questa forbice il
# ritaglio toglie un bordo e non si nota; fuori toglierebbe meta' scena.
TOLLERANZA_PIENO_SCHERMO = (0.72, 1.30)


def _adatta_al_formato(clip, durata, stile=None):
    """Porta qualunque sorgente alle misure dell'uscita (9:16 o 16:9).

    - Sorgenti con le proporzioni dell'uscita -> scale-to-cover + ritaglio
      centrale, cioe' schermo pieno. E' il caso dei trailer Steam nel video
      lungo, che sono 16:9 come lui, e delle clip verticali nello Short.
    - Tutte le altre -> riquadro centrale su sfondo sfocato ricavato dal
      fotogramma stesso. E' il caso dei trailer 16:9 dentro uno Short, e delle
      clip girate col telefono dentro il video lungo.
    """
    W, H = config.VIDEO_W, config.VIDEO_H
    stile = stile or STILE_BASE

    proporzione_uscita = W / max(H, 1)
    proporzione_clip = clip.w / max(clip.h, 1)
    minimo, massimo = TOLLERANZA_PIENO_SCHERMO

    # --- Stesse proporzioni: riempie tutto lo schermo ---
    if minimo <= proporzione_clip / proporzione_uscita <= massimo:
        fattore = max(W / clip.w, H / clip.h)
        scalato = clip.resized((round(clip.w * fattore), round(clip.h * fattore)))
        return scalato.cropped(width=W, height=H,
                               x_center=scalato.w / 2, y_center=scalato.h / 2)

    # --- Proporzioni diverse: riquadro + sfondo sfocato ---
    if W >= H:
        # Uscita orizzontale: e' l'altezza a fare da vincolo, e il riquadro
        # sta al centro. Qui dentro finiscono le clip verticali di popponetv,
        # girate col telefono, che nel 16:9 non possono riempire lo schermo.
        altezza_fg = int(H * 0.94)
        larghezza_fg = max(round(altezza_fg * clip.w / max(clip.h, 1)), 2)
        if larghezza_fg > W * 0.94:
            larghezza_fg = int(W * 0.94)
            altezza_fg = max(round(larghezza_fg * clip.h / max(clip.w, 1)), 2)
        posizione = ("center", "center")
    else:
        # Uscita verticale: e' la larghezza a fare da vincolo, e l'altezza del
        # riquadro la decide la veste.
        larghezza_fg = int(W * config.ZOOM_GAMEPLAY)
        altezza_fg = max(round(larghezza_fg * clip.h / max(clip.w, 1)), 2)
        altezza_max = int(H * 0.62)
        if altezza_fg > altezza_max:
            altezza_fg = altezza_max
            larghezza_fg = max(round(altezza_fg * clip.w / max(clip.h, 1)), 2)
        posizione = ("center", int(H * stile["y_gameplay"]))

    primo_piano = clip.resized((larghezza_fg, altezza_fg))

    try:
        istante = min(clip.duration / 2, max(clip.duration - 0.05, 0))
        sfondo = _sfondo_sfocato(clip.get_frame(istante), durata,
                                 stile["luminosita_sfondo"])
    except Exception as e:
        print(f"[Warning Maker] Sfondo sfocato non generato ({e}), uso il nero.")
        sfondo = ColorClip(size=(W, H), color=(0, 0, 0)).with_duration(durata)

    return CompositeVideoClip(
        [sfondo, primo_piano.with_position(posizione)],
        size=(W, H),
    ).with_duration(durata)


# Il nome di prima, quando Samaritan faceva solo Short verticali.
_adatta_a_verticale = _adatta_al_formato


def _scatto(t, ampiezza, secondi):
    """Lo zoom "a scatto": parte largo di `ampiezza` e rientra in `secondi`,
    frenando alla fine. E' l'effetto punch-in dei montaggi veloci."""
    if ampiezza <= 0 or t >= secondi:
        return 0.0
    return ampiezza * (1 - t / secondi) ** 2


def _zoom_fotogramma(fotogramma, fattore):
    """Ingrandisce un fotogramma di `fattore` restando al centro.

    Si ritaglia prima la parte che resta in quadro e la si porta alle misure
    piene con un ridimensionamento solo: costa come un resize del fotogramma,
    invece di ingrandirlo tutto e poi comporlo su un fondo e ritagliarlo.
    """
    if fattore <= 1.0005:
        return fotogramma
    alto, largo = fotogramma.shape[:2]
    w, h = largo / fattore, alto / fattore
    x0, y0 = (largo - w) / 2, (alto - h) / 2
    img = Image.fromarray(fotogramma)
    return np.array(img.resize((largo, alto), Image.BILINEAR,
                               box=(x0, y0, x0 + w, y0 + h)))


def _applica_zoom(clip, durata, intensita=0.08, verso="dentro",
                  scatto=0.0, secondi_scatto=0.22):
    """Ken Burns: zoom lento e continuo, il movimento trattiene l'occhio.

    Il verso fa piu' differenza di quanta sembri: "dentro" stringe sul
    dettaglio, "fuori" apre sulla scena. Lo stesso spezzone montato nei due
    versi si legge come due inquadrature diverse.

    `scatto` aggiunge in testa allo stacco uno zoom veloce che rientra in
    `secondi_scatto`: costa niente in piu', e' lo stesso ridimensionamento.
    """
    try:
        if verso == "fuori":
            def lento(t):
                return 1 + intensita * (1 - t / max(durata, 0.01))
        else:
            def lento(t):
                return 1 + intensita * (t / max(durata, 0.01))

        def fattore(t):
            return lento(t) + _scatto(t, scatto, secondi_scatto)

        # Lo spezzone arriva gia' alle misure dell'uscita e pieno: la sua
        # maschera e' tutta opaca, e portarsela dietro costa a ogni fotogramma.
        pieno = clip.without_mask() if clip.mask is not None else clip
        return pieno.transform(
            lambda prendi, t: _zoom_fotogramma(prendi(t), fattore(t))
        ).with_duration(durata)
    except Exception as e:
        print(f"[Warning Maker] Zoom non applicato ({e}).")
        return clip


# ===========================================================================
# MONTAGGIO
# ===========================================================================
def _apri_video(percorso):
    if percorso not in _CACHE_VIDEO:
        _CACHE_VIDEO[percorso] = VideoFileClip(percorso).without_audio()
    return _CACHE_VIDEO[percorso]


def _prepara_segmento(sorgente, durata, stile=None, verso="dentro",
                      scatto=0.0, secondi_scatto=0.22, esatta=False):
    """Costruisce un singolo stacco gia' in formato 1080x1920.

    Con `esatta` lo stacco dura esattamente `durata` anche se la clip e' piu'
    corta (la si ripete): gli stacchi a tempo con la voce non possono
    accorciarsi da soli, altrimenti i tagli scivolano fuori tempo.
    """
    stile = stile or STILE_BASE
    intensita = stile["intensita_zoom"]

    if sorgente["tipo"] == "immagine":
        base = ImageClip(sorgente["path"]).with_duration(durata)
        # Sugli screenshot lo zoom e' piu' marcato: senza, sembrerebbero fermi
        return _applica_zoom(_adatta_al_formato(base, durata, stile), durata,
                             intensita=intensita * 2, verso=verso,
                             scatto=scatto, secondi_scatto=secondi_scatto)

    video = _apri_video(sorgente["path"])
    if video.duration <= durata:
        pezzo = video.subclipped(0, video.duration)
        if esatta:
            from moviepy.video.fx import Loop
            pezzo = pezzo.with_effects([Loop(duration=durata)])
        else:
            durata = video.duration
    else:
        inizio = random.uniform(0, video.duration - durata)
        pezzo = video.subclipped(inizio, inizio + durata)

    return _applica_zoom(_adatta_al_formato(pezzo, durata, stile), durata,
                         intensita=intensita, verso=verso,
                         scatto=scatto, secondi_scatto=secondi_scatto)


def _verso_dello_stacco(stile, numero):
    # "alternato" cambia verso a ogni stacco: il montaggio respira invece
    # di spingere sempre nella stessa direzione per tutto il video.
    if stile["zoom"] == "alternato":
        return "dentro" if numero % 2 == 0 else "fuori"
    return stile["zoom"]


# Lo scatto dello sfondo: quello d'apertura e' piu' ampio e piu' lungo (fa
# parte dell'amo), quello sugli stacchi e' un colpo secco.
SCATTO_APERTURA = (0.22, 0.55)
SCATTO_STACCO = (0.10, 0.20)


def _sfondo_a_tempo(utilizzabili, punti, durata_totale, stile):
    """Lo sfondo dello Short: uno stacco per ogni punto, mai la stessa
    sorgente due volte di fila, e lo zoom a scatto dove la veste lo vuole."""
    segmenti_tempo = effetti.segmenti_da_punti(punti, durata_totale)
    ordine = effetti.ordine_sorgenti(len(utilizzabili), len(segmenti_tempo))
    scatta = "scatto" in stile["transizione"]

    segmenti, scartate = [], set()
    for numero, ((inizio, durata), indice) in enumerate(zip(segmenti_tempo, ordine)):
        if numero == 0:
            ampiezza, secondi = SCATTO_APERTURA
        elif scatta:
            ampiezza, secondi = SCATTO_STACCO
        else:
            ampiezza, secondi = 0.0, 0.2
        segmento = None
        # Se la sorgente prevista non si apre si prova la successiva: lo
        # stacco deve esserci comunque, o i tagli dopo andrebbero fuori tempo.
        for tentativo in range(len(utilizzabili)):
            candidata = (indice + tentativo) % len(utilizzabili)
            if candidata in scartate:
                continue
            sorgente = utilizzabili[candidata]
            try:
                segmento = _prepara_segmento(
                    sorgente, durata, stile, _verso_dello_stacco(stile, numero),
                    scatto=ampiezza, secondi_scatto=secondi, esatta=True)
                break
            except Exception as e:
                print(f"[Warning Maker] Sorgente scartata ({sorgente['path']}): {e}")
                scartate.add(candidata)
        if segmento is None:
            return None
        segmenti.append(segmento.with_duration(durata))

    print(f"[Samaritan Maker] Veste '{stile['nome']}', stacchi a tempo con la voce: "
          f"{len(segmenti)} in {durata_totale:.1f}s "
          f"(media {durata_totale / max(len(segmenti), 1):.1f}s), "
          f"transizione {stile['transizione']}.")
    # Gli stacchi sono tutti a misura piena e opachi: si mettono in fila
    # senza comporli su un fondo, che costerebbe una fusione a fotogramma.
    return concatenate_videoclips(segmenti, method="chain")


def costruisci_sfondo_montato(sorgenti, durata_totale, stile=None, punti=None):
    """Alterna le sorgenti con uno stacco ogni 2-3 secondi.

    Video e immagini vengono mescolati: i trailer danno movimento, gli
    screenshot danno inquadrature pulite del gioco. Le clip d'archivio con
    una scena invece non si mescolano: vanno nell'ordine delle frasi. La veste decide quanto
    durano gli stacchi (`ritmo`) e da che verso si muove lo zoom.

    Con `punti` (gli istanti di stacco calcolati sulla voce, vedi
    effetti.punti_di_stacco) gli stacchi cadono esattamente li': e' il
    montaggio veloce dello Short. Senza, si taglia a caso fra STACCO_MIN e
    STACCO_MAX come fa il video lungo.
    """
    stile = stile or STILE_BASE
    utilizzabili = [s for s in sorgenti if os.path.exists(s["path"])]
    if not utilizzabili:
        return None

    # Le clip d'archivio con una scena seguono l'ordine della voce: ogni
    # scena ha la sua finestra di tempo (stock.scegli_sorgente). Mescolarle
    # metteva la pista da corsa sotto la frase sui prezzi e viceversa.
    per_scena = any(s.get("scena") is not None for s in utilizzabili)
    usi = {}
    if not per_scena:
        random.shuffle(utilizzabili)
        # I video per primi: il video deve APRIRE con movimento, non con uno
        # statico
        utilizzabili.sort(key=lambda s: s["tipo"] != "video")

    if punti:
        return _sfondo_a_tempo(utilizzabili, punti, durata_totale, stile)

    segmenti, coperto, indice = [], 0.0, 0
    while coperto < durata_totale:
        if per_scena:
            sorgente = scegli_sorgente(utilizzabili, coperto, durata_totale, usi)
        else:
            sorgente = utilizzabili[indice % len(utilizzabili)]
        indice += 1

        durata = random.uniform(config.STACCO_MIN * stile["ritmo"],
                                config.STACCO_MAX * stile["ritmo"])
        durata = min(durata, durata_totale - coperto)
        if durata < 0.4:
            break

        verso = _verso_dello_stacco(stile, len(segmenti))

        try:
            segmento = _prepara_segmento(sorgente, durata, stile, verso)
        except Exception as e:
            print(f"[Warning Maker] Sorgente scartata ({sorgente['path']}): {e}")
            utilizzabili = [s for s in utilizzabili if s is not sorgente]
            if not utilizzabili:
                break
            continue

        segmenti.append(segmento)
        coperto += segmento.duration

    if not segmenti:
        return None

    n_video = sum(1 for s in utilizzabili if s["tipo"] == "video")
    print(f"[Samaritan Maker] Veste '{stile['nome']}', zoom {stile['zoom']}.")
    print(f"[Samaritan Maker] {len(segmenti)} stacchi in {coperto:.1f}s "
          f"(media {coperto / len(segmenti):.1f}s) da {len(utilizzabili)} sorgenti "
          f"({n_video} video, {len(utilizzabili) - n_video} immagini)")

    return concatenate_videoclips(segmenti, method="compose")


# ===========================================================================
# GRAFICA
# ===========================================================================
def crea_immagine_parola(testo, font_size=115, colore=GIALLO):
    bordo, pad_x, pad_y = 9, 44, 28
    larghezza_utile = config.VIDEO_W * 0.94 - 2 * (bordo + pad_x)
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # Le vesti usano corpi diversi, e una parola lunga scritta grande uscirebbe
    # dallo schermo: si rimpicciolisce finche' non ci sta. Meglio una parola
    # piu' piccola che una parola tagliata a meta'.
    while font_size > 60:
        font = _carica_font(font_size)
        if misura.textlength(testo, font=font) <= larghezza_utile:
            break
        font_size -= 6

    font = _carica_font(font_size)
    bbox = misura.textbbox((0, 0), testo, font=font)
    testo_w, testo_h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    img = Image.new(
        "RGBA",
        (testo_w + bordo * 2 + pad_x * 2, testo_h + bordo * 2 + pad_y * 2),
        (0, 0, 0, 0),
    )
    ImageDraw.Draw(img).text(
        (pad_x + bordo - bbox[0], pad_y + bordo - bbox[1]),
        testo, font=font, fill=colore, stroke_width=bordo, stroke_fill="black",
    )
    return np.array(img)


def crea_banner_titolo(testo, larghezza_max, font_size=64):
    font = _carica_font(font_size)
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    righe, riga = [], ""
    for parola in testo.split():
        tentativo = f"{riga} {parola}".strip()
        if misura.textlength(tentativo, font=font) <= larghezza_max - 80:
            riga = tentativo
        else:
            if riga:
                righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    righe = righe[:3]

    altezza_riga = font_size + 18
    img = Image.new("RGBA",
                    (larghezza_max, altezza_riga * len(righe) + 40),
                    (0, 0, 0, 165))
    draw = ImageDraw.Draw(img)
    for i, riga in enumerate(righe):
        w = draw.textlength(riga, font=font)
        draw.text(((larghezza_max - w) / 2, 20 + i * altezza_riga),
                  riga, font=font, fill="white", stroke_width=3, stroke_fill="black")
    return np.array(img)


# Il cartello del telegiornale: etichetta rossa, titolo su fascia chiara e,
# sotto, la testata e l'avviso che le immagini sono di repertorio. Sta in
# cima per tutto il video, sopra il riquadro delle clip e lontano dai
# sottotitoli (58-74% dell'altezza) e dai comandi dell'app Shorts in basso.
Y_CARTELLO_TG = 0.05
ETICHETTA_TG = {"it": "ULTIM'ORA", "en": "BREAKING NEWS"}
REPERTORIO_TG = {"it": "Immagini di repertorio", "en": "Stock footage"}
FONTE_TG = {"it": "Fonte", "en": "Source"}
ROSSO_TG = (200, 16, 30)


def testata_della_fonte(fonte):
    """'Titolo della notizia (ANSA)' -> 'ANSA'. '' se non c'e'."""
    trovata = re.search(r"\(([^()]+)\)\s*$", (fonte or "").strip())
    return trovata.group(1).strip() if trovata else ""


def crea_cartello_tg(titolo, testata, lingua="it", larghezza=None):
    """Il cartello del telegiornale, come immagine RGBA."""
    larghezza = larghezza or int(config.VIDEO_W * 0.92)
    lingua = lingua if lingua in ETICHETTA_TG else "it"
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    font_etichetta = _carica_font(40)
    font_titolo = _carica_font(52)
    font_fonte = _carica_font(32)

    etichetta = ETICHETTA_TG[lingua]
    alto_etichetta = 70
    largo_etichetta = int(misura.textlength(etichetta, font=font_etichetta)) + 48

    righe = _manda_a_capo(misura, titolo.strip(), font_titolo, larghezza - 60)
    if len(righe) > 2:
        # Due righe al massimo: la terza si taglia con i puntini, e il titolo
        # intero resta comunque quello del video.
        righe = righe[:2]
        while righe[1] and misura.textlength(righe[1] + "...", font=font_titolo) > larghezza - 60:
            righe[1] = righe[1].rsplit(" ", 1)[0] if " " in righe[1] else righe[1][:-1]
        righe[1] += "..."
    alto_riga = 64
    alto_titolo = alto_riga * max(len(righe), 1) + 28

    piede = REPERTORIO_TG[lingua]
    if testata:
        piede = f"{FONTE_TG[lingua]}: {testata}  \u00b7  {piede}"
    alto_piede = 54

    img = Image.new("RGBA", (larghezza, alto_etichetta + alto_titolo + alto_piede),
                    (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, largo_etichetta, alto_etichetta), fill=ROSSO_TG + (255,))
    draw.text((24, 12), etichetta, font=font_etichetta, fill="white")

    y = alto_etichetta
    draw.rectangle((0, y, larghezza, y + alto_titolo), fill=(245, 245, 245, 240))
    for i, riga in enumerate(righe):
        draw.text((30, y + 14 + i * alto_riga), riga, font=font_titolo,
                  fill=(15, 15, 15))

    y += alto_titolo
    draw.rectangle((0, y, larghezza, y + alto_piede), fill=(15, 15, 15, 225))
    while (misura.textlength(piede, font=font_fonte) > larghezza - 40
           and getattr(font_fonte, "size", 0) > 20):
        font_fonte = _carica_font(font_fonte.size - 2)
    draw.text((20, y + 10), piede, font=font_fonte, fill=(230, 230, 230))
    return np.array(img)


def _manda_a_capo(draw, testo, font, larghezza_max):
    """Spezza il testo in righe che stanno dentro larghezza_max."""
    righe, corrente = [], ""
    for parola in testo.split():
        tentativo = f"{corrente} {parola}".strip()
        if not corrente or draw.textlength(tentativo, font=font) <= larghezza_max:
            corrente = tentativo
        else:
            righe.append(corrente)
            corrente = parola
    if corrente:
        righe.append(corrente)
    return righe


def crea_miniatura(frame, testo, percorso=None, colore=GIALLO):
    """Miniatura verticale ricavata dallo sfondo, con l'amo scritto grande.

    Senza miniatura personalizzata YouTube estrae un fotogramma a caso. Nel
    feed Shorts non cambia niente, perche' il video parte da solo; cambia nella
    griglia del canale e nella ricerca, dove nove fotogrammi casuali in fila
    sono la differenza fra un canale e un archivio.
    """
    W, H = config.VIDEO_W, config.VIDEO_H
    percorso = percorso or config.FILE_MINIATURA

    img = Image.fromarray(np.uint8(frame)).convert("RGB")
    if img.size != (W, H):
        img = img.resize((W, H), Image.BILINEAR)
    img = ImageEnhance.Brightness(img).enhance(0.55)   # il testo deve staccare

    testo = (testo or "").strip()
    if testo:
        draw = ImageDraw.Draw(img)
        margine = int(W * 0.08)
        dimensione, font, righe = 150, None, [testo]
        # Parte grande e rimpicciolisce finche' non sta in tre righe: i titoli
        # corti restano enormi, quelli lunghi restano comunque leggibili.
        for dimensione in range(150, 59, -10):
            font = _carica_font(dimensione)
            righe = _manda_a_capo(draw, testo, font, W - 2 * margine)
            if len(righe) <= 3:
                break
        altezza_riga = int(dimensione * 1.18)
        y = (H - altezza_riga * len(righe)) // 2
        for riga in righe:
            larghezza = draw.textlength(riga, font=font)
            draw.text(((W - larghezza) / 2, y), riga, font=font, fill=colore,
                      stroke_width=max(4, dimensione // 18), stroke_fill="black")
            y += altezza_riga

    # YouTube rifiuta le miniature oltre i 2 MB. A questa risoluzione non ci si
    # arriva quasi mai, ma su un fotogramma molto rumoroso puo' succedere.
    for qualita in (88, 78, 68, 58):
        img.save(percorso, "JPEG", quality=qualita, optimize=True)
        if os.path.getsize(percorso) <= 2 * 1024 * 1024:
            break
    print(f"[Samaritan Maker] Miniatura pronta: {os.path.basename(percorso)}")
    return percorso


def crea_progress_bar(durata, passi=60, altezza=12, colore=(255, 230, 0)):
    """La barra sta sempre in cima: in fondo la coprirebbe l'interfaccia di
    YouTube. Quello che cambia da una veste all'altra e' spessore e colore."""
    clips = []
    clips.append(
        ColorClip(size=(config.VIDEO_W, altezza), color=(20, 20, 20))
        .with_duration(durata).with_position((0, 0)).with_opacity(0.55)
    )
    passo = durata / passi
    for i in range(1, passi + 1):
        clips.append(
            ColorClip(size=(max(int(config.VIDEO_W * i / passi), 1), altezza),
                      color=colore)
            .with_start(passo * (i - 1)).with_duration(passo).with_position((0, 0))
        )
    return clips


# ===========================================================================
# SOTTOTITOLI
# ===========================================================================
def crea_immagine_frase(testo, font_size=52, colore="white",
                        larghezza_max=None):
    """Una riga (o due) di sottotitolo, su fascia scura semitrasparente.

    E' il sottotitolo del video lungo. Quello dello Short e' un'altra cosa:
    una parola per volta, enorme, al centro. Su otto minuti quella forma
    diventa insopportabile, e soprattutto costerebbe un clip di montaggio per
    ogni parola, cioe' oltre mille clip sovrapposti in un video solo.
    """
    larghezza_max = larghezza_max or int(config.VIDEO_W * 0.80)
    font = _carica_font(font_size)
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    righe = _manda_a_capo(misura, testo, font, larghezza_max - 60)[:2]

    altezza_riga = font_size + 16
    img = Image.new("RGBA",
                    (larghezza_max, altezza_riga * len(righe) + 32),
                    (0, 0, 0, 150))
    draw = ImageDraw.Draw(img)
    for i, riga in enumerate(righe):
        w = draw.textlength(riga, font=font)
        draw.text(((larghezza_max - w) / 2, 16 + i * altezza_riga),
                  riga, font=font, fill=colore,
                  stroke_width=3, stroke_fill="black")
    return np.array(img)


def _sottotitoli_a_frase(risultato, stile):
    """I sottotitoli del video lungo: una frase per volta, in basso."""
    clips = []
    y = int(config.VIDEO_H * 0.80)
    corpo = max(int(config.VIDEO_H * 0.048), 30)

    for segmento in risultato.get("segments", []):
        testo = grafia_canale(segmento.get("text") or "").strip()
        if not testo:
            continue
        inizio = segmento.get("start", 0)
        durata = max(segmento.get("end", inizio) - inizio, 0.4)
        try:
            clips.append(
                ImageClip(crea_immagine_frase(testo, font_size=corpo,
                                              colore=stile["colore_testo"]))
                .with_start(inizio).with_duration(durata)
                .with_position(("center", y))
            )
        except Exception as e:
            print(f"[Warning Maker] Sottotitolo saltato: {e}")

    print(f"[Samaritan Subtitles] {len(clips)} frasi sincronizzate.")
    return clips


def _parole_da_whisper(audio_path):
    import whisper

    print(f"[Samaritan Subtitles] Trascrizione con modello '{config.WHISPER_MODEL}'...")
    modello = whisper.load_model(config.WHISPER_MODEL)
    risultato = modello.transcribe(audio_path, language=config.LINGUA,
                                   word_timestamps=not config.VIDEO_LUNGO)
    if config.VIDEO_LUNGO:
        return risultato
    return [{"parola": info["word"], "inizio": info["start"], "fine": info["end"]}
            for segmento in risultato.get("segments", [])
            for info in segmento.get("words", [])]


def parole_dello_short(audio_path, testo=""):
    """I tempi delle parole dello Short, con la punteggiatura del testo.

    I tempi esatti li da' la voce stessa (vedi voice.leggi_parole); Whisper
    solo se la voce non li ha dati. Servono a sottotitoli, stacchi e suoni,
    quindi si leggono una volta sola.
    """
    parole = leggi_parole(audio_path)
    if parole:
        print(f"[Samaritan Subtitles] Tempi esatti dalla voce ({len(parole)} parole).")
    else:
        parole = _parole_da_whisper(audio_path)
    return effetti.ripunteggia(parole, testo) if testo else parole


BIANCO = "#FFFFFF"

# Quanto e' piu' grande la parola detta rispetto alle altre della riga, e
# di quanto "salta" nel momento in cui viene detta.
SCALA_PAROLA_DETTA = 1.18
SALTO_PAROLA_DETTA = 0.20
SECONDI_SALTO = 0.13


def crea_immagine_riga(parole, attiva, colori, font_size=96, larghezza_max=None):
    """Una riga di sottotitolo con la parola detta accesa e piu' grande.

    `parole` sono gia' maiuscole, `colori` e' il colore di ciascuna (bianco,
    evidenza o accento). Tutte stanno sulla stessa linea di base, cosi' la
    parola piu' grande non fa ballare la riga. Ritorna l'immagine RGBA e il
    riquadro (x0, y0, x1, y1) della parola accesa, che serve per farla
    saltare.
    """
    bordo, pad_x, pad_y = 9, 30, 22
    larghezza_max = larghezza_max or int(config.VIDEO_W * 0.94)
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    while True:
        font = _carica_font(font_size)
        grande = _carica_font(int(font_size * SCALA_PAROLA_DETTA))
        # Il bordo nero di ogni parola sborda di `bordo` pixel per lato e
        # mangerebbe lo spazio: lo si aggiunge, altrimenti "ALLA VIGILIA" si
        # legge "ALLAVIGILIA".
        spazio = misura.textlength(" ", font=font) * 1.1 + 2 * bordo
        larghezze = [misura.textlength(p, font=grande if i == attiva else font)
                     for i, p in enumerate(parole)]
        # Attorno alla parola detta serve anche il posto per il suo salto, che
        # la allarga di SALTO_PAROLA_DETTA per un istante.
        margine = (larghezze[attiva] * SALTO_PAROLA_DETTA / 2
                   if 0 <= attiva < len(parole) else 0)
        accanto = sum(1 for j in (attiva - 1, attiva) if 0 <= j < len(parole) - 1)
        totale = (sum(larghezze) + spazio * (len(parole) - 1) + margine * accanto
                  + 2 * (bordo + pad_x))
        if totale <= larghezza_max or font_size <= 48:
            break
        font_size -= 6

    salita, discesa = grande.getmetrics()
    altezza = salita + discesa + 2 * (bordo + pad_y)
    img = Image.new("RGBA", (int(totale) + 1, altezza), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    base = pad_y + bordo + salita
    x = pad_x + bordo
    riquadro = (0, 0, img.width, img.height)
    for i, (parola, colore) in enumerate(zip(parole, colori)):
        f = grande if i == attiva else font
        draw.text((x, base), parola, font=f, fill=colore, anchor="ls",
                  stroke_width=bordo, stroke_fill="black")
        if i == attiva:
            sx = draw.textbbox((x, base), parola, font=f, anchor="ls",
                               stroke_width=bordo)
            riquadro = (max(int(sx[0]) - 2, 0), max(int(sx[1]) - 2, 0),
                        min(int(sx[2]) + 2, img.width), min(int(sx[3]) + 2, img.height))
        x += larghezze[i] + spazio
        if i in (attiva - 1, attiva):
            x += margine

    # Al corpo minimo una riga puo' restare piu' larga dello schermo: la si
    # rimpicciolisce tutta, perche' una parola tagliata dal bordo non si legge
    # (e un clip fuori quadro manda in errore la composizione).
    if img.width > larghezza_max:
        k = larghezza_max / img.width
        img = img.resize((larghezza_max, max(int(img.height * k), 1)), Image.LANCZOS)
        riquadro = tuple(int(v * k) for v in riquadro)
    return np.array(img), riquadro


def _colore_parola(tipo, attiva, stile):
    # La parola detta ha sempre il suo colore, anche se e' un numero o un
    # nome: altrimenti su quelle righe la si riconoscerebbe solo dal corpo.
    if attiva:
        return stile["colore_parola"]
    return stile["colore_evidenza"] if tipo else BIANCO


def _sottotitoli_accesi(parole, titolo, gioco, stile, dopo=0.0):
    """I sottotitoli dello Short: righe di poche parole, quella detta accesa.

    Una riga resta a schermo finche' la voce la legge; a ogni parola cambia
    l'immagine (stessa riga, accesa un'altra parola) e la parola detta fa un
    piccolo salto. Il salto e' un ritaglio della parola stessa ingrandito per
    un decimo di secondo: si ridimensiona un francobollo, non tutta la riga.

    Prima di `dopo` (la fine dell'amo) non compare niente: in quei secondi a
    schermo c'e' gia' il titolo enorme, e tre testi insieme non li legge
    nessuno. Una parola a cavallo entra quando l'amo esce, senza salto.
    """
    W = config.VIDEO_W
    y = int(config.VIDEO_H * stile["y_sottotitoli"])
    corpo = int(stile["corpo_sottotitoli"] * 0.80)
    chiave_titolo = effetti.parole_del_titolo(titolo, gioco)
    tempi = tempi_parole(parole)
    tipi = [effetti.tipo_parola(parole, i, chiave_titolo) for i in range(len(parole))]

    clips = []
    for riga in effetti.raggruppa_parole(parole):
        # Punti e virgole servono a capire dove finisce la frase, ma a schermo
        # una parola per volta sembrano refusi; ? e ! invece si leggono.
        testi = [grafia_canale(testo).strip().upper().rstrip(".,;:")
                 for testo in (parole[i]["parola"] for i in riga)]
        if not any(testi):
            continue
        for posizione, i in enumerate(riga):
            _, inizio, durata = tempi[i]
            salto = True
            if inizio + durata <= dopo:
                continue
            if inizio < dopo:
                durata -= dopo - inizio
                inizio, salto = dopo, False
            colori = [_colore_parola(tipi[j], j == i, stile) for j in riga]
            try:
                immagine, (x0, y0, x1, y1) = crea_immagine_riga(
                    testi, posizione, colori, font_size=corpo)
            except Exception as e:
                print(f"[Warning Maker] Sottotitolo saltato: {e}")
                continue
            x_riga = (W - immagine.shape[1]) // 2
            clips.append(ImageClip(immagine).with_start(inizio)
                         .with_duration(durata).with_position((x_riga, y)))

            ritaglio = immagine[y0:y1, x0:x1]
            if ritaglio.size == 0 or not salto:
                continue
            cx, cy = x_riga + (x0 + x1) / 2, y + (y0 + y1) / 2
            larga, alta = x1 - x0, y1 - y0

            def scala(t):
                return 1 + _scatto(t, SALTO_PAROLA_DETTA, SECONDI_SALTO)

            def dove(t, cx=cx, cy=cy, larga=larga, alta=alta):
                k = scala(t)
                # Il salto resta dentro lo schermo anche per la parola sul bordo.
                x = min(max(cx - larga * k / 2, 0), W - larga * k)
                return (int(x), int(cy - alta * k / 2))
            try:
                clips.append(ImageClip(ritaglio).resized(scala)
                             .with_start(inizio)
                             .with_duration(min(SECONDI_SALTO, durata))
                             .with_position(dove))
            except Exception:
                pass

    print(f"[Samaritan Subtitles] {len(parole)} parole in "
          f"{len(effetti.raggruppa_parole(parole))} righe accese.")
    return clips


def genera_sottotitoli_clips(audio_path, titolo="", gioco="", stile=None,
                             parole=None, dopo=0.0):
    stile = stile or STILE_BASE

    if config.VIDEO_LUNGO:
        return _sottotitoli_a_frase(_parole_da_whisper(audio_path), stile)

    if parole is None:
        parole = parole_dello_short(audio_path)
    return _sottotitoli_accesi(parole, titolo, gioco, stile, dopo)


# ===========================================================================
# EFFETTI DELLO SHORT (amo, lampi, finale, suoni): la logica sta in effetti.py
# ===========================================================================
def crea_immagine_testo(righe, colori, corpi, larghezza_max=None, interlinea=1.12):
    """Righe di testo centrate, ognuna col suo colore e corpo, bordo nero.

    Le righe troppo larghe si rimpiccioliscono finche' non ci stanno: un
    titolo lungo resta leggibile invece di uscire dallo schermo.
    """
    larghezza_max = larghezza_max or int(config.VIDEO_W * 0.90)
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pronte = []
    for riga, corpo in zip(righe, corpi):
        while corpo > 40:
            font = _carica_font(corpo)
            if misura.textlength(riga, font=font) <= larghezza_max - 40:
                break
            corpo -= 6
        pronte.append((riga, _carica_font(corpo), corpo))

    bordi = [max(5, c // 14) for _, _, c in pronte]
    alte = [int(c * interlinea) + 2 * b for (_, _, c), b in zip(pronte, bordi)]
    img = Image.new("RGBA", (larghezza_max, sum(alte) + 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = 10
    for (riga, font, corpo), colore, bordo, alta in zip(pronte, colori, bordi, alte):
        w = draw.textlength(riga, font=font)
        draw.text(((larghezza_max - w) / 2, y + bordo), riga, font=font,
                  fill=colore, stroke_width=bordo, stroke_fill="black")
        y += alta
    return np.array(img)


def _a_scatto(immagine, inizio, durata, centro, ampiezza=0.32, secondi=0.18):
    """ImageClip che entra grande e si ferma di colpo, centrata in `centro`."""
    alta, larga = immagine.shape[:2]
    cx, cy = centro

    def scala(t):
        return 1 + _scatto(t, ampiezza, secondi)

    def dove(t):
        k = scala(t)
        return (int(cx - larga * k / 2), int(cy - alta * k / 2))
    return (ImageClip(immagine).resized(scala).with_start(inizio)
            .with_duration(durata).with_position(dove))


def crea_amo(titolo, stile):
    """L'amo dei primi due secondi: il titolo enorme che entra a scatto."""
    W, H = config.VIDEO_W, config.VIDEO_H
    testo = (titolo or "").strip().upper()
    if not testo:
        return []
    misura = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    corpo = 150
    for corpo in range(150, 71, -10):
        righe = _manda_a_capo(misura, testo, _carica_font(corpo), W * 0.86)
        if len(righe) <= 3:
            break
    righe = righe[:3]
    # L'ultima riga nel colore d'accento: e' quella che si legge per ultima
    # ed e' di solito la notizia (il prezzo, il "da oggi").
    colori = [BIANCO] * (len(righe) - 1) + [stile["colore_parola"]]
    immagine = crea_immagine_testo(righe, colori, [corpo] * len(righe))
    # Sta sopra i sottotitoli: il suo fondo resta lontano dalla loro fascia.
    alto_max = stile["y_sottotitoli"] * H - 40
    cy = min(H * 0.44, alto_max - immagine.shape[0] / 2)
    return [_a_scatto(immagine, 0, min(effetti.SECONDI_AMO, 10), (W / 2, cy))]


# Opacita' del lampo: abbastanza per sentire il colpo, non uno schermo bianco.
OPACITA_LAMPO = 0.6


def crea_lampi(punti, stile, fps=None):
    """Il lampo bianco sugli stacchi gia' scelti (effetti.punti_dei_lampi):
    un solo fotogramma a opacita' 0.6, un colpo di luce e non uno schermo
    bianco."""
    if "flash" not in stile["transizione"]:
        return []
    fps = fps or config.FPS or 30
    W, H = config.VIDEO_W, config.VIDEO_H
    lampi = []
    for t in punti:
        if t <= 0:
            continue
        lampi.append(ColorClip(size=(W, H), color=(255, 255, 255))
                     .with_start(t).with_duration(1 / fps)
                     .with_opacity(OPACITA_LAMPO))
    return lampi


def crea_finale(inizio, durata, stile, nome_canale, handle="", lingua="it"):
    """Gli ultimi secondi: invito a seguire il canale, col logo se c'e'."""
    W, H = config.VIDEO_W, config.VIDEO_H
    clips = [ColorClip(size=(W, H), color=(0, 0, 0)).with_start(inizio)
             .with_duration(durata).with_opacity(0.62)]

    righe = effetti.testi_finale(nome_canale, handle, lingua)
    colori = [stile["colore_parola"], BIANCO, (210, 210, 210)][:len(righe)]
    corpi = [140, 96, 58][:len(righe)]
    testo = crea_immagine_testo(righe, colori, corpi)
    cy_testo = H * 0.50

    logo = effetti.trova_logo()
    if logo:
        try:
            immagine = Image.open(logo).convert("RGBA")
            lato = int(W * 0.30)
            immagine = immagine.resize(
                (lato, max(int(immagine.height * lato / immagine.width), 1)),
                Image.LANCZOS)
            logo_np = np.array(immagine)
            cy_logo = cy_testo - testo.shape[0] / 2 - logo_np.shape[0] / 2 - 30
            clips.append(_a_scatto(logo_np, inizio + 0.12, durata - 0.12,
                                   (W / 2, cy_logo), ampiezza=0.6, secondi=0.25))
        except Exception as e:
            print(f"[Warning Maker] Logo del finale saltato: {e}")
    clips.append(_a_scatto(testo, inizio, durata, (W / 2, cy_testo)))
    return clips


def mixa_effetti(voce, durata, eventi):
    """La voce con sotto i suoni degli effetti, a volume basso.

    Gli effetti stanno in una traccia sola, costruita in memoria: un clip
    audio per ogni pop farebbe lo stesso lavoro molte volte.
    """
    if not eventi:
        return voce
    traccia = effetti.traccia_effetti(durata, eventi)
    sotto = AudioArrayClip(traccia, fps=effetti.FREQUENZA_AUDIO).with_start(0)
    return CompositeAudioClip([voce, sotto]).with_duration(durata)


# ===========================================================================
# PIPELINE
# ===========================================================================
def assembla_video_finale(testo_per_audio=None, query_video="gameplay",
                          titolo="", gioco="", tema="Gaming",
                          resoconto=None, audio_pronto=None, fonte="",
                          query_scene=None):
    """Monta il video e lo scrive su disco. Ritorna il percorso, o None.

    `audio_pronto` e' il percorso di un audio gia' sintetizzato: lo passa il
    video lungo, che la voce la genera una sezione per volta per sapere dove
    cade ogni capitolo. Senza, la voce la si genera qui da `testo_per_audio`,
    come ha sempre fatto lo Short.
    """
    os.makedirs(config.DIR_OUTPUT, exist_ok=True)
    print("\n--- SAMARITAN MAKER: PRODUZIONE VIDEO ---")

    # La veste di oggi: colori, altezze, barra, banner, zoom, ritmo. Cambia a
    # ogni video, quindi due Short di fila non si somigliano.
    stile = veste.scegli_veste()

    if not testo_per_audio:
        from brain import genera_script_samaritan
        dati = genera_script_samaritan(tema)
        testo_per_audio = dati["script"]
        query_video = dati["query_video"]
        query_scene = dati.get("query_scene")
        titolo = dati["titolo"]
        gioco = dati.get("gioco", "")
        fonte = dati.get("fonte", "")

    # Lo Short ha il montaggio veloce (vedi effetti.py): stacchi a tempo con
    # la voce, amo, lampi, suoni e finale. Il video lungo no: su otto minuti
    # un lampo ogni due secondi sfinirebbe, e il suo ritmo e' un altro.
    wow = not config.VIDEO_LUNGO

    # Nello Short la voce chiude con l'invito a seguire il canale, detto
    # mentre a schermo compare il finale.
    testo_voce = testo_per_audio or ""
    if wow and not audio_pronto:
        invito = effetti.frase_finale_parlata(profilo.attivo().nome_canale,
                                              config.LINGUA)
        if invito:
            testo_voce = f"{testo_voce.rstrip()} {invito}"

    audio_path = audio_pronto or genera_voce_samaritan(testo_voce)
    if not audio_path:
        print("[Errore Maker] Audio non generato: interrompo.")
        return None

    # Materiale ufficiale del gioco, con ripiego automatico su stock
    from gameplay import procura_materiale
    sorgenti, gioco_ufficiale = procura_materiale(
        gioco=gioco, query_pexels=query_video, minimo=3,
        query_scene=query_scene, contesto=testo_per_audio,
    )
    if not sorgenti:
        print("[Errore Maker] Nessun materiale video disponibile: interrompo.")
        return None

    # Qui dentro e' l'unico posto che sa se il materiale e' davvero ufficiale:
    # procura_materiale() ripiega su clip d'archivio senza azzerare 'gioco',
    # quindi chi scrive la descrizione non puo' dedurlo dal nome del gioco.
    # Le sorgenti d'archivio hanno 'gioco' a None, quelle Steam no.
    if resoconto is not None:
        ufficiali = sum(1 for s in sorgenti if s.get("gioco"))
        resoconto["gioco_ufficiale"] = gioco_ufficiale
        resoconto["sorgenti_ufficiali"] = ufficiali
        resoconto["sorgenti_stock"] = len(sorgenti) - ufficiali

    audio_clip = AudioFileClip(audio_path)
    durata = audio_clip.duration + 0.4

    parole, punti, inizio_finale = [], None, None
    if wow:
        try:
            parole = parole_dello_short(audio_path, testo_voce)
        except Exception as e:
            print(f"[Warning Maker] Tempi delle parole non disponibili: {e}")
        # Il finale parte quando la voce comincia l'invito ("Seguici: ...").
        # Le parole dell'invito non fanno sottotitoli, stacchi ne' pop: a
        # schermo c'e' gia' il finale. Senza invito riconosciuto il finale
        # parte quando la voce ha finito, come prima.
        k = effetti.indice_invito_parlato(parole, config.LINGUA)
        if k is not None:
            inizio_finale = parole[k]["inizio"]
            parole = parole[:k]
            durata = max(audio_clip.duration + 0.5,
                         inizio_finale + effetti.SECONDI_FINALE)
        else:
            inizio_finale = audio_clip.duration + 0.1
            durata = inizio_finale + effetti.SECONDI_FINALE
        minimo, massimo = stile["stacco"]
        punti = effetti.punti_di_stacco(parole, durata, minimo, massimo)

    sfondo = costruisci_sfondo_montato(sorgenti, durata, stile, punti)
    if sfondo is None:
        print("[Errore Maker] Montaggio fallito: interrompo.")
        audio_clip.close()
        return None

    audio_finale = audio_clip
    if wow:
        try:
            eventi = [(0.0, effetti.suono_whoosh()),
                      (max(inizio_finale - 0.15, 0),
                       effetti.suono_whoosh(volume=effetti.VOLUME_WHOOSH * 0.8, seme=11))]
            eventi += [(max(t - 0.02, 0), effetti.suono_pop())
                       for t in effetti.momenti_pop(parole)]
            audio_finale = mixa_effetti(audio_clip, durata, eventi)
            print(f"[Samaritan Maker] Effetti sonori: {len(eventi)} "
                  f"({len(eventi) - 2} pop sui numeri).")
        except Exception as e:
            print(f"[Warning Maker] Effetti sonori saltati: {e}")
            audio_finale = audio_clip

    sfondo = sfondo.with_duration(durata).with_audio(audio_finale)
    livelli = [sfondo]

    if wow:
        try:
            livelli.extend(crea_lampi(effetti.punti_dei_lampi(punti, parole),
                                      stile))
        except Exception as e:
            print(f"[Warning Maker] Lampi sugli stacchi saltati: {e}")

    # Un telegiornale ha il suo cartello fisso al posto del banner: titolo,
    # testata e "immagini di repertorio" fino alla fine. Senza l'avviso
    # una clip stock sotto una notizia vera sembra il filmato della notizia.
    # Nello Short il cartello entra quando esce l'amo: nei primi due secondi
    # il titolo c'e' gia', enorme, e due volte non serve.
    con_amo = wow and bool(titolo)
    inizio_cartello = min(effetti.SECONDI_AMO, durata) if con_amo else 0
    telegiornale = profilo.attivo().telegiornale and not config.VIDEO_LUNGO
    if telegiornale and titolo:
        try:
            livelli.append(
                ImageClip(crea_cartello_tg(pulisci_testo(titolo),
                                           testata_della_fonte(fonte),
                                           config.LINGUA))
                .with_start(inizio_cartello)
                .with_duration(durata - inizio_cartello)
                .with_position(("center", int(config.VIDEO_H * Y_CARTELLO_TG)))
            )
        except Exception as e:
            print(f"[Warning Maker] Cartello del telegiornale saltato: {e}")

    # Banner e barra non ci sono in tutte le vesti: l'assenza e' una scelta,
    # non un errore, ed e' il modo piu' netto per far sembrare diverso il video.
    # Nello Short il titolo lo porta l'amo, enorme, nei primi due secondi:
    # il banner sarebbe lo stesso titolo due volte.
    if titolo and stile["banner"] and not telegiornale and not wow:
        altezza_banner, secondi_banner = stile["banner"]
        try:
            banner = (
                ImageClip(crea_banner_titolo(pulisci_testo(titolo).upper(),
                                             int(config.VIDEO_W * 0.92)))
                .with_start(0).with_duration(min(secondi_banner, durata))
                .with_position(("center", int(config.VIDEO_H * altezza_banner)))
            )
            livelli.append(banner)
        except Exception as e:
            print(f"[Warning Maker] Banner titolo saltato: {e}")

    if stile["barra"]:
        spessore, colore_barra = stile["barra"]
        try:
            livelli.extend(crea_progress_bar(durata, altezza=spessore,
                                             colore=colore_barra))
        except Exception as e:
            print(f"[Warning Maker] Progress bar saltata: {e}")

    amo_a_schermo = False
    if con_amo:
        try:
            from brain import testo_miniatura
            amo = testo_miniatura(titolo) or pulisci_testo(titolo)
        except Exception:
            amo = pulisci_testo(titolo)
        try:
            clip_amo = crea_amo(amo, stile)
            livelli.extend(clip_amo)
            amo_a_schermo = bool(clip_amo)
        except Exception as e:
            print(f"[Warning Maker] Amo iniziale saltato: {e}")

    try:
        livelli.extend(genera_sottotitoli_clips(audio_path, titolo,
                                                gioco_ufficiale or gioco, stile,
                                                parole=parole or None,
                                                dopo=effetti.SECONDI_AMO
                                                if amo_a_schermo else 0.0))
    except Exception as e:
        print(f"[Warning Maker] Sottotitoli saltati: {e}")

    if wow:
        canale = profilo.attivo()
        try:
            livelli.extend(crea_finale(inizio_finale, durata - inizio_finale, stile,
                                       canale.nome_canale, canale.handle,
                                       config.LINGUA))
        except Exception as e:
            print(f"[Warning Maker] Finale saltato: {e}")

    finale = CompositeVideoClip(livelli,
                                size=(config.VIDEO_W, config.VIDEO_H)
                                ).with_duration(durata)

    nome_file = ("samaritan_video_lungo.mp4" if config.VIDEO_LUNGO
                 else "samaritan_short_subbed.mp4")
    output_file = os.path.join(config.DIR_OUTPUT, nome_file)
    print(f"[Samaritan Maker] Rendering {config.VIDEO_W}x{config.VIDEO_H} "
          f"@{config.FPS}fps ({durata:.1f}s, preset {config.PRESET_RENDER})...")
    finale.write_videofile(output_file, fps=config.FPS, codec="libx264",
                           audio_codec="aac", preset=config.PRESET_RENDER,
                           threads=4)

    # La miniatura si ricava dallo sfondo, non dal composito: sul composito ci
    # sono gia' banner e sottotitoli, e sovrapporci altro testo e' illeggibile.
    # Il file vecchio va tolto PRIMA: se la generazione fallisce, main.py non
    # deve caricare la miniatura del video di ieri.
    if os.path.exists(config.FILE_MINIATURA):
        os.remove(config.FILE_MINIATURA)
    try:
        from brain import testo_miniatura
        istante = min(1.2, max(durata - 0.2, 0.1))
        crea_miniatura(sfondo.get_frame(istante), testo_miniatura(titolo),
                       colore=stile["colore_evidenza"])
    except Exception as e:
        print(f"[Warning Maker] Miniatura saltata: {e}")

    for c in [audio_clip, sfondo, finale] + list(_CACHE_VIDEO.values()):
        try:
            c.close()
        except Exception:
            pass
    _CACHE_VIDEO.clear()

    # Il giro delle vesti avanza solo ora: il video esiste davvero, quindi
    # questa veste e' spesa. Se il rendering fosse fallito, la prossima
    # esecuzione riproverebbe con la stessa invece di saltarla.
    veste.segna_veste(stile["nome"])

    print("\nVIDEO GENERATO CON SUCCESSO!")
    return output_file


if __name__ == "__main__":
    assembla_video_finale()
