import pyautogui
import time
import os
from langchain_core.tools import tool

@tool
def invia_messaggio_whatsapp(contatto: str, testo: str) -> str:
    """
    Usa QUESTO STRUMENTO per inviare un messaggio su WhatsApp.
    Estrazione obbligatoria dei parametri dalla frase dell'utente:
    - 'contatto': estrai ESATTAMENTE il nome della persona o del gruppo a cui inviare il messaggio (es. se chiede "invia a Marco ciao", il contatto è "Marco"). NON includere altre parole.
    - 'testo': estrai ESATTAMENTE o GENERA SOLO il testo del messaggio da inviare.
    Esempio: "Scrivi a mamma che arrivo tardi sul gruppo famiglia" -> contatto="mamma", testo="arrivo tardi".
    """
    try:
        # 1. Apri l'app di WhatsApp
        os.system("cmd /c start whatsapp:")
        # Aspettiamo il tempo necessario per l'apertura
        time.sleep(2.5)  

        # Premiamo esc per chiudere eventuali ricerche aperte
        pyautogui.press('esc')
        time.sleep(0.2)

        # 2. Usa la scorciatoia per la ricerca (Ctrl + F)
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(0.5)
        
        # Svuotiamo la barra di ricerca da testi precedenti
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(0.2)
        
        # 3. Digita il nome del contatto velocemente
        pyautogui.write(contatto)
        time.sleep(1)  # Aspetta che appaiano i risultati
        
        # 4. Spostati sul primo risultato e apri la chat
        pyautogui.press('down')
        time.sleep(0.2)
        pyautogui.press('enter')
        time.sleep(0.5)
        
        # 5. Scrivi il testo del messaggio senza rallentamenti
        pyautogui.write(testo)
        time.sleep(2)
        
        # 6. Invia il messaggio
        pyautogui.press('enter')
        
        return f"Il messaggio per {contatto} è stato digitato e inviato con successo."
    except Exception as e:
        return f"Errore durante l'automazione di WhatsApp: {str(e)}"
