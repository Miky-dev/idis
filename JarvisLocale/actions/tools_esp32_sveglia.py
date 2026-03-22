import os
import requests
import time
from langchain_core.tools import tool
from dotenv import load_dotenv

load_dotenv()

ESP32_IP = os.getenv("ESP32_SVEGLIA_IP", "http://192.168.1.212")

def verifica_connessione_sveglia():
    """Ping iniziale per verificare che la sveglia ESP32 sia online."""
    url = f"{ESP32_IP}/"
    try:
        # Timeout aumentato a 5s perché la lettura dei sensori (DHT ecc.) 
        # sull'ESP32 può bloccare temporaneamente il web server
        requests.get(url, timeout=5)
        print(f"✅ JARVIS connesso a Stark Station (Sveglia ESP32) su {ESP32_IP}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Stark Station (Sveglia ESP32) non raggiungibile su {ESP32_IP} (Errore: {e}). I comandi remoti potrebbero fallire.")
        return False


@tool
def invia_comando_sveglia(azione: str) -> str:
    """
    Invia un comando alla Stark Station, che è la SVEGLIA SUL COMODINO e gestisce le LUCI DEL LETTO.
    Usa questo strumento per accendere/spegnere le luci del letto, o per attivare un protocollo.
    Il parametro 'azione' DEVE essere ESATTAMENTE uno dei seguenti valori:
    - "rosso"      -> (per protocollo alba rossa / luce rossa)
    - "matrix"     -> (per protocollo matrix / luce verde)
    - "cyberpunk"  -> (per protocollo cyberpunk / luce viola)
    - "lavoro"     -> (per modalità lavoro / luce bianca / accensione base)
    - "off"        -> (per spegnere le luci del letto / spegni tutto)
    - "lum_max"    -> (per impostare la luminosità al massimo)
    - "lum_media"  -> (per impostare la luminosità a un livello medio)
    - "lum_bassa"  -> (per impostare la luminosità al minimo / bassa)
    """
    
    # Dizionario di sicurezza: se l'IA invia "bianca", lo tradiamo nella rotta corretta dell'ESP32 "/lavoro"
    sinonimi = {
        "bianca": "lavoro", "bianco": "lavoro",
        "verde": "matrix",
        "viola": "cyberpunk",
        "rosso": "rosso",
        "rossa": "rosso",
        "alba_rossa": "rosso",
        "massimo": "lum_max", "massima": "lum_max", "alta": "lum_max",
        "media": "lum_media", "medio": "lum_media",
        "bassa": "lum_bassa", "minimo": "lum_bassa", "minima": "lum_bassa"
    }
    azione_reale = sinonimi.get(azione.lower(), azione.lower())
    
    url = f"{ESP32_IP}/{azione_reale}"
    try:
        print(f"JARVIS: Invio comando '{azione_reale}' alla Stark Station su {url}...")
        risposta = requests.get(url, timeout=10)
        if risposta.status_code == 200:
            msg = f"Comando '{azione}' eseguito con successo sulla Stark Station."
            print(f"JARVIS: {msg}")
            return msg
        else:
            msg = f"Errore di comunicazione con la sveglia. Status: {risposta.status_code}"
            print(f"JARVIS: {msg}")
            return msg
    except requests.exceptions.RequestException as e:
        msg = f"Impossibile contattare la sveglia Stark Station. Errore: {e}"
        print(f"JARVIS: {msg}")
        return msg

@tool
def leggi_sensori_stanza() -> str:
    """
    Legge i dati dei sensori (temperatura, umidità e presenza umana) nella stanza 
    rilevati dalla Stark Station (ESP32).
    Usa questo strumento per rispondere a domande sulla temperatura in camera, 
    l'umidità interna o per sapere se c'è qualcuno (presenza umana).
    """
    import esp32_bridge
    dati = esp32_bridge.stark_station_data
    temp = dati.get("temperatura")
    umid = dati.get("umidita")
    pres = dati.get("presenza")
    
    if temp is None:
        return "Non ho ancora ricevuto aggiornamenti dai sensori della Stark Station."
    
    str_pres = "Rilevata presenza umana" if pres else "Nessuno presente"
    msg = f"Sensori Camera: {temp}°C, Umidità al {umid}%. {str_pres}."
    print(f"JARVIS: {msg}")
    return msg

@tool
def imposta_sveglia(ora: int, minuto: int, stop_ora: int = 9, stop_minuto: int = 45, abilitata: bool = True) -> str:
    """
    Imposta la sveglia programmata sulla Stark Station.
    - ora / minuto: orario di attivazione (alba rossa + buzzer)
    - stop_ora / stop_minuto: orario di spegnimento automatico
    - abilitata: True per attivare, False per disabilitare
    """
    params = {
        "ora":          ora,
        "minuto":       minuto,
        "stop_ora":     stop_ora,
        "stop_minuto":  stop_minuto,
        "abilitata":    "1" if abilitata else "0"
    }
    try:
        risposta = requests.get(f"{ESP32_IP}/sveglia_set", params=params, timeout=3)
        if risposta.status_code == 200:
            # Aggiorna stato locale per la dashboard
            try:
                from alarm.alarm_service import _stark_alarm
                _stark_alarm["ora"]          = ora
                _stark_alarm["minuto"]       = minuto
                _stark_alarm["stop_ora"]     = stop_ora
                _stark_alarm["stop_minuto"]  = stop_minuto
                _stark_alarm["abilitata"]    = abilitata
            except Exception:
                pass
            return risposta.text
        return f"Errore HTTP {risposta.status_code}"
    except requests.exceptions.RequestException as e:
        return f"Impossibile contattare la Stark Station. Errore: {e}"
