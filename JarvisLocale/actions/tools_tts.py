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
import esp32_bridge

try:
    import sounddevice as sd
    import numpy as np
    from kokoro_onnx import Kokoro
    _DEPENDENCIES_OK = True
except ImportError as e:
    print(f"⚠️ Dipendenze TTS mancanti: {e}")
    _DEPENDENCIES_OK = False

# ── Path assoluti ────────────────────────────────────────────────────────────
_BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ONNX_PATH   = os.path.join(_BASE_DIR, "kokoro-v1.0.onnx")
_VOICES_PATH = os.path.join(_BASE_DIR, "voices-v1.0.bin")

# ── Configurazione ───────────────────────────────────────────────────────────
VOCE_DEFAULT     = os.getenv("IDIS_VOICE", "if_sara")
VELOCITA_DEFAULT = float(os.getenv("IDIS_VOICE_SPEED", "1.05"))
LINGUA           = "it"

# Punteggiatura che segnala la fine di una frase (flush al TTS)
# .!?: flush immediato | virgola dopo 20+ chars buffer → flush
_SEPARATORI = re.compile(r'(?<=[.!?;:])\s+')
_MIN_CHARS_VIRGOLA = 20   # flush su virgola solo se buffer >= N chars

# ── Stato globale ────────────────────────────────────────────────────────────
_kokoro: "Kokoro" | None = None
_kokoro_lock           = threading.Lock()
_tts_abilitato         = True

_stop_event            = threading.Event()
_coda_frasi: queue.Queue = queue.Queue()
_coda_audio: queue.Queue = queue.Queue(maxsize=4)

_thread_sintesi:       threading.Thread | None = None
_thread_riproduzione:  threading.Thread | None = None
_session_id:           int = 0


# ── Init modello ─────────────────────────────────────────────────────────────

def _carica_kokoro() -> None:
    global _kokoro, _tts_abilitato
    if not _DEPENDENCIES_OK:
        _tts_abilitato = False
        return

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


def _get_kokoro() -> "Kokoro" | None:
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

def _worker_sintesi(session_id: int):
    """Thread che prende frasi da _coda_frasi e genera audio in _coda_audio."""
    kokoro = _get_kokoro()
    if kokoro is None:
        return

    while session_id == _session_id:
        try:
            frase = _coda_frasi.get(timeout=1)
        except queue.Empty:
            if _stop_event.is_set() or session_id != _session_id:
                break
            continue

        if frase is None or session_id != _session_id:  # Segnale di fine
            if session_id == _session_id:
                _coda_audio.put(None)
            break

        if _stop_event.is_set():
            # Svuota la coda rimanente senza sintetizzare
            while not _coda_frasi.empty():
                try: _coda_frasi.get_nowait()
                except: pass
            if session_id == _session_id:
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

def _worker_riproduzione(session_id: int):
    """Thread che prende audio da _coda_audio e lo riproduce sequenzialmente."""
    while session_id == _session_id:
        try:
            item = _coda_audio.get(timeout=1)
        except queue.Empty:
            if _stop_event.is_set() or session_id != _session_id:
                break
            continue

        if item is None or session_id != _session_id:  # Segnale di fine
            esp32_bridge.set_ai_state("idle")
            break

        if _stop_event.is_set():
            esp32_bridge.set_ai_state("idle")
            break

        samples, rate = item
        try:
            esp32_bridge.set_ai_state("speaking")
            if _DEPENDENCIES_OK: sd.play(samples, rate)
            if _DEPENDENCIES_OK: sd.wait()
        except Exception as e:
            print(f"[TTS] Errore riproduzione: {e}")
            esp32_bridge.set_ai_state("idle")


# ── API pubblica ─────────────────────────────────────────────────────────────

def avvia_sessione_streaming() -> None:
    """
    Avvia la pipeline TTS streaming.
    Chiama questa funzione PRIMA di iniziare a passare chunk con `alimenta_chunk()`.
    """
    global _thread_sintesi, _thread_riproduzione, _session_id

    ferma()  # Ferma eventuali sessioni precedenti

    _stop_event.clear()
    _session_id += 1
    current_session = _session_id

    # Svuota le code
    while not _coda_frasi.empty():
        try: _coda_frasi.get_nowait()
        except: pass
    while not _coda_audio.empty():
        try: _coda_audio.get_nowait()
        except: pass

    _thread_sintesi      = threading.Thread(target=_worker_sintesi, args=(current_session,), daemon=True, name="TTS-Sintesi")
    _thread_riproduzione = threading.Thread(target=_worker_riproduzione, args=(current_session,), daemon=True, name="TTS-Play")
    _thread_sintesi.start()
    _thread_riproduzione.start()


# Buffer interno per raccogliere i chunk parziali
_buffer_chunk = ""
_buffer_lock  = threading.Lock()


def alimenta_chunk(testo_parziale: str) -> None:
    """
    Ricevi un chunk di testo dall'LLM stream.
    Flush su: .!?;: | virgola dopo _MIN_CHARS_VIRGOLA chars | buffer >= 80 chars
    """
    global _buffer_chunk

    if not _tts_abilitato or _stop_event.is_set():
        return

    with _buffer_lock:
        _buffer_chunk += testo_parziale

        # Flush su punteggiatura forte (.!?;:)
        parti = re.split(r'(?<=[.!?;:])\s+', _buffer_chunk)
        if len(parti) > 1:
            for frase_completa in parti[:-1]:
                frase_completa = frase_completa.strip()
                if frase_completa:
                    _coda_frasi.put(frase_completa)
            _buffer_chunk = parti[-1]
            return

        # Flush su virgola se buffer abbastanza lungo
        if ',' in _buffer_chunk and len(_buffer_chunk) >= _MIN_CHARS_VIRGOLA:
            idx = _buffer_chunk.rfind(',')
            frase = _buffer_chunk[:idx].strip()
            if frase:
                _coda_frasi.put(frase)
            _buffer_chunk = _buffer_chunk[idx+1:].lstrip()
            return

        # Flush forzato se buffer troppo lungo (evita attese su frasi senza punteggiatura)
        if len(_buffer_chunk) >= 80:
            # Trova l'ultimo spazio per non spezzare le parole
            idx = _buffer_chunk.rfind(' ', 0, 80)
            if idx > 20:
                frase = _buffer_chunk[:idx].strip()
                _coda_frasi.put(frase)
                _buffer_chunk = _buffer_chunk[idx:].lstrip()


def chiudi_sessione_streaming() -> None:
    """
    Segnala che il testo è terminato.
    Manda il residuo nel buffer e chiude la pipeline.
    NON bloccante — i worker finiscono in background senza bloccare la UI.
    """
    global _buffer_chunk

    with _buffer_lock:
        residuo = _buffer_chunk.strip()
        _buffer_chunk = ""
        if residuo:
            _coda_frasi.put(residuo)

    # Segnale di fine — i worker si fermano da soli quando la coda si svuota
    _coda_frasi.put(None)
    # Niente join() — la UI torna subito disponibile mentre l'audio finisce in background


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
                esp32_bridge.set_ai_state("speaking")
                if _DEPENDENCIES_OK: sd.play(samples, rate)
                if _DEPENDENCIES_OK: sd.wait()
                esp32_bridge.set_ai_state("idle")
        except Exception as e:
            print(f"[TTS] Errore: {e}")
            esp32_bridge.set_ai_state("idle")

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
        if _DEPENDENCIES_OK: sd.stop()
        esp32_bridge.set_ai_state("idle")
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