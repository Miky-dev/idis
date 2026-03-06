"""
tools_tts.py — Sintesi vocale STREAMING con Kokoro-ONNX per IDIS.

Pipeline: LLM stream → buffer frasi → coda TTS → coda audio → altoparlante
Le prime parole vengono riprodotte entro ~1-2s dall'inizio della risposta.

Richiede nella cartella JarvisLocale:
  - kokoro-v1.0.onnx
  - voices-v1.0.bin
"""

import threading
import queue
import re
import os

import sounddevice as sd
import numpy as np
from kokoro_onnx import Kokoro

# ── Path assoluti ────────────────────────────────────────────────────────────
_BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ONNX_PATH   = os.path.join(_BASE_DIR, "kokoro-v1.0.onnx")
_VOICES_PATH = os.path.join(_BASE_DIR, "voices-v1.0.bin")

# ── Configurazione ───────────────────────────────────────────────────────────
VOCE_DEFAULT     = os.getenv("IDIS_VOICE", "if_sara")
VELOCITA_DEFAULT = float(os.getenv("IDIS_VOICE_SPEED", "1.05"))
LINGUA           = "it"

# Punteggiatura che segnala la fine di una frase (flush al TTS)
_SEPARATORI = re.compile(r'(?<=[.!?;])\s+|(?<=,)\s+(?=\S{4,})')

# ── Stato globale ────────────────────────────────────────────────────────────
_kokoro: Kokoro | None = None
_kokoro_lock           = threading.Lock()
_tts_abilitato         = True

_stop_event            = threading.Event()
_coda_frasi: queue.Queue = queue.Queue()
_coda_audio: queue.Queue = queue.Queue(maxsize=4)

_thread_sintesi:       threading.Thread | None = None
_thread_riproduzione:  threading.Thread | None = None


# ── Init modello ─────────────────────────────────────────────────────────────

def _carica_kokoro() -> None:
    global _kokoro, _tts_abilitato
    try:
        print(f"⏳ Caricamento Kokoro TTS...")
        _kokoro = Kokoro(_ONNX_PATH, _VOICES_PATH)
        print("🔊 Kokoro TTS pronto.")
    except FileNotFoundError as e:
        print(f"⚠️ File modello non trovato: {e}")
        print(f"   Assicurati che 'kokoro-v1.0.onnx' e 'voices-v1.0.bin' siano in: {_BASE_DIR}")
        _tts_abilitato = False
    except Exception as e:
        print(f"⚠️ Kokoro non disponibile: {e}")
        _tts_abilitato = False


def _get_kokoro() -> "Kokoro | None":
    global _kokoro
    if _kokoro is None and _tts_abilitato:
        with _kokoro_lock:
            if _kokoro is None:
                _carica_kokoro()
    return _kokoro


# ── Pulizia testo ────────────────────────────────────────────────────────────

def _pulisci(testo: str) -> str:
    testo = re.sub(r'https?://\S+', '', testo)
    testo = re.sub(r'\*+([^*]+)\*+', r'\1', testo)
    testo = re.sub(r'_+([^_]+)_+', r'\1', testo)
    testo = re.sub(r'`[^`]*`', '', testo)
    testo = re.sub(r'```[\s\S]*?```', '', testo)
    testo = re.sub(r'[\U00010000-\U0010ffff]', '', testo)
    testo = re.sub(r'[#\[\]|>]', '', testo)
    testo = re.sub(r'\s+', ' ', testo).strip()
    return testo


# ── Worker sintesi: prende frasi dalla coda, genera audio ───────────────────

def _worker_sintesi():
    """Thread che prende frasi da _coda_frasi e genera audio in _coda_audio."""
    kokoro = _get_kokoro()
    if kokoro is None:
        return

    while True:
        try:
            frase = _coda_frasi.get(timeout=5)
        except queue.Empty:
            break

        if frase is None:  # Segnale di fine
            _coda_audio.put(None)
            break

        if _stop_event.is_set():
            # Svuota la coda rimanente senza sintetizzare
            while not _coda_frasi.empty():
                try: _coda_frasi.get_nowait()
                except: pass
            _coda_audio.put(None)
            break

        frase = _pulisci(frase)
        if not frase:
            continue

        try:
            samples, rate = kokoro.create(
                frase,
                voice=VOCE_DEFAULT,
                speed=VELOCITA_DEFAULT,
                lang=LINGUA,
            )
            if not _stop_event.is_set():
                _coda_audio.put((samples, rate))
        except Exception as e:
            print(f"[TTS] Errore sintesi: {e}")


# ── Worker riproduzione: prende audio dalla coda e lo suona ─────────────────

def _worker_riproduzione():
    """Thread che prende audio da _coda_audio e lo riproduce sequenzialmente."""
    while True:
        try:
            item = _coda_audio.get(timeout=10)
        except queue.Empty:
            break

        if item is None:  # Segnale di fine
            break

        if _stop_event.is_set():
            break

        samples, rate = item
        try:
            sd.play(samples, rate)
            sd.wait()
        except Exception as e:
            print(f"[TTS] Errore riproduzione: {e}")


# ── API pubblica ─────────────────────────────────────────────────────────────

def avvia_sessione_streaming() -> None:
    """
    Avvia la pipeline TTS streaming.
    Chiama questa funzione PRIMA di iniziare a passare chunk con `alimenta_chunk()`.
    """
    global _thread_sintesi, _thread_riproduzione

    ferma()  # Ferma eventuali sessioni precedenti

    _stop_event.clear()

    # Svuota le code
    while not _coda_frasi.empty():
        try: _coda_frasi.get_nowait()
        except: pass
    while not _coda_audio.empty():
        try: _coda_audio.get_nowait()
        except: pass

    _thread_sintesi      = threading.Thread(target=_worker_sintesi, daemon=True, name="TTS-Sintesi")
    _thread_riproduzione = threading.Thread(target=_worker_riproduzione, daemon=True, name="TTS-Play")
    _thread_sintesi.start()
    _thread_riproduzione.start()


# Buffer interno per raccogliere i chunk parziali
_buffer_chunk = ""
_buffer_lock  = threading.Lock()


def alimenta_chunk(testo_parziale: str) -> None:
    """
    Ricevi un chunk di testo dall'LLM stream.
    Quando il buffer contiene una frase completa, la manda al TTS.
    """
    global _buffer_chunk

    if not _tts_abilitato or _stop_event.is_set():
        return

    with _buffer_lock:
        _buffer_chunk += testo_parziale

        # Cerca separatori di frase nel buffer
        parti = re.split(r'(?<=[.!?;])\s+', _buffer_chunk)

        if len(parti) > 1:
            # Le prime N-1 parti sono frasi complete; l'ultima è ancora in costruzione
            for frase_completa in parti[:-1]:
                frase_completa = frase_completa.strip()
                if frase_completa:
                    _coda_frasi.put(frase_completa)
            _buffer_chunk = parti[-1]


def chiudi_sessione_streaming() -> None:
    """
    Segnala che il testo è terminato.
    Manda il residuo nel buffer al TTS e aspetta che la riproduzione finisca.
    """
    global _buffer_chunk

    with _buffer_lock:
        residuo = _buffer_chunk.strip()
        _buffer_chunk = ""
        if residuo:
            _coda_frasi.put(residuo)

    # Segnale di fine alla pipeline
    _coda_frasi.put(None)

    # Aspetta che entrambi i worker finiscano
    if _thread_sintesi:
        _thread_sintesi.join(timeout=30)
    if _thread_riproduzione:
        _thread_riproduzione.join(timeout=30)


def parla(testo: str, bloccante: bool = False) -> None:
    """
    Sintetizza e riproduce una stringa completa (non streaming).
    Usato per notifiche brevi, supervisore, ecc.
    """
    if not _tts_abilitato:
        return
    kokoro = _get_kokoro()
    if kokoro is None:
        return

    testo_pulito = _pulisci(testo)
    if not testo_pulito:
        return

    def _play():
        try:
            samples, rate = kokoro.create(testo_pulito, voice=VOCE_DEFAULT,
                                           speed=VELOCITA_DEFAULT, lang=LINGUA)
            if not _stop_event.is_set():
                sd.play(samples, rate)
                sd.wait()
        except Exception as e:
            print(f"[TTS] Errore: {e}")

    if bloccante:
        _play()
    else:
        threading.Thread(target=_play, daemon=True).start()


def ferma() -> None:
    """Interrompe immediatamente qualsiasi riproduzione in corso."""
    global _buffer_chunk
    _stop_event.set()
    _buffer_chunk = ""
    try:
        sd.stop()
    except Exception:
        pass


def sta_parlando() -> bool:
    return (
        (_thread_riproduzione is not None and _thread_riproduzione.is_alive()) or
        (_thread_sintesi is not None and _thread_sintesi.is_alive())
    )


def avvia_precaricamento() -> None:
    """Carica Kokoro in background all'avvio."""
    threading.Thread(target=_carica_kokoro, daemon=True, name="KokoroInit").start()


# ─── Test rapido ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _carica_kokoro()
    avvia_sessione_streaming()
    testo_test = "Ciao! Sono IDIS, il tuo assistente intelligente. Oggi fa un po' freddo, ma sono pronto ad aiutarti."
    for parola in testo_test.split():
        alimenta_chunk(parola + " ")
    chiudi_sessione_streaming()
    print("Test completato.")