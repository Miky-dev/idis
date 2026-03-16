import serial
import time
import threading
from fastapi import APIRouter

# ══════════════════════════════════════════════════════════════
# CONFIGURAZIONE ESP32
# ══════════════════════════════════════════════════════════════
PORTA_ESP32 = 'COM5'
BAUD_RATE   = 115200
TIMEOUT_SEC = 0.1

_esp32 = None
_stato_corrente = None
_thread_reconnect = None
_stop_thread = False

MAPPA_STATI = {
    'sleep': 'R',
    'idle': 'I',
    'thinking': 'P',
    'speaking': 'S'
}

# ── Dati sensori (aggiornati dall'ESP32 sveglia via HTTP) ──────
sensor_data = {"temp": None, "humidity": None, "co2": None}

# ── Router FastAPI ─────────────────────────────────────────────
router = APIRouter()

@router.post("/sensors")
async def receive_sensors(data: dict):
    sensor_data.update(data)
    return {"ok": True}

@router.get("/alarm/check")
async def check_alarm():
    from alarm.alarm_service import alarm_state
    return {"ring": alarm_state["ring"]}

# ══════════════════════════════════════════════════════════════
# LOGICA SERIALE (invariata)
# ══════════════════════════════════════════════════════════════
def set_ai_state(stato_sfera: str):
    global _esp32, _stato_corrente
    char_cmd = MAPPA_STATI.get(stato_sfera.lower(), 'R')
    if _stato_corrente == char_cmd:
        return
    if _esp32 and _esp32.is_open:
        try:
            _esp32.write(char_cmd.encode('utf-8'))
            _stato_corrente = char_cmd
        except Exception as e:
            _chiudi_porta()
    else:
        _stato_corrente = char_cmd

def _chiudi_porta():
    global _esp32
    if _esp32:
        try:
            _esp32.close()
        except Exception:
            pass
    _esp32 = None

def _gestore_riconnessione():
    global _esp32, _stop_thread, _stato_corrente
    while not _stop_thread:
        if _esp32 is None or not _esp32.is_open:
            try:
                _esp32 = serial.Serial(port=PORTA_ESP32, baudrate=BAUD_RATE, timeout=TIMEOUT_SEC)
                print(f"✅ ESP32 Eye Display connesso su porta {PORTA_ESP32}")
                ultimo = _stato_corrente if _stato_corrente else 'R'
                _stato_corrente = None
                time.sleep(1)
                set_ai_state("sleep" if ultimo == 'R' else "idle" if ultimo == 'I' else "thinking" if ultimo == 'P' else "speaking")
            except Exception:
                _esp32 = None
        time.sleep(3)

def inizializza():
    global _thread_reconnect, _stop_thread
    _stop_thread = False
    _thread_reconnect = threading.Thread(target=_gestore_riconnessione, daemon=True, name="ESP32Reconnect")
    _thread_reconnect.start()

def ferma():
    global _stop_thread
    _stop_thread = True
    _chiudi_porta()