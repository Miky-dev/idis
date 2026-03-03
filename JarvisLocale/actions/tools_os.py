import os
import subprocess
from langchain_core.tools import tool

# Dizionario per la sicurezza (Whitelist di applicazioni consentite)
WHITELIST_APP = {
    "blocco note": "notepad.exe",
    "calcolatrice": "calc.exe",
    "esplora file": "opera.exe",
    "prompt": "cmd.exe",
    "browser": "start opera",
    "whatsapp": "cmd /c start whatsapp:", 
    "discord": os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe"),
    "spotify": "cmd /c start spotify:",
    "armoury crate": "cmd /c start armourycrate:",
    "antigravity": "antigravity",
    "task manager": "taskmgr.exe"
}
 
@tool
def apri_applicazione(nome_app: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente chiede esplicitamente di aprire, avviare o lanciare un programma, o chiede di compiere un'azione strettamente legata a queste app.
    Scegli il 'nome_app' SOLO tra queste opzioni esatte in base alla richiesta:
    - "whatsapp" (per messaggi)
    - "discord" (per chat vocali o community)
    - "antigravity" (per programmare)
    - "spotify" (per musica)
    - "armoury crate" (per statistiche di sistema, temperature, hardware Asus)
    - "task manager" (per uso RAM, CPU, processi)
    - "blocco note" (per scrivere appunti)
    - "calcolatrice" (per calcoli)
    - "esplora file" (per navigare file)
    - "browser" (per internet)
    Se la richiesta dell'utente non c'entra nulla con l'aprire app (es. "come stai?", "che ore sono?"), NON USARE QUESTO STRUMENTO.
    """
    nome_app = nome_app.lower().strip()
    comando = WHITELIST_APP.get(nome_app)
    
    if comando:
        try:
            # shell=True serve per comandi come 'start msedge'
            subprocess.Popen(comando, shell=True)
            return f"App '{nome_app}' aperta con successo."
        except Exception as e:
            return f"Errore durante l'apertura: {str(e)}"
    else:
        return f"Errore: L'app '{nome_app}' non è nella whitelist o non è stata riconosciuta."
