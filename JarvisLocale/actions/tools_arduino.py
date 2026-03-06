import serial
import time
import threading
from langchain_core.tools import tool

PORTA_ARDUINO = 'COM3'
arduino = None
stato_led_attuale = "SPENTO"


def get_stato_led() -> str:
    return stato_led_attuale


@tool
def ottieni_stato_led() -> str:
    """Restituisce lo stato attuale della luce (ACCESO o SPENTO)."""
    return stato_led_attuale

def imposta_animazione_pensiero(attiva: bool):
    """Invia il comando per attivare o disattivare l'animazione di pensiero."""
    global arduino
    if arduino and arduino.is_open:
        try:
            stato = "ON" if attiva else "OFF"
            arduino.write(f"THINK_{stato}\n".encode('utf-8'))
        except Exception:
            pass

def _connetti_arduino_thread():
    """Connessione Arduino in background — non blocca l'avvio dell'app."""
    global arduino
    try:
        arduino = serial.Serial(PORTA_ARDUINO, 9600, timeout=2)
        # Arduino si riavvia all'apertura seriale, aspettiamo in background
        time.sleep(2)
        print(f"✅ JARVIS connesso ad Arduino sulla porta {PORTA_ARDUINO}")
    except Exception as e:
        print(f"⚠️ Arduino non disponibile: {e}. Funzionalità LED disabilitate.")
        arduino = None

# ✅ Connessione in thread separato — non blocca l'avvio dell'app
threading.Thread(target=_connetti_arduino_thread, daemon=True).start()

@tool
def controlla_led(stato: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede di accendere o spegnere la luce o il LED.
    L'argomento 'stato' DEVE essere esattamente "ON" (per accendere) oppure "OFF" (per spegnere).
    """
    global arduino, stato_led_attuale
    if not arduino or not arduino.is_open:
        return "Errore hardware: Arduino è scollegato o non ancora connesso."

    try:
        arduino.reset_input_buffer()
        comando_seriale = f"LED_{stato.upper()}\n"
        arduino.write(comando_seriale.encode('utf-8'))
        time.sleep(0.5)

        if arduino.in_waiting > 0:
            try:
                arduino.readline().decode('utf-8').strip()
            except Exception:
                pass

        # Aggiorna lo stato globale
        stato_led_attuale = "ACCESO" if stato.upper() == "ON" else "SPENTO"
        return stato_led_attuale

    except Exception as e:
        return f"Errore durante l'invio del segnale: {str(e)}"