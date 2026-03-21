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
    Invia un comando alla Stark Station (sveglia ESP32).
    Usa questo strumento per attivare un protocollo sulla sveglia (es. se l'utente dice "protocollo alba rossa", l'azione sarà "rosso")
    oppure per spegnerla (es. se l'utente dice "spegni tutto", l'azione sarà "off").
    """
    url = f"{ESP32_IP}/{azione}"
    try:
        print(f"JARVIS: Invio comando '{azione}' alla Stark Station su {url}...")
        risposta = requests.get(url, timeout=3)
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

