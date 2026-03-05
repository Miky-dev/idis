import pyautogui
import pyperclip
import time
import os
from langchain_core.tools import tool

# Stato interno — salva il messaggio in attesa di conferma
_messaggio_in_attesa = {
    "contatto": None,
    "testo": None
}

@tool
def prepara_messaggio_whatsapp(contatto: str, testo: str) -> str:
    """
    PRIMO PASSO per inviare un messaggio WhatsApp.
    Usa questo tool per preparare il messaggio e chiedere conferma all'utente PRIMA di inviarlo.
    Dopo aver chiamato questo tool, chiedi SEMPRE all'utente: "Confermi l'invio?"
    - 'contatto': nome esatto della persona o gruppo (es. "Marco", "Famiglia")
    - 'testo': testo del messaggio da inviare
    """
    _messaggio_in_attesa["contatto"] = contatto
    _messaggio_in_attesa["testo"] = testo
    return (
        f"Messaggio pronto:\n"
        f"  A: {contatto}\n"
        f"  Testo: \"{testo}\"\n\n"
        f"Vuoi che lo invii? Rispondi 'sì' o 'no'."
    )

@tool
def conferma_invio_whatsapp() -> str:
    """
    SECONDO PASSO — invia il messaggio WhatsApp preparato in precedenza.
    Usa questo tool SOLO dopo che l'utente ha confermato esplicitamente con 'sì' o 'confermo'.
    Non richiedere parametri — usa il messaggio già salvato.
    """
    contatto = _messaggio_in_attesa.get("contatto")
    testo = _messaggio_in_attesa.get("testo")

    if not contatto or not testo:
        return "Nessun messaggio in attesa. Usa prima 'prepara_messaggio_whatsapp'."

    try:
        # 1. Apri WhatsApp
        os.system("cmd /c start whatsapp:")
        _attendi_finestra(2.5)

        # 2. Chiudi eventuali ricerche aperte
        pyautogui.press('esc')
        time.sleep(0.2)

        # 3. Apri la ricerca
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(0.5)

        # 4. Pulisci e digita il contatto
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(0.1)
        _scrivi_testo(contatto)
        time.sleep(1.0)

        # 5. Seleziona primo risultato
        pyautogui.press('down')
        time.sleep(0.2)
        pyautogui.press('enter')
        time.sleep(0.5)

        # 6. Scrivi il messaggio — usa clipboard per supportare accenti ed emoji
        _scrivi_testo(testo)
        time.sleep(0.3)

        # 7. Invia
        pyautogui.press('enter')

        # 8. Pulisci lo stato
        _messaggio_in_attesa["contatto"] = None
        _messaggio_in_attesa["testo"] = None

        return f"Messaggio inviato a {contatto}."

    except Exception as e:
        return f"Errore durante l'invio: {str(e)}"

@tool
def annulla_messaggio_whatsapp() -> str:
    """
    Annulla il messaggio WhatsApp in attesa di conferma.
    Usa questo tool se l'utente risponde 'no' o vuole annullare.
    """
    contatto = _messaggio_in_attesa.get("contatto")
    _messaggio_in_attesa["contatto"] = None
    _messaggio_in_attesa["testo"] = None
    return f"Messaggio a {contatto} annullato."


# ─── Funzioni di supporto ───────────────────────────────────────────

def _attendi_finestra(secondi_max: float):
    """Aspetta che WhatsApp sia aperto, con timeout massimo."""
    time.sleep(min(secondi_max, 2.5))

def _scrivi_testo(testo: str):
    """
    Scrive testo usando pyperclip (clipboard) invece di pyautogui.write().
    Questo supporta accenti, emoji e caratteri speciali italiani.
    """
    try:
        pyperclip.copy(testo)
        pyautogui.hotkey('ctrl', 'v')
    except Exception:
        # Fallback a write() se pyperclip non è disponibile
        pyautogui.write(testo, interval=0.02)