import serial
import time
import threading
import datetime
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

def _log(tag: str, msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][{tag}] {msg}")

@router.post("/sensors")
async def receive_sensors(data: dict):
    sensor_data.update(data)
    return {"ok": True}

@router.get("/alarm/check")
async def check_alarm():
    from alarm.alarm_service import alarm_state
    return {"ring": alarm_state["ring"]}

# ── Stark Station ──────────────────────────────────────────────
stark_station_data = {
    "temperatura": None,
    "umidita": None,
    "presenza": False
}

@router.post("/stark_station/sensori")
async def stark_sensori(data: dict):
    stark_station_data["temperatura"] = data.get("temperatura")
    stark_station_data["umidita"] = data.get("umidita")
    _log("STARK", f"Temp: {stark_station_data['temperatura']}°C | Umidità: {stark_station_data['umidita']}%")
    return {"status": "ok"}

_timer_assenza = None

@router.post("/stark_station/presenza")
async def stark_presenza(data: dict):
    global _timer_assenza
    presenza_attuale = data.get("presenza", False)
    stark_station_data["presenza"] = presenza_attuale
    stato_str = "Rilevata" if presenza_attuale else "Nessuno"
    _log("STARK", f"Presenza: {stato_str}")
    
    try:
        from automations.profilo_uscita import esegui_profilo_uscita, esegui_profilo_rientro
        
        if presenza_attuale:
            if _timer_assenza is not None:
                _timer_assenza.cancel()
                _timer_assenza = None
                _log("STARK", "Timer assenza annullato (presenza rilevata).")
            
            # Prova a rientrare (il modulo stesso controlla se l'utente era "fuori")
            threading.Thread(target=esegui_profilo_rientro, daemon=True).start()
        else:
            if _timer_assenza is None:
                def scadenza_assenza():
                    global _timer_assenza
                    _timer_assenza = None
                    if not stark_station_data["presenza"]:
                        _log("STARK", "Timeout 5 min senza attività: avvio profilo uscita.")
                        # Forza l'uscita automatica
                        esegui_profilo_uscita("Assenza rilevata dalla Stark Station")
                        
                _timer_assenza = threading.Timer(300.0, scadenza_assenza) # 300 sec = 5 min
                _timer_assenza.daemon = True
                _timer_assenza.start()
                _log("STARK", "Nessuna presenza: avviato timer di 5 minuti.")
                
    except Exception as e:
        _log("STARK", f"Errore gestione timer presenza: {e}")
        
    return {"status": "ok"}

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