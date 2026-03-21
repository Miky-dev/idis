import os
import requests
import time
from langchain_core.tools import tool
from dotenv import load_dotenv

load_dotenv()

ESP32_IP = os.getenv("ESP32_SVEGLIA_IP", "http://192.168.1.50")

def verifica_connessione_sveglia():
    """Ping iniziale per verificare che la sveglia ESP32 sia online."""
    url = f"{ESP32_IP}/"
    try:
        # Timeout breve per non bloccare il thread a lungo
        requests.get(url, timeout=2)
        print(f"✅ JARVIS connesso a Stark Station (Sveglia ESP32) su {ESP32_IP}")
        return True
    except requests.exceptions.RequestException:
        print(f"⚠️ Stark Station (Sveglia ESP32) non raggiungibile su {ESP32_IP}. I comandi remoti potrebbero fallire.")
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
        "rosso": "alba_rossa",
        "rossa": "alba_rossa",
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

