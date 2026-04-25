import pyautogui
import pyperclip
import time
import os
import subprocess
import threading
import pygetwindow as gw
from langchain_core.tools import tool

_messaggio_in_attesa = {
    "contatto": None,
    "testo": None
}

# ✅ Tiene traccia se WhatsApp era già aperto
_whatsapp_aperto = False

def _apri_whatsapp_e_aspetta():
    """Apre WhatsApp e aspetta dinamicamente che sia pronto, invece di sleep fisso."""
    global _whatsapp_aperto
    os.system("cmd /c start whatsapp:")

    if _whatsapp_aperto:
        # ✅ Era già aperto — diamo tempo a Windows di portarlo in primo piano
        time.sleep(1.2)
    else:
        # Prima apertura — aspetta di più
        time.sleep(3.5)
        _whatsapp_aperto = True
    
    # Riporta in primo piano IDIS per permettere all'utente di vedere la richiesta e confermare
    _attiva_finestra_idis()

def _attiva_finestra_whatsapp():
    """Cerca e mette in primo piano la finestra di WhatsApp."""
    try:
        finestre = gw.getWindowsWithTitle('WhatsApp')
        if finestre:
            w = finestre[0]
            if w.isMinimized:
                w.restore()
            w.activate()
            time.sleep(0.6)
            return True
    except Exception as e:
        print(f"⚠️ Errore focus WhatsApp: {e}")
    return False

def _attiva_finestra_idis():
    """Cerca e mette in primo piano la finestra dell'app IDIS."""
    try:
        finestre = gw.getWindowsWithTitle('IDIS')
        for w in finestre:
            if w.title == 'IDIS':
                if w.isMinimized:
                    w.restore()
                w.activate()
                time.sleep(0.3)
                return True
    except Exception as e:
        print(f"⚠️ Errore focus IDIS: {e}")
    return False

@tool
def attiva_whatsapp() -> str:
    """Mette in primo piano la finestra di WhatsApp (se aperta)."""
    if _attiva_finestra_whatsapp():
        return "Finestra WhatsApp portata in primo piano."
    return "Non ho trovato la finestra di WhatsApp aperta."

@tool
def prepara_messaggio_whatsapp(contatto: str, testo: str) -> str:
    """
    PRIMO PASSO per inviare un messaggio WhatsApp.
    Prepara il messaggio e chiede conferma prima di inviarlo.
    - 'contatto': nome della persona o gruppo (es. "Marco", "Famiglia")
    - 'testo': testo del messaggio
    """
    _messaggio_in_attesa["contatto"] = contatto
    _messaggio_in_attesa["testo"] = testo

    # ✅ Pre-apri WhatsApp in background mentre IDIS risponde
    # Così quando l'utente conferma, WhatsApp è già pronto
    threading.Thread(target=_apri_whatsapp_e_aspetta, daemon=True).start()

    return (
        f"Messaggio pronto:\n"
        f"  A: {contatto}\n"
        f"  Testo: \"{testo}\"\n\n"
        f"Vuoi che lo invii? Rispondi 'sì' o 'no'."
    )

@tool
def conferma_invio_whatsapp() -> str:
    """
    SECONDO PASSO — invia il messaggio WhatsApp preparato.
    Usalo solo dopo conferma esplicita dell'utente.
    """
    contatto = _messaggio_in_attesa.get("contatto")
    testo = _messaggio_in_attesa.get("testo")

    if not contatto or not testo:
        return "Nessun messaggio in attesa. Usa prima 'prepara_messaggio_whatsapp'."

    try:
        # ✅ Assicura che WhatsApp sia in primo piano prima di inviare tasti
        _attiva_finestra_whatsapp()
        time.sleep(0.6)

        # Chiudi ricerche aperte
        pyautogui.press('esc')
        time.sleep(0.3)

        # Apri ricerca
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(0.6)

        # Pulisci e cerca contatto
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        _scrivi_testo(contatto)
        time.sleep(1.2)   # Attesa maggiore per i risultati di ricerca

        # Seleziona primo risultato
        pyautogui.press('down')
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(0.6)

        # Scrivi e invia
        _scrivi_testo(testo)
        time.sleep(0.4)
        pyautogui.press('enter')

        # Pulisci stato
        _messaggio_in_attesa["contatto"] = None
        _messaggio_in_attesa["testo"] = None

        # Riporta in primo piano IDIS dopo aver inviato il messaggio
        _attiva_finestra_idis()

        return f"Messaggio inviato a {contatto}."

    except Exception as e:
        return f"Errore durante l'invio: {str(e)}"

@tool
def annulla_messaggio_whatsapp() -> str:
    """Annulla il messaggio WhatsApp in attesa di conferma."""
    contatto = _messaggio_in_attesa.get("contatto")
    _messaggio_in_attesa["contatto"] = None
    _messaggio_in_attesa["testo"] = None
    return f"Messaggio a {contatto} annullato."


def _scrivi_testo(testo: str):
    """Scrive testo via clipboard per supportare accenti ed emoji."""
    try:
        pyperclip.copy(testo)
        pyautogui.hotkey('ctrl', 'v')
    except Exception:
        pyautogui.write(testo, interval=0.02)