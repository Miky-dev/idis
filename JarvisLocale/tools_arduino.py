import serial
import time
from langchain_core.tools import tool

# INSERISCI QUI LA TUA PORTA ESATTA (es. 'COM3', 'COM4', ecc.)
PORTA_ARDUINO = 'COM3' 
arduino = None

# Variabile per tenere traccia dello stato in tempo reale (all'avvio l'Arduino setta LOW)
stato_led_attuale = "SPENTO"

def ottieni_stato_led() -> str:
    """Restituisce lo stato attuale della luce."""
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

def connetti_arduino():
    """Tenta di aprire la connessione con Arduino all'avvio."""
    global arduino
    if arduino is None:
        try:
            arduino = serial.Serial(PORTA_ARDUINO, 9600, timeout=2)
            # Quando si apre la seriale, Arduino si riavvia fisicamente. 
            # Dobbiamo aspettare 2 secondi in silenzio prima di parlargli!
            time.sleep(2) 
            print(f"✅ JARVIS connesso fisicamente ad Arduino sulla porta {PORTA_ARDUINO}")
        except Exception as e:
            print(f"❌ Errore connessione Arduino: {e}. Controlla il cavo o chiudi l'IDE.")

# Proviamo a connetterci appena l'app si avvia
connetti_arduino()

@tool
def controlla_led(stato: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede di accendere o spegnere la luce o il LED.
    L'argomento 'stato' DEVE essere esattamente "ON" (per accendere) oppure "OFF" (per spegnere).
    """
    global arduino
    if not arduino or not arduino.is_open:
        return "Errore hardware: Il braccio robotico (Arduino) è scollegato o occupato."

    try:
        # Puliamo il canale di comunicazione
        arduino.reset_input_buffer()
        
        # Assembliamo il comando da spedire via cavo (es. "LED_ON\n")
        comando_seriale = f"LED_{stato.upper()}\n"
        arduino.write(comando_seriale.encode('utf-8'))
        
        # Diamo ad Arduino mezzo secondo per eseguire e risponderci
        time.sleep(0.5)
        
        # Leggiamo la risposta di Arduino ("Ricevuto: accendo il Pin 12!")
        if arduino.in_waiting > 0:
            risposta_arduino = arduino.readline().decode('utf-8').strip()
            
            # Aggiorna la memoria globale dello stato hardware
            global stato_led_attuales
            stato_led_attuale = "ACCESO" if stato.upper() == "ON" else "SPENTO"
            
            return f"{stato_led_attuale}"
        else:
            return f"Ho inviato il segnale per {stato}, ma l'hardware non ha confermasto."
            
    except Exception as e:
        return f"Errore durante l'invio del segnale elettrico: {str(e)}"
