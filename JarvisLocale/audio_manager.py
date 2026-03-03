import sounddevice as sd
from scipy.io.wavfile import write as wav_write
from faster_whisper import WhisperModel
import edge_tts
import pygame
import asyncio
import os
import time

# --- Configurazione ---
SAMPLE_RATE = 16000       # Hz - ottimale per Whisper
DURATA_REGISTRAZIONE = 5  # secondi
FILE_INPUT = "input.wav"
FILE_RISPOSTA = "risposta.mp3"
VOCE_TTS = "it-IT-DiegoNeural"  # alternativa: "it-IT-ElsaNeural"

# Carica il modello Whisper una sola volta (evita di ricaricarlo ad ogni chiamata)
print("⏳ Caricamento modello Whisper (small)... potrebbe richiedere qualche secondo.")
modello_whisper = WhisperModel("small", device="cpu", compute_type="int8")
print("✅ Modello Whisper caricato.")


def ascolta() -> str:
    """
    Registra audio dal microfono per DURATA_REGISTRAZIONE secondi,
    lo salva come WAV e lo trascrive in italiano con faster-whisper.
    Restituisce il testo riconosciuto.
    """
    print(f"\n🎙️  In ascolto per {DURATA_REGISTRAZIONE} secondi... Parla ora!")

    # Registra audio dal microfono
    audio = sd.rec(
        int(DURATA_REGISTRAZIONE * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )
    sd.wait()  # attendi fine registrazione
    print("✅ Registrazione completata.")

    # Salva come file WAV
    wav_write(FILE_INPUT, SAMPLE_RATE, audio)

    # Trascrivi con Whisper
    print("⏳ Trascrizione in corso...")
    segmenti, info = modello_whisper.transcribe(FILE_INPUT, language="it")

    testo = ""
    for segmento in segmenti:
        testo += segmento.text

    testo = testo.strip()
    print(f"📝 Testo riconosciuto: \"{testo}\"")
    return testo


def parla(testo: str) -> None:
    """
    Converte il testo in audio usando edge-tts con voce italiana,
    salva il file MP3 e lo riproduce con pygame.
    """
    print("🔊 Generazione audio della risposta...")

    # Genera l'audio con edge-tts (usa asyncio internamente)
    asyncio.run(_genera_audio(testo))

    # Riproduci con pygame
    pygame.mixer.init()
    pygame.mixer.music.load(FILE_RISPOSTA)
    pygame.mixer.music.play()

    # Attendi che la riproduzione finisca
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)

    pygame.mixer.music.unload()
    pygame.mixer.quit()
    print("✅ Riproduzione completata.")


async def _genera_audio(testo: str) -> None:
    """Helper asincrono per generare l'audio TTS."""
    communicate = edge_tts.Communicate(testo, VOCE_TTS)
    await communicate.save(FILE_RISPOSTA)
