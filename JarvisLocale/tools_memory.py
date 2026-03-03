import json
import os
from langchain_core.tools import tool

FILE_MEMORIA = "memoria_utente.json"

def leggi_memoria():
    """Legge i dati salvati nel file JSON."""
    if not os.path.exists(FILE_MEMORIA):
        return {}
    try:
        with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def scrivi_memoria(dati):
    """Scrive i dati nel file JSON."""
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=4, ensure_ascii=False)

@tool
def ricorda_informazione(chiave: str, valore: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede esplicitamente di ricordare, imparare o annotare un'informazione personale su di lui (es. il suo nome, dove vive, che app preferisce, le sue abitudini).
    L'argomento 'chiave' deve essere una breve categoria in stile snake_case (es. 'app_messaggi', 'citta_residenza', 'nome_utente').
    L'argomento 'valore' è l'informazione vera e propria da ricordare (es. 'WhatsApp', 'Roma', 'Marco').
    """
    memoria_attuale = leggi_memoria()
    memoria_attuale[chiave] = valore
    scrivi_memoria(memoria_attuale)
    return f"Informazione salvata con successo nella memoria a lungo termine: {chiave} = {valore}"
