"""
tools_sounds.py — Feedback audio sintetizzato per IDIS.

Suoni generati al volo con numpy, riprodotti con sounddevice.
Zero file esterni — tutto in memoria, cachato all'avvio.

Mappa stati:
  thinking  → doppio tono ascendente sci-fi (conferma ricezione)
  speaking  → click naturale morbido (sta per parlare)
  idle      → tono discendente + fade (risposta completata)
  error     → tono dissonante breve (qualcosa è andato storto)
  wake      → trillo ascendente (IDIS si attiva / saluto)
"""

import threading
import numpy as np

try:
    import sounddevice as sd
    _SD_OK = True
except Exception:
    _SD_OK = False
    print("[SOUNDS] sounddevice non disponibile — suoni disabilitati.")

# ── Configurazione ────────────────────────────────────────────
SR         = 22050    # sample rate
_abilitato = True
_volume    = 0.35     # 0.0 – 1.0
_cache: dict[str, np.ndarray] = {}   # suoni pre-renderizzati
_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════
# GENERATORI PRIMITIVI
# ══════════════════════════════════════════════════════════════

def _t(durata_s: float) -> np.ndarray:
    """Asse temporale."""
    return np.linspace(0, durata_s, int(SR * durata_s), endpoint=False)

def _sine(freq: float, durata_s: float, amp: float = 1.0) -> np.ndarray:
    t = _t(durata_s)
    return amp * np.sin(2 * np.pi * freq * t).astype(np.float32)

def _env(sig: np.ndarray, attack: float = 0.01, decay: float = 0.05,
         sustain: float = 0.7, release: float = 0.1) -> np.ndarray:
    """Envelope ADSR applicata al segnale."""
    n      = len(sig)
    a_n    = int(SR * attack)
    d_n    = int(SR * decay)
    r_n    = int(SR * release)
    s_n    = n - a_n - d_n - r_n

    env = np.zeros(n, dtype=np.float32)
    if a_n > 0:
        env[:a_n]               = np.linspace(0, 1, a_n)
    if d_n > 0:
        env[a_n:a_n+d_n]        = np.linspace(1, sustain, d_n)
    if s_n > 0:
        env[a_n+d_n:a_n+d_n+s_n] = sustain
    if r_n > 0:
        env[-r_n:]              = np.linspace(sustain, 0, r_n)
    return (sig * env).astype(np.float32)

def _fade_out(sig: np.ndarray, fade_s: float = 0.05) -> np.ndarray:
    fade_n = min(int(SR * fade_s), len(sig))
    out    = sig.copy()
    out[-fade_n:] *= np.linspace(1, 0, fade_n)
    return out

def _concat(*arrays) -> np.ndarray:
    return np.concatenate(arrays).astype(np.float32)

def _silence(durata_s: float) -> np.ndarray:
    return np.zeros(int(SR * durata_s), dtype=np.float32)

def _click(durata_s: float = 0.004, freq: float = 1800.0) -> np.ndarray:
    """Click naturale: burst di rumore filtrato."""
    n    = int(SR * durata_s)
    noise = np.random.randn(n).astype(np.float32)
    tone  = _sine(freq, durata_s, 0.4)
    click = noise * 0.6 + tone
    env   = np.linspace(1, 0, n) ** 2
    return (click * env).astype(np.float32)


# ══════════════════════════════════════════════════════════════
# DESIGN DEI SUONI
# ══════════════════════════════════════════════════════════════

def _build_thinking() -> np.ndarray:
    """
    Doppio tono ascendente sci-fi — conferma 'ho ricevuto, sto pensando'.
    Due brevi beep (880 Hz → 1320 Hz) con pausa micro.
    """
    t1 = _env(_sine(880,  0.07), attack=0.005, decay=0.02, sustain=0.6, release=0.04)
    t2 = _env(_sine(1320, 0.07), attack=0.005, decay=0.02, sustain=0.6, release=0.04)
    return _concat(t1, _silence(0.04), t2)


def _build_speaking() -> np.ndarray:
    """
    Click morbido naturale — 'sto per parlare'.
    Suono basso e discreto, non invasivo.
    """
    c1 = _click(0.005, 900)
    c2 = _click(0.004, 700)
    return _concat(c1, _silence(0.01), c2)


def _build_idle() -> np.ndarray:
    """
    Tono discendente con fade — 'risposta completata'.
    1200 Hz → 800 Hz → 500 Hz, stile notifica completamento.
    """
    t1 = _env(_sine(1200, 0.08), attack=0.005, decay=0.03, sustain=0.5, release=0.05)
    t2 = _env(_sine(800,  0.08), attack=0.003, decay=0.03, sustain=0.4, release=0.06)
    t3 = _env(_sine(500,  0.10), attack=0.003, decay=0.02, sustain=0.3, release=0.08)
    return _fade_out(_concat(t1, _silence(0.03), t2, _silence(0.03), t3), 0.04)


def _build_error() -> np.ndarray:
    """
    Tono dissonante breve — 'qualcosa è andato storto'.
    Due frequenze ravvicinate creano battimento fastidioso ma breve.
    """
    t1 = _env(_sine(440, 0.15, 0.7), attack=0.01, decay=0.05, sustain=0.5, release=0.08)
    t2 = _env(_sine(466, 0.15, 0.7), attack=0.01, decay=0.05, sustain=0.5, release=0.08)
    return _fade_out((t1 + t2) * 0.5, 0.03)


def _build_wake() -> np.ndarray:
    """
    Trillo ascendente — 'IDIS attivo / saluto'.
    Tre note rapide in crescendo (Do-Mi-Sol).
    """
    t1 = _env(_sine(523,  0.06), attack=0.005, decay=0.02, sustain=0.6, release=0.03)
    t2 = _env(_sine(659,  0.06), attack=0.005, decay=0.02, sustain=0.6, release=0.03)
    t3 = _env(_sine(784,  0.09), attack=0.005, decay=0.03, sustain=0.7, release=0.05)
    return _concat(t1, _silence(0.025), t2, _silence(0.025), t3)


# ══════════════════════════════════════════════════════════════
# INIT — pre-render all'avvio
# ══════════════════════════════════════════════════════════════

def _prerenderizza():
    """Genera e cacha tutti i suoni in background all'avvio."""
    global _cache
    _cache = {
        "thinking": _build_thinking(),
        "speaking": _build_speaking(),
        "idle":     _build_idle(),
        "error":    _build_error(),
        "wake":     _build_wake(),
    }
    print(f"[SOUNDS] {len(_cache)} suoni pre-renderizzati. ✓")


def avvia_precaricamento():
    """Chiamato da avvia_background() in logica_chat."""
    threading.Thread(target=_prerenderizza, daemon=True, name="SoundsInit").start()


# ══════════════════════════════════════════════════════════════
# RIPRODUZIONE
# ══════════════════════════════════════════════════════════════

def _play_raw(samples: np.ndarray):
    """Riproduce samples float32 in modo non bloccante."""
    if not _SD_OK or not _abilitato:
        return
    try:
        sd.play(samples * _volume, SR, blocking=False)
    except Exception as e:
        print(f"[SOUNDS] Errore riproduzione: {e}")


def suona(stato: str):
    """
    Riproduce il suono associato allo stato.
    Non bloccante — ritorna immediatamente.

    stati validi: 'thinking', 'speaking', 'idle', 'error', 'wake'
    """
    if not _abilitato:
        return
    with _lock:
        samples = _cache.get(stato)
    if samples is None:
        # Cache non ancora pronta — genera al volo (prima volta)
        builders = {
            "thinking": _build_thinking,
            "speaking": _build_speaking,
            "idle":     _build_idle,
            "error":    _build_error,
            "wake":     _build_wake,
        }
        fn = builders.get(stato)
        if fn is None:
            return
        samples = fn()
        with _lock:
            _cache[stato] = samples

    threading.Thread(target=_play_raw, args=(samples,), daemon=True).start()


# ── Shortcut ─────────────────────────────────────────────────
def thinking(): suona("thinking")
def speaking():  suona("speaking")
def idle():      suona("idle")
def error():     suona("error")
def wake():      suona("wake")


# ── Controlli ────────────────────────────────────────────────
def set_volume(v: float):
    """Imposta volume 0.0–1.0."""
    global _volume
    _volume = max(0.0, min(1.0, v))

def abilita(val: bool):
    global _abilitato
    _abilitato = val


# ── Test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    _prerenderizza()
    for nome in ["wake", "thinking", "speaking", "idle", "error"]:
        print(f"  → {nome}")
        suona(nome)
        time.sleep(0.8)
    time.sleep(1)
    print("Test completato.")