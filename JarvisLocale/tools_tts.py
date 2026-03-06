"""
tools_tts.py — Sintesi vocale con Kokoro-ONNX per IDIS.
Usa kokoro-onnx (leggero, ottimizzato Windows) per generare audio da testo
e sounddevice per la riproduzione in tempo reale.
"""

import numpy as np
import sounddevice as sd
import threading

# Kokoro-ONNX
from kokoro_onnx import Kokoro

# --- Configurazione ---
# Voce italiana consigliata: "if_sara" (femminile) o "im_nicola" (maschile)
# Per un elenco completo: https://github.com/thewh1teagle/kokoro-onnx#voices
VOCE = "if_sara"
LINGUA = "it"
SAMPLE_RATE = 24000  # sample rate nativo di Kokoro

# Singleton del modello — caricato una volta sola
_kokoro: Kokoro | None = None
_lock = threading.Lock()
_in_riproduzione = threading.Event()


def _get_kokoro() -> Kokoro:
    """Inizializza Kokoro in modo lazy e thread-safe."""
    global _kokoro
    if _kokoro is None:
        with _lock:
            if _kokoro is None:
                print("⏳ Caricamento modello Kokoro TTS...")
                _kokoro = Kokoro("kokoro-v1.0.onnx", "voices.bin")
                print("✅ Kokoro TTS pronto.")
    return _kokoro


def parla(testo: str, voce: str = VOCE, velocita: float = 1.0, blocca: bool = True) -> None:
    """
    Sintetizza il testo in audio e lo riproduce via sounddevice.

    Args:
        testo:    Testo da sintetizzare.
        voce:     Voce Kokoro da usare (default: 'if_sara').
        velocita: Moltiplicatore velocità (0.5 = lento, 1.0 = normale, 1.5 = veloce).
        blocca:   Se True attende la fine della riproduzione (sincrono).
                  Se False la riproduzione avviene in background.
    """
    if not testo or not testo.strip():
        return

    def _play():
        try:
            kokoro = _get_kokoro()
            samples, sample_rate = kokoro.create(
                testo,
                voice=voce,
                speed=velocita,
                lang=LINGUA,
            )
            _in_riproduzione.set()
            sd.play(samples, sample_rate)
            sd.wait()
        except Exception as e:
            print(f"⚠️ TTS error: {e}")
        finally:
            _in_riproduzione.clear()

    if blocca:
        _play()
    else:
        t = threading.Thread(target=_play, daemon=True)
        t.start()


def interrompi() -> None:
    """Ferma immediatamente la riproduzione in corso."""
    sd.stop()
    _in_riproduzione.clear()


def sta_parlando() -> bool:
    """Ritorna True se è in corso una riproduzione audio."""
    return _in_riproduzione.is_set()


def precarica() -> None:
    """Forcefully carica il modello in memoria (utile all'avvio)."""
    threading.Thread(target=_get_kokoro, daemon=True).start()


# ─── Test rapido ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Test TTS con Kokoro-ONNX")
    parla("Ciao, sono IDIS, il tuo assistente intelligente. Come posso aiutarti?")
