import json
import os
from langchain_core.tools import tool

FILE_MEMORIA = "memoria_utente.json"

# ✅ Cache in RAM — evita I/O disco ad ogni messaggio
_cache_memoria = None

def leggi_memoria():
    global _cache_memoria
    if _cache_memoria is not None:
        return _cache_memoria
    if not os.path.exists(FILE_MEMORIA):
        _cache_memoria = {}
        return _cache_memoria
    try:
        with open(FILE_MEMORIA, "r", encoding="utf-8") as f:
            _cache_memoria = json.load(f)
    except:
        _cache_memoria = {}
    return _cache_memoria

def scrivi_memoria(dati):
    global _cache_memoria
    _cache_memoria = dati  # ✅ Aggiorna anche la cache
    with open(FILE_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=4, ensure_ascii=False)

@tool
def ricorda_informazione(chiave: str, valore: str) -> str:
    """
    Usa questo strumento SOLO quando l'utente ti chiede esplicitamente di ricordare un'informazione personale.
    'chiave': categoria in snake_case (es. 'nome_utente', 'citta_residenza').
    'valore': informazione da ricordare (es. 'Marco', 'Roma').
    """
    memoria_attuale = leggi_memoria()
    memoria_attuale[chiave] = valore
    scrivi_memoria(memoria_attuale)
    return f"Salvato: {chiave} = {valore}"
