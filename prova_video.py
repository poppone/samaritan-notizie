"""
Video di prova: scrive e monta uno Short come la pipeline vera, ma NON lo
carica da nessuna parte (niente YouTube, niente copia pubblica, niente
prenotazione della notizia). Serve a far vedere a Davide le modifiche di
montaggio prima di unirle. Il file finisce fra gli artifact della run.

Uso:
    python prova_video.py                # tema libero
    python prova_video.py "MotoGP"       # tema specifico
"""
import os
import shutil
import sys

from brain import genera_script_samaritan
from maker import assembla_video_finale


def main():
    tema = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].strip() else None
    dati = genera_script_samaritan(tema)
    print(f"TITOLO : {dati['titolo']}")
    print(f"FONTE  : {dati.get('fonte', '')}")
    print(f"SCRIPT : {dati['script']}")
    video = assembla_video_finale(
        testo_per_audio=dati["script"],
        query_video=dati["query_video"],
        titolo=dati["titolo"],
        gioco=dati.get("gioco", ""),
        fonte=dati.get("fonte", ""),
        query_scene=dati.get("query_scene"),
    )
    if not video:
        sys.exit("Montaggio fallito.")
    os.makedirs("prova", exist_ok=True)
    shutil.copy(video, os.path.join("prova", "prova.mp4"))
    with open(os.path.join("prova", "scheda.txt"), "w", encoding="utf-8") as f:
        f.write(f"{dati['titolo']}\n\nFonte: {dati.get('fonte', '')}\n\n{dati['script']}\n")

    # Per controllare l'allineamento fra voce e scritte: i tempi delle parole
    # dati dalla voce e quello che Whisper sente nel video finito.
    import glob
    import json
    import config
    for parole in glob.glob(os.path.join(config.DIR_TEMP, "*.parole.json")):
        shutil.copy(parole, os.path.join("prova", os.path.basename(parole)))
    try:
        import whisper
        risultato = whisper.load_model("base").transcribe(
            video, language="it", word_timestamps=True)
        sentite = [{"parola": w["word"].strip(), "inizio": round(w["start"], 2),
                    "fine": round(w["end"], 2)}
                   for s in risultato["segments"] for w in s.get("words", [])]
        with open(os.path.join("prova", "sentite.json"), "w",
                  encoding="utf-8") as f:
            json.dump(sentite, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"Trascrizione di controllo saltata: {e}")


if __name__ == "__main__":
    main()
